from app.core import settings
from app.db import Document
def ingest(db,source,content):
    d=db.query(Document).filter_by(source=source).one_or_none()
    if d is None:d=Document(source=source,content=content);db.add(d)
    else:d.content=content
    db.commit();db.refresh(d);return d.id
def retrieve(db,query,limit=5):
    terms={t.lower() for t in query.split() if len(t)>2}; ranked=[]
    for d in db.query(Document).all():
        score=sum(d.content.lower().count(t) for t in terms)
        if score:ranked.append((score,d))
    ranked.sort(key=lambda x:x[0],reverse=True)
    return [{"source":d.source,"content":d.content[:5000]} for _,d in ranked[:limit]]
def answer(db,question):
    cfg=settings(); docs=retrieve(db,question)
    context="\\n\\n".join(f"SOURCE {d['source']}\\n{d['content']}" for d in docs)
    if not cfg.nebius_api_key or not cfg.nebius_model:
        return {"answer":"Nebius is not configured. Add NEBIUS_API_KEY and NEBIUS_MODEL to backend/.env. Retrieved sources: "+", ".join(d["source"] for d in docs),
                "sources":[d["source"] for d in docs]}
    from openai import OpenAI
    client=OpenAI(api_key=cfg.nebius_api_key,base_url=cfg.nebius_base_url)
    out=client.chat.completions.create(model=cfg.nebius_model,temperature=.1,messages=[
      {"role":"system","content":"You are VYOM, an ESA Mission-1 telemetry assistant. Answer only from supplied evidence, cite source names, state when evidence is insufficient. Never invent spacecraft state or issue commands."},
      {"role":"user","content":f"Question: {question}\\nEvidence:\\n{context or 'No matching documents.'}"}])
    return {"answer":out.choices[0].message.content,"sources":[d["source"] for d in docs]}
def research(query):
    key=settings().tavily_api_key
    if not key:return []
    from tavily import TavilyClient
    return TavilyClient(api_key=key).search(query=query,search_depth="basic",max_results=5).get("results",[])
