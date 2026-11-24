from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
import hashlib, json, math, os, sqlite3, tempfile, time
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler

from app.dataset import channel_parquet, channel_annotations, metadata
from app.operator_policy import build_combined_policy_candidates, operator_policy_metadata

@dataclass(frozen=True)
class Protocol:
    train_fraction: float = .60
    validation_fraction: float = .20
    quantile: float = .99
    min_threshold: float = 3.0
    stat_threshold: float = 6.0
    if_contamination: float = .01
    if_estimators: int = 100
    seed: int = 42
    max_train_rows: int = 10_000
    persistence: int = 3
    release_ratio: float = .5
    cadence_confirm: int = 8
    cadence_tolerance: float = .05
    gap_factor: float = 3.0
    event_bridge_cadences: float = 2.0

PROTOCOL = Protocol()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()

class ExactOrderStore:
    """Disk-backed exact order statistics using SQLite; slow but bounded and auditable."""
    def __init__(self, directory: Path, name: str):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory/f"{name}.sqlite3"
        if self.path.exists(): self.path.unlink()
        self.db = sqlite3.connect(self.path)
        self.db.execute("PRAGMA journal_mode=OFF")
        self.db.execute("PRAGMA synchronous=OFF")
        self.db.execute("CREATE TABLE values_(v REAL NOT NULL)")
        self.count=0
    def add(self, values):
        arr=np.asarray(values,dtype=np.float64); arr=arr[np.isfinite(arr)]
        if len(arr):
            self.db.executemany("INSERT INTO values_(v) VALUES(?)", ((float(x),) for x in arr)); self.count+=len(arr)
    def finish(self):
        self.db.commit(); self.db.execute("CREATE INDEX IF NOT EXISTS idx_v ON values_(v)"); self.db.commit()
    def at(self, rank:int)->float:
        if not 0<=rank<self.count: raise ValueError("order-statistic rank outside observations")
        row=self.db.execute("SELECT v FROM values_ ORDER BY v LIMIT 1 OFFSET ?",(int(rank),)).fetchone()
        return float(row[0])
    def median(self)->float:
        self.finish()
        if not self.count: raise ValueError("no finite observations")
        if self.count%2: return self.at(self.count//2)
        a=self.at(self.count//2-1); b=self.at(self.count//2)
        return float(np.mean(np.array([a,b],dtype=np.float64)))
    def quantile_higher(self,q:float)->float:
        self.finish()
        if not self.count: raise ValueError("no finite observations")
        rank=int(math.ceil((self.count-1)*q)); return self.at(rank)
    def count_above(self,x:float)->int:
        self.finish(); return int(self.db.execute("SELECT COUNT(*) FROM values_ WHERE v>?",(float(x),)).fetchone()[0])
    def close(self):
        try:self.db.close()
        finally:
            if self.path.exists(): self.path.unlink()

class ParquetStream:
    def __init__(self,path:Path,batch_rows=5000):
        import pyarrow.parquet as pq
        self.path=Path(path); self.batch_rows=batch_rows; self._pq=pq
        with pq.ParquetFile(self.path) as f:
            self.rows=f.metadata.num_rows
            names=f.schema_arrow.names
            if "timestamp" not in names or len(names)!=2: raise ValueError("expected timestamp + one value column")
            self.value_col=next(x for x in names if x!="timestamp")
    def batches(self,start=0,stop=None):
        stop=self.rows if stop is None else stop
        if not 0<=start<=stop<=self.rows: raise ValueError("invalid stream range")
        pos=0
        with self._pq.ParquetFile(self.path) as f:
            for batch in f.iter_batches(batch_size=self.batch_rows):
                n=batch.num_rows; left=max(0,start-pos); right=min(n,stop-pos)
                if left<right:
                    x=batch.slice(left,right-left).to_pandas()
                    if "timestamp" in x: x=x.set_index("timestamp")
                    x.index=pd.to_datetime(x.index,utc=True)
                    yield x.iloc[:,0].astype("float64")
                pos+=n
                if pos>=stop:return
    def timestamp(self,row:int):
        return next(self.batches(row,row+1)).index[0]

class AdaptiveCadence:
    def __init__(self, initial:float, tolerance=.05, confirm=8, gap_factor=3.0):
        self.current=float(initial); self.tolerance=tolerance; self.confirm=confirm; self.gap_factor=gap_factor
        self.prev=None; self.candidate=None; self.count=0
    def update(self,index:pd.DatetimeIndex):
        out=np.full(len(index),self.current,dtype=float); gaps=[]
        for i,ts in enumerate(index):
            if self.prev is None: self.prev=ts; out[i]=self.current; continue
            d=(ts-self.prev).total_seconds(); previous=self.current
            if d>previous*self.gap_factor:
                gaps.append({"start":(self.prev+pd.Timedelta(1,'ns')).isoformat(),"end":(ts-pd.Timedelta(1,'ns')).isoformat(),"elapsed_seconds":d,"expected_cadence_seconds":previous})
            similar=abs(d-previous)<=max(1e-9,abs(previous)*self.tolerance)
            if not similar and d>0 and d<=previous*self.gap_factor:
                if self.candidate is not None and abs(d-self.candidate)<=max(1e-9,abs(self.candidate)*self.tolerance): self.count+=1
                else:self.candidate=d;self.count=1
                if self.count>=self.confirm:
                    self.current=float(self.candidate);self.candidate=None;self.count=0
            else:
                self.candidate=None;self.count=0
            out[i]=self.current; self.prev=ts
        return out,gaps

class EventAccumulator:
    def __init__(self,channel:str,detector:str,bridge=2.0):
        self.channel=channel;self.detector=detector;self.bridge=bridge;self.open=None
    def update(self,index,flags,scores,cadences):
        emitted=[]
        for ts,flag,score,cad in zip(index,np.asarray(flags,bool),np.asarray(scores,float),np.asarray(cadences,float)):
            if flag:
                if self.open is None:
                    self.open={"channel":self.channel,"detector":self.detector,"start":ts,"end":ts,"peak_time":ts,"peak_score":float(score),"count":1,"last_cadence":float(cad)}
                elif (ts-self.open["end"]).total_seconds()<=self.bridge*max(float(cad),self.open["last_cadence"]):
                    self.open["end"]=ts;self.open["count"]+=1;self.open["last_cadence"]=float(cad)
                    if score>self.open["peak_score"]:self.open["peak_score"]=float(score);self.open["peak_time"]=ts
                else:
                    emitted.append(self._finish()); self.open={"channel":self.channel,"detector":self.detector,"start":ts,"end":ts,"peak_time":ts,"peak_score":float(score),"count":1,"last_cadence":float(cad)}
            elif self.open is not None:
                emitted.append(self._finish())
        return emitted
    def _finish(self):
        e=self.open;self.open=None
        e["start"]=e["start"].isoformat();e["end"]=e["end"].isoformat();e["peak_time"]=e["peak_time"].isoformat();
        e["duration_seconds"]=(pd.Timestamp(e["end"])-pd.Timestamp(e["start"])).total_seconds();e.pop("last_cadence",None);return e
    def finish(self): return [self._finish()] if self.open else []


def initial_cadence(stream:ParquetStream, stop:int)->float:
    values=[]; prev=None
    for s in stream.batches(0,min(stop,10001)):
        idx=s.index
        if prev is not None: values.append((idx[0]-prev).total_seconds())
        if len(idx)>1: values.extend(np.diff(idx.view('i8'))/1e9)
        prev=idx[-1]
    arr=np.asarray(values,float);arr=arr[np.isfinite(arr)&(arr>0)]
    if not len(arr): raise ValueError("cannot infer cadence")
    return float(np.median(arr))


def fit_exact_stats(stream:ParquetStream,stop:int,scratch:Path):
    values=ExactOrderStore(scratch,"train_values"); steps=ExactOrderStore(scratch,"train_steps")
    prev=np.nan; rows=0
    try:
        for s in stream.batches(0,stop):
            a=s.to_numpy(float);values.add(a);rows+=len(a)
            joined=np.r_[prev,a]; d=np.abs(np.diff(joined)); steps.add(d[d>0]); prev=a[-1]
        med=values.median(); dev=ExactOrderStore(scratch,"train_dev")
        try:
            for s in stream.batches(0,stop): dev.add(np.abs(s.to_numpy(float)-med))
            mad=dev.median(); sigma=1.4826*mad
        finally:dev.close()
        quantum=steps.median() if steps.count else 0.; floor=max(.5*quantum,.1*sigma,1e-6*max(1.,abs(med)))
        return {"location":med,"robust_sigma":sigma,"quantum":quantum,"floor":floor,"global_scale":max(sigma,floor),"change_scale":max(quantum,floor),"rows":rows}
    finally: values.close();steps.close()


def temporal_scores(series:pd.Series, stats:dict, prev_value:float|None):
    a=series.to_numpy(float); previous=a[0] if prev_value is None else prev_value
    diff=np.abs(np.diff(np.r_[previous,a]))
    point=diff/stats["change_scale"]
    interval=np.abs(a-stats["location"])/stats["global_scale"]
    return point,interval,float(a[-1])


def correlate(events:list[dict],ann:pd.DataFrame,cadence:float):
    if ann.empty:
        for e in events:e["annotation_ids"]=[];e["categories"]=[]
        return events
    ann=ann.copy();ann.StartTime=pd.to_datetime(ann.StartTime,utc=True);ann.EndTime=pd.to_datetime(ann.EndTime,utc=True)
    for e in events:
        a,b=pd.Timestamp(e["start"]),pd.Timestamp(e["end"]); ids=[];cats=[]
        for r in ann.itertuples():
            s,t=r.StartTime,r.EndTime
            if s==t:
                tol=pd.Timedelta(seconds=cadence/2);s-=tol;t+=tol
            if a<=t and b>=s:ids.append(str(r.ID));cats.append(str(r.Category))
        e["annotation_ids"]=sorted(set(ids));e["categories"]=sorted(set(cats))
    return events


def severity(score:float)->str:
    if score>=10:return "critical"
    if score>=5:return "high"
    if score>=2:return "medium"
    return "low"


def run_channel(channel:str,output:Path,batch_rows=5000,protocol:Protocol=PROTOCOL,progress=None):
    path=channel_parquet(channel); stream=ParquetStream(path,batch_rows); n=stream.rows
    train=int(n*protocol.train_fraction); valid=int(n*(protocol.train_fraction+protocol.validation_fraction))
    if min(train,valid-train,n-valid)<30: raise ValueError(f"{channel}: insufficient observations")
    output.mkdir(parents=True,exist_ok=True); scratch=output/"scratch";scratch.mkdir(exist_ok=True)
    cfg={"channel":channel,"protocol":asdict(protocol),"operator_policy":operator_policy_metadata(),"source_sha256":sha256(path),"rows":n,"split":{"train":train,"validation":valid-train,"test":n-valid}}
    (output/"configuration.json").write_text(json.dumps(cfg,indent=2),encoding="utf-8")
    started=time.perf_counter(); cadence0=initial_cadence(stream,train); stats=fit_exact_stats(stream,train,scratch)
    # deterministic bounded training sample for IF
    rng=np.random.default_rng(protocol.seed); sample=[]; seen=0; prev=None
    for s in stream.batches(0,train):
        a=s.to_numpy(float)
        p,i,prev=temporal_scores(s,stats,prev)
        feats=np.c_[a,p,i]
        for row in feats:
            seen+=1
            if len(sample)<protocol.max_train_rows: sample.append(row.copy())
            else:
                j=int(rng.integers(0,seen))
                if j<protocol.max_train_rows:sample[j]=row.copy()
    sample=np.asarray(sample,float); scaler=RobustScaler().fit(sample); iso=IsolationForest(n_estimators=protocol.if_estimators,contamination=protocol.if_contamination,random_state=protocol.seed,n_jobs=2).fit(scaler.transform(sample))
    # validation exact thresholds
    point_store=ExactOrderStore(scratch,"val_point");interval_store=ExactOrderStore(scratch,"val_interval")
    train_boundary=stream.timestamp(train)
    prev=None; cadence=AdaptiveCadence(cadence0,protocol.cadence_tolerance,protocol.cadence_confirm,protocol.gap_factor)
    for s in stream.batches(0,valid):
        cds,_=cadence.update(s.index);p,i,prev=temporal_scores(s,stats,prev)
        if s.index[-1]>=train_boundary:
            mask=s.index>=train_boundary;point_store.add(p[mask]);interval_store.add(i[mask])
    point_t=max(protocol.min_threshold,point_store.quantile_higher(protocol.quantile)); interval_t=max(protocol.min_threshold,interval_store.quantile_higher(protocol.quantile));point_store.close();interval_store.close()
    frozen={"point_threshold":point_t,"interval_threshold":interval_t,"training":stats,"initial_cadence_seconds":cadence0,"operator_policy":operator_policy_metadata(),"frozen_at":utc_now()}
    (output/"fitted.json").write_text(json.dumps(frozen,indent=2),encoding="utf-8")
    # Prepare test-only truth before scoring. Labels never enter fitting/calibration.
    ann=channel_annotations(channel).copy()
    test_start,test_end=stream.timestamp(valid),stream.timestamp(n-1)
    ann["StartTime"]=pd.to_datetime(ann.StartTime,utc=True);ann["EndTime"]=pd.to_datetime(ann.EndTime,utc=True)
    tolerance=pd.Timedelta(seconds=cadence0/2)
    effective_start=ann.StartTime.where(ann.StartTime!=ann.EndTime,ann.StartTime-tolerance)
    effective_end=ann.EndTime.where(ann.StartTime!=ann.EndTime,ann.EndTime+tolerance)
    test_truth=ann[(effective_end>=test_start)&(effective_start<=test_end)].copy()
    value_truth=test_truth[test_truth.Category.isin(["Anomaly","Rare Event"])].copy()
    gap_truth=test_truth[test_truth.Category=="Communication Gap"].copy()
    target_row=metadata()["channels"].set_index("Channel").loc[channel]
    labelled_channel=str(target_row["Target"]).upper()=="YES"

    # warm causal state through train+validation, then fresh event groupers for test
    prev=None; cadence=AdaptiveCadence(cadence0,protocol.cadence_tolerance,protocol.cadence_confirm,protocol.gap_factor); persistent=0; active=False
    for s in stream.batches(0,valid):
        cds,_=cadence.update(s.index);p,i,prev=temporal_scores(s,stats,prev)
        for x in i:
            if x>interval_t:persistent+=1
            elif active and x>interval_t*protocol.release_ratio:pass
            else:persistent=0;active=False
            if persistent>=protocol.persistence:active=True
    groupers={k:EventAccumulator(channel,k,protocol.event_bridge_cadences) for k in ("temporal_point","temporal_interval","combined","isolation_forest","timestamp_gap")}
    events=[]; test_rows=0; flagged=0
    sample_tp=sample_fp=sample_fn=sample_tn=0
    baseline_flagged=full_threshold_flagged=0
    exposure_seconds=0.0; exposure_prev=None
    for s in stream.batches(valid,n):
        cds,gaps=cadence.update(s.index);p,i,prev=temporal_scores(s,stats,prev)
        point=p>point_t; interval=np.zeros(len(s),bool)
        for idx,x in enumerate(i):
            if x>interval_t:persistent+=1
            elif active and x>interval_t*protocol.release_ratio:pass
            else:persistent=0;active=False
            if persistent>=protocol.persistence:active=True
            interval[idx]=active
        feats=np.c_[s.to_numpy(float),p,i]; iso_score=-iso.decision_function(scaler.transform(feats)); iso_flag=iso.predict(scaler.transform(feats))==-1
        temporal_flag=point|interval
        temporal_ratio=np.maximum(p/max(point_t,1e-9),i/max(interval_t,1e-9))
        policy_candidates=build_combined_policy_candidates(temporal_flag,iso_flag,temporal_ratio)
        combined=policy_candidates["combined"]
        baseline_flagged+=int(policy_candidates["combined_m13_baseline"].sum())
        full_threshold_flagged+=int(policy_candidates["combined_if_full_threshold"].sum())
        for name,flags,scores in (("temporal_point",point,p),("temporal_interval",interval,i),("isolation_forest",iso_flag,iso_score),("combined",combined,temporal_ratio)):
            events.extend(groupers[name].update(s.index,flags,scores,cds)); flagged+=int(flags.sum()) if name=="combined" else 0
        # Sample metrics are assumption-dependent and only defined on labelled Target=YES channels.
        positive=np.zeros(len(s),dtype=bool)
        for r in value_truth.itertuples():
            left,right=r.StartTime,r.EndTime
            if left==right:left-=tolerance;right+=tolerance
            positive|=((s.index>=left)&(s.index<=right))
        if labelled_channel:
            sample_tp+=int(np.count_nonzero(combined & positive));sample_fp+=int(np.count_nonzero(combined & ~positive))
            sample_fn+=int(np.count_nonzero(~combined & positive));sample_tn+=int(np.count_nonzero(~combined & ~positive))
        # Observed exposure excludes gaps > 3 contemporaneous cadences.
        times=s.index
        if exposure_prev is not None:
            d=(times[0]-exposure_prev).total_seconds();
            if 0<d<=3*cds[0]:exposure_seconds+=d
        if len(times)>1:
            ds=np.diff(times.view("i8"))/1e9; exposure_seconds+=float(ds[(ds>0)&(ds<=3*cds[1:])].sum())
        exposure_prev=times[-1]
        for g in gaps:
            ts=pd.Timestamp(g["end"]);score=g["elapsed_seconds"]/max(g["expected_cadence_seconds"],1e-9)
            events.append({"channel":channel,"detector":"timestamp_gap","start":g["start"],"end":g["end"],"peak_time":ts.isoformat(),"peak_score":score,"count":0,"duration_seconds":g["elapsed_seconds"],"evidence":{"cause":"unknown","expected_cadence_seconds":g["expected_cadence_seconds"]}})
        test_rows+=len(s)
        if progress:progress(test_rows,n-valid)
    for g in groupers.values():events.extend(g.finish())
    events=correlate(events,ann,cadence0)
    for e in events:e["severity"]=severity(float(e["peak_score"]));e.setdefault("evidence",{})
    # one-to-one event metrics for test-only value truth under nominal-complement benchmark convention
    combined=[e for e in events if e["detector"]=="combined"]
    truth=value_truth.copy(); matched_truth=set();matched_pred=0
    for e in combined:
        for idx,r in truth.iterrows():
            if idx in matched_truth:continue
            a,b=pd.Timestamp(e["start"]),pd.Timestamp(e["end"]);s,t=r.StartTime,r.EndTime
            if s==t:s-=pd.Timedelta(seconds=cadence0/2);t+=pd.Timedelta(seconds=cadence0/2)
            if a<=t and b>=s: matched_truth.add(idx);matched_pred+=1;break
    precision=matched_pred/len(combined) if combined else (1.0 if not len(truth) else 0.0);recall=matched_pred/len(truth) if len(truth) else None
    f1=2*precision*recall/(precision+recall) if recall is not None and precision+recall else (0.0 if recall is not None else None)
    # Communication-gap event recall is separate from value-anomaly scoring.
    gap_predictions=[e for e in events if e["detector"]=="timestamp_gap"];gap_matched=set();gap_tp=0
    for e in gap_predictions:
        for idx,r in gap_truth.iterrows():
            if idx in gap_matched:continue
            if pd.Timestamp(e["start"])<=r.EndTime and pd.Timestamp(e["end"])>=r.StartTime:gap_matched.add(idx);gap_tp+=1;break
    sample_precision=sample_tp/(sample_tp+sample_fp) if labelled_channel and sample_tp+sample_fp else (0.0 if labelled_channel else None)
    sample_recall=sample_tp/(sample_tp+sample_fn) if labelled_channel and sample_tp+sample_fn else None
    sample_f1=2*sample_precision*sample_recall/(sample_precision+sample_recall) if sample_precision is not None and sample_recall is not None and sample_precision+sample_recall else (0.0 if sample_recall is not None else None)
    report={"channel":channel,"status":"completed","rows":n,"split":{"train_rows":train,"validation_rows":valid-train,"test_rows":n-valid,"test_start":test_start.isoformat(),"test_end":test_end.isoformat()},"test_rows":test_rows,"events":len(events),"combined_events":len(combined),"combined_flagged_samples":flagged,"operator_policy":operator_policy_metadata(),"policy_diagnostics":{"active_temporal_first_flagged_samples":flagged,"m13_baseline_half_threshold_flagged_samples":baseline_flagged,"full_threshold_challenger_flagged_samples":full_threshold_flagged,"interpretation":"Alternative policy counts are diagnostics only; active operator incidents use temporal flags only."},"sample_metrics_nominal_complement":{"available":labelled_channel,"tp":sample_tp if labelled_channel else None,"fp":sample_fp if labelled_channel else None,"fn":sample_fn if labelled_channel else None,"tn":sample_tn if labelled_channel else None,"precision":sample_precision,"recall":sample_recall,"f1":sample_f1,"confirmed_negative_samples":0,"interpretation":"Assumption-dependent on labelled channels; unannotated does not mean independently confirmed physical normal."},"event_metrics_nominal_complement":{"precision":precision if labelled_channel else None,"recall":recall,"f1":f1 if labelled_channel else None,"matched":matched_pred,"truth":len(truth),"false_events_per_observation_day":((len(combined)-matched_pred)*86400/exposure_seconds) if labelled_channel and exposure_seconds else None,"note":"VYOM closed-overlap one-to-one metric; not ESA official alarming/affiliation metric"},"communication_gap":{"predicted":len(gap_predictions),"truth":len(gap_truth),"matched":gap_tp,"recall":gap_tp/len(gap_truth) if len(gap_truth) else None},"resources":{"wall_seconds":time.perf_counter()-started,"observed_test_exposure_seconds":exposure_seconds},"fitted":frozen,"scientific_limits":["Unannotated periods follow the benchmark nominal-complement convention, not independently confirmed physical normality.","Target=NO is never used as a supervised normal class.","Retrospective benchmark results are not external blind validation."]}
    with (output/"events.jsonl").open('w',encoding='utf-8') as f:
        for e in events:f.write(json.dumps(e,default=str)+"\n")
    (output/"report.json").write_text(json.dumps(report,indent=2,default=str),encoding='utf-8')
    md=f"""# VYOM channel report — {channel}

- Status: **completed**
- Rows: **{n:,}**
- Test rows: **{test_rows:,}**
- Combined events: **{len(combined):,}**
- Value truth events in test: **{len(truth):,}**
- Matched value events: **{matched_pred:,}**
- Event precision (nominal-complement assumption): **{report['event_metrics_nominal_complement']['precision']}**
- Event recall: **{report['event_metrics_nominal_complement']['recall']}**
- Event F1: **{report['event_metrics_nominal_complement']['f1']}**
- Communication-gap predictions/truth/matched: **{len(gap_predictions)} / {len(gap_truth)} / {gap_tp}**
- Wall time: **{report['resources']['wall_seconds']:.2f} s**

## Scientific disclosure

This is VYOM's retrospective 60/20/20 protocol. Unannotated periods follow the benchmark nominal-complement convention where assumption-dependent precision/F1 are shown. Target=NO is not a supervised negative class. This report is not equivalent to the official ESA leaderboard metric and does not establish flight readiness.
"""
    (output/"report.md").write_text(md,encoding="utf-8")
    for p in scratch.glob('*'):p.unlink()
    try:scratch.rmdir()
    except OSError:pass
    return report,events
