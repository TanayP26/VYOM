from __future__ import annotations
import math,os,re
from sqlalchemy.orm import Session
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from app.core import settings
from app.db import KnowledgeDocument

TOKEN=re.compile(r"[A-Za-z0-9_\-]{2,}")
def tokens(text):return [x.lower() for x in TOKEN.findall(text)]

def _trace(name):
    try:
        from langsmith import traceable
        return traceable(name=name)
    except Exception:
        return lambda fn:fn

def _configure_trace():
    cfg=settings()
    if cfg.langsmith_api_key:
        os.environ.setdefault("LANGSMITH_TRACING","true")
        os.environ.setdefault("LANGSMITH_API_KEY",cfg.langsmith_api_key)
        os.environ.setdefault("LANGSMITH_PROJECT",cfg.langsmith_project)

def upsert(db:Session,source:str,content:str,metadata:dict|None=None):
    d=db.query(KnowledgeDocument).filter_by(source=source).one_or_none()
    if d is None:d=KnowledgeDocument(source=source,content=content,metadata_json=metadata or {});db.add(d)
    else:d.content=content;d.metadata_json=metadata or d.metadata_json
    db.commit();db.refresh(d);return d.id

def retrieve(db:Session,query:str,limit=6):
    docs=db.query(KnowledgeDocument).all()
    if not docs:return []
    corpus=[d.content for d in docs]
    # Transparent hybrid: TF-IDF cosine + exact term evidence. No opaque vector DB.
    try:
        vectorizer=TfidfVectorizer(lowercase=True,ngram_range=(1,2),max_features=40000)
        matrix=vectorizer.fit_transform(corpus+[query]); cosine=cosine_similarity(matrix[-1],matrix[:-1]).ravel()
    except ValueError:
        cosine=[0.0]*len(docs)
    q=set(tokens(query));N=max(1,len(docs));dfs={t:sum(1 for d in docs if t in set(tokens(d.content))) for t in q}
    ranked=[]
    for idx,d in enumerate(docs):
        dt=tokens(d.content);lex=0.0
        for t in q:
            tf=dt.count(t)
            if tf:lex+=(1+math.log1p(tf))*math.log((N+1)/(dfs.get(t,0)+.5))
        score=float(cosine[idx])+0.08*lex
        if score>0:ranked.append((score,d))
    ranked.sort(key=lambda x:x[0],reverse=True)
    # Reserve evidence slots for the current evaluated policy when the question
    # explicitly concerns policy, detector performance or the Run 11 evaluation.
    # Historical documents remain available and retain their original scores.
    query_lower=query.lower()
    current_policy_query=bool(re.search(
        r"temporal[- ]first|m1\.3\.1|run\s*#?\s*11\b|channel[_ -]?13\b|\bb1\b|generaliz|recall|false alarms?|incident burden|detector performance|scientific limitations",
        query_lower
    ))
    if current_policy_query:
        priority=("docs/MILESTONE1_3_1_B1_EVALUATION.md",
                  "docs/MILESTONE1_3_1_OPERATOR_POLICY.md")
        by_source={d.source:(score,d) for score,d in ranked}
        by_doc={d.source:d for d in docs}
        reserved=[by_source.get(name,(0.0,by_doc[name])) for name in priority if name in by_doc]
        reserved_sources={d.source for _,d in reserved}
        ranked=reserved+[(score,d) for score,d in ranked if d.source not in reserved_sources]
    return [{"source":d.source,"content":d.content[:7000],"metadata":d.metadata_json,"score":float(s)} for s,d in ranked[:limit]]

@_trace("vyom_nebius_grounded_answer")
def _generate(question,evidence):
    cfg=settings();from openai import OpenAI
    client=OpenAI(api_key=cfg.nebius_api_key,base_url=cfg.nebius_base_url)
    system=("You are VYOM, a spacecraft telemetry decision-support assistant. Use only supplied internal evidence. "
            "Separate Dataset Fact, Statistical Observation, Model Inference and System Recommendation. Cite source names inline. "
            "When describing the current policy, distinguish the latest evaluated M1.3.1 result from historical development evidence. A completed run is not proof of good detection quality. Run 10 and Run 11 used different channels; their incident counts do not establish a controlled before/after policy improvement. Within Run 11, distinguish the combined candidate count from the independent IF comparator. A shared annotation ID means physical-event independence is not established, not that dependence has been proven. Distinguish event recall (matched annotated events divided by annotated events) from labelled sample recall. Timestamp-only history capacity is a required bound, not necessarily observed history usage. Unmatched predictions have unknown physical truth. Do not treat client-supplied context as independently verified evidence. If evidence is insufficient, say so. Never claim flight qualification, invent spacecraft state, or issue commands.")
    out=client.chat.completions.create(model=cfg.nebius_model,temperature=.1,messages=[{"role":"system","content":system},{"role":"user","content":f"Question: {question}\n\nEvidence:\n{evidence or 'No matching internal evidence.'}"}])
    return out.choices[0].message.content

def answer(db:Session,question:str,context:dict|None=None):
    _configure_trace();cfg=settings();docs=retrieve(db,question);context=context or {}
    evidence="\n\n".join(f"SOURCE: {d['source']}\n{d['content']}" for d in docs)
    if context:evidence=f"ACTIVE PRODUCT CONTEXT (client-supplied; not independently verified):\n{context}\n\n"+evidence
    sources=[d["source"] for d in docs]
    if not cfg.nebius_api_key or not cfg.nebius_model:
        return {"mode":"VYOM Knowledge","answer":"Nebius generation is not configured. The strongest internal evidence has still been retrieved below. Configure NEBIUS_API_KEY and NEBIUS_MODEL to generate a grounded explanation.","sources":sources,"evidence":docs[:3]}
    return {"mode":"VYOM Knowledge","answer":_generate(question,evidence),"sources":sources}

@_trace("vyom_tavily_live_research")
def external_research(query:str):
    _configure_trace();cfg=settings()
    if not cfg.tavily_api_key:return {"mode":"Live Research","results":[],"note":"TAVILY_API_KEY is not configured."}
    from tavily import TavilyClient
    result=TavilyClient(api_key=cfg.tavily_api_key).search(query=query,search_depth="advanced",max_results=6)
    return {"mode":"Live Research","results":result.get("results",[]),"note":"External research is not internal mission telemetry evidence."}
