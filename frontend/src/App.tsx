import{useEffect,useState}from"react";
const API=import.meta.env.VITE_API_URL||"http://localhost:8000/api";
type Run={id:number;status:string;processed:number;total:number;summary:any;error?:string};
type Event={id:number;channel:string;timestamp:string;score:number;severity:string;annotation?:string};
export default function App(){
 const[runs,setRuns]=useState<Run[]>([]),[events,setEvents]=useState<Event[]>([]),[q,setQ]=useState(""),[answer,setAnswer]=useState(""),[busy,setBusy]=useState(false);
 async function refresh(){try{const[a,b]=await Promise.all([fetch(API+"/analysis/runs"),fetch(API+"/events?limit=100")]);setRuns(await a.json());setEvents(await b.json())}catch{}}
 useEffect(()=>{refresh();const t=setInterval(refresh,4000);return()=>clearInterval(t)},[]);
 async function start(){setBusy(true);try{await fetch(API+"/analysis/runs",{method:"POST"});await refresh()}finally{setBusy(false)}}
 async function ask(){setBusy(true);try{const r=await fetch(API+"/chat",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({question:q})});const d=await r.json();setAnswer(d.answer||"No answer returned")}catch{setAnswer("API unavailable. Start the backend first.")}finally{setBusy(false)}}
 const run=runs[0];
 return <main><header><b>VYOM <small>MISSION INTELLIGENCE</small></b><span>● SYSTEM READY</span></header>
 <section className="hero"><div><label>ESA / MISSION 01 / TELEMETRY INTELLIGENCE</label><h1>Spacecraft health.<br/><i>Seen before it fails.</i></h1><p>76-channel telemetry analysis and anomaly intelligence workspace.</p><button disabled={busy} onClick={start}>{busy?"WORKING…":"RUN FULL 76-CHANNEL ANALYSIS"}</button></div><div className="orb">V</div></section>
 <section className="stats"><Metric title="CHANNELS IN SCOPE" value="76"/><Metric title="LATEST RUN" value={run?`#${run.id}`:"—"}/><Metric title="PROCESSED" value={run?`${run.processed}/${run.total}`:"0/76"}/><Metric title="DETECTIONS" value={run?.summary?.detection_events??events.length}/></section>
 <Panel title="Analysis runs"><p>{run?`Run #${run.id} · ${run.status} · ${run.processed}/${run.total} channels`:"No analysis runs yet."}</p>{run?.error&&<p className="error">{run.error}</p>}</Panel>
 <Panel title="Detection stream"><div className="scroll"><table><thead><tr><th>CHANNEL</th><th>UTC TIME</th><th>SCORE</th><th>SEVERITY</th><th>ANNOTATION</th></tr></thead><tbody>{events.slice(0,40).map(e=><tr key={e.id}><td>{e.channel}</td><td>{new Date(e.timestamp).toLocaleString()}</td><td>{e.score.toFixed(3)}</td><td>{e.severity}</td><td>{e.annotation||"Unlabelled candidate"}</td></tr>)}</tbody></table>{!events.length&&<p>No detections yet.</p>}</div></Panel>
 <Panel title="VYOM assistant"><p>Ask questions about documents ingested into the knowledge base. Nebius credentials are required for generated answers.</p><div className="ask"><input value={q} onChange={e=>setQ(e.target.value)} placeholder="Ask about telemetry or mission evidence…"/><button disabled={busy||q.length<3} onClick={ask}>ASK</button></div>{answer&&<pre>{answer}</pre>}</Panel>
 <footer>VYOM · DECISION SUPPORT ONLY · NO SPACECRAFT COMMAND EXECUTION</footer></main>
}
function Metric({title,value}:{title:string,value:any}){return <div><small>{title}</small><strong>{value}</strong></div>}
function Panel({title,children}:{title:string,children:any}){return <section className="panel"><h2>{title}</h2>{children}</section>}
