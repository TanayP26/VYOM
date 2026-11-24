import {useState} from "react";

function safeLink(url:string){try{const u=new URL(url);return u.protocol==="https:"||u.protocol==="http:"?u.href:null}catch{return null}}
function Inline({text}:{text:string}){
 const parts=text.split(/(\*\*[^*\n]+\*\*|\x60[^\x60\n]+\x60|\[[^\]\n]+\]\(https?:\/\/[^\s)]+\))/g);
 return <>{parts.map((part,i)=>{if(part.startsWith("**")&&part.endsWith("**"))return <strong key={i}>{part.slice(2,-2)}</strong>;if(part.startsWith("`")&&part.endsWith("`"))return <code key={i}>{part.slice(1,-1)}</code>;const match=part.match(/^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/);const link=match&&safeLink(match[2]);return match&&link?<a key={i} href={link} target="_blank" rel="noopener noreferrer">{match[1]}</a>:part})}</>
}

export function EvidenceMarkdown({text}:{text:string}){
 const lines=text.replace(/\r\n/g,"\n").split("\n");const blocks=[];let i=0;
 const cells=(s:string)=>s.trim().replace(/^\|/,"").replace(/\|$/,"").split("|").map(x=>x.trim());
 while(i<lines.length){const line=lines[i],key=i;if(!line.trim()){i++;continue}
  if(/^\s*```/.test(line)){const code=[];i++;while(i<lines.length&&!/^\s*```/.test(lines[i]))code.push(lines[i++]);if(i<lines.length)i++;blocks.push(<pre key={key}><code>{code.join("\n")}</code></pre>);continue}
  const heading=line.match(/^\s*(#{1,6})\s+(.+)$/);if(heading){blocks.push(<h3 key={key}><Inline text={heading[2]}/></h3>);i++;continue}
  if(line.includes("|")&&i+1<lines.length&&/^\s*\|?\s*:?-{3,}/.test(lines[i+1])&&lines[i+1].includes("|")){const head=cells(line);i+=2;const body=[];while(i<lines.length&&lines[i].trim()&&lines[i].includes("|"))body.push(cells(lines[i++]));blocks.push(<div className="md-table" key={key}><table><thead><tr>{head.map((c,j)=><th key={j}><Inline text={c}/></th>)}</tr></thead><tbody>{body.map((r,j)=><tr key={j}>{head.map((_,k)=><td key={k}><Inline text={r[k]||""}/></td>)}</tr>)}</tbody></table></div>);continue}
  const item=line.match(/^\s*([-+*]|\d+\.)\s+(.+)$/);if(item){const ordered=/\d/.test(item[1]),items=[];while(i<lines.length){const m=lines[i].match(/^\s*([-+*]|\d+\.)\s+(.+)$/);if(!m||/\d/.test(m[1])!==ordered)break;items.push(m[2]);i++}const children=items.map((x,j)=><li key={j}><Inline text={x}/></li>);blocks.push(ordered?<ol key={key}>{children}</ol>:<ul key={key}>{children}</ul>);continue}
  blocks.push(<p key={key}><Inline text={line}/></p>);i++;
 }
 return <div className="evidence-markdown">{blocks}</div>
}

export function AnswerActions({answer,sources=[]}:{answer:string;sources?:unknown[]}){
 const[status,setStatus]=useState("");
 async function copy(){try{await navigator.clipboard.writeText(answer);setStatus("Copied")}catch{setStatus("Copy unavailable; select the response text instead.")}}
 return <div className="answer-actions"><button type="button" onClick={()=>void copy()}>Copy response</button><span role="status">{status}</span>{sources.length>0&&<details><summary>Sources ({sources.length})</summary><ol>{sources.map((s,i)=><li key={i}>{typeof s==="string"?s:JSON.stringify(s)}</li>)}</ol></details>}</div>
}

export function ResearchResults({results}:{results:unknown[]}){
 return <div className="research-results">{results.map((item,i)=>{const r=item as {title?:string;url?:string;content?:string};const url=typeof r?.url==="string"?safeLink(r.url):null;return <article key={i}><h3>{url?<a href={url} target="_blank" rel="noopener noreferrer">{r.title||url}</a>:r?.title||"Research result"}</h3><p>{typeof r?.content==="string"?r.content:"No excerpt returned."}</p></article>})}</div>
}
