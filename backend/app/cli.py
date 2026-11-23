from __future__ import annotations
import argparse,json
from pathlib import Path
from app.dataset import mission_summary,channel_catalog
from app.science import run_channel
from app.core import settings

def main():
    p=argparse.ArgumentParser(description="VYOM final-product CLI")
    sub=p.add_subparsers(dest="command",required=True)
    sub.add_parser("status")
    run=sub.add_parser("run");run.add_argument("channels",nargs="+");run.add_argument("--output",default=None);run.add_argument("--batch-rows",type=int,default=5000)
    full=sub.add_parser("full");full.add_argument("--confirm",action="store_true");full.add_argument("--output",default=None);full.add_argument("--batch-rows",type=int,default=5000)
    args=p.parse_args()
    if args.command=="status":print(json.dumps(mission_summary(),indent=2));return
    if args.command=="full" and not args.confirm:raise SystemExit("Refusing full retrospective benchmark without --confirm")
    available={x['channel'] for x in channel_catalog() if x['ingested']};channels=sorted(available,key=lambda x:int(x.split('_')[-1])) if args.command=="full" else args.channels
    bad=set(channels)-available
    if bad:raise SystemExit(f"Unavailable channels: {sorted(bad)}")
    out=Path(args.output).resolve() if args.output else settings().resolve(settings().artifact_dir)/"cli_run"
    summary=[]
    for i,ch in enumerate(channels,1):
        print(f"[{i}/{len(channels)}] {ch}",flush=True)
        report,_=run_channel(ch,out/ch,batch_rows=args.batch_rows);summary.append(report)
    result={"status":"completed","channels":len(summary),"events":sum(x['events'] for x in summary),"output":str(out)}
    (out/"manifest.json").write_text(json.dumps({"runs":summary,**result},indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))

if __name__=="__main__":main()
