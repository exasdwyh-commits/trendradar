import { useEffect, useState } from 'react'
import { ChevronRight, RefreshCw } from 'lucide-react'
import { api } from '../api'
import type { Candidate, ResearchPack } from '../types'
import { Header, Pill } from '../components/Common'

export function Research({selected,onSelect,onDecision}:{selected:string|null;onSelect:(id:string|null)=>void;onDecision:()=>void}){
  const [items,setItems]=useState<Candidate[]>([])
  const [detail,setDetail]=useState<any>(null)
  const [busy,setBusy]=useState(false)
  useEffect(()=>{api.get<{items:Candidate[]}>('/api/candidates?limit=40').then(x=>setItems(x.items.filter(i=>i.action!=='SKIP')))},[])
  useEffect(()=>{if(selected)api.get('/api/candidates/'+selected).then(setDetail);else setDetail(null)},[selected])
  if(selected&&detail){
    const x:Candidate=detail.candidate
    const research:ResearchPack|null=detail.research||null
    const evidenceById=new Map((detail.evidence||[]).map((e:any)=>[e.id,e]))
    const grounding=research?.grounding
    const thesisReady=!!research && (grounding?.grounded_units||0)>=2 && (grounding?.evidence_count||0)>=2 && (grounding?.independent_source_count||0)>=2 && (grounding?.quality_source_count||0)>=1
    const doResearch=async()=>{setBusy(true);try{await api.post('/api/candidates/'+selected+'/research');setDetail(await api.get('/api/candidates/'+selected))}finally{setBusy(false)}}
    const thesis=async()=>{if(!thesisReady)return;setBusy(true);try{await api.post('/api/candidates/'+selected+'/thesis');onDecision()}finally{setBusy(false)}}
    const ResearchColumn=({title,items,tone}:{title:string;items:any[];tone:'green'|'blue'|'amber'})=><div className="research-pack-column"><div className="research-pack-title"><Pill tone={tone}>{title}</Pill><span>{items.length}</span></div>{!items.length?<p className="research-empty">暂无</p>:items.map((item:any,i:number)=><div className="research-unit" key={i}><p>{item.text}</p>{item.note&&<small>{item.note}</small>}<div className="research-citations">{(item.evidence_ids||[]).map((id:string)=>{const e:any=evidenceById.get(id);return e?<a key={id} href={e.url} target="_blank" rel="noreferrer">{e.source_id}</a>:<span key={id}>{id.slice(0,6)}</span>})}</div></div>)}</div>
    return <>
      <Header title="研究详情" sub="先看商业机制，再回到底层证据。所有结论都必须能追溯。"
        action={<button className="ghost-button" onClick={()=>onSelect(null)}>返回研究室</button>}/>
      <article className="research-summary">
        <div className="research-top"><Pill tone={x.action==='WRITE'?'blue':'neutral'}>{x.action}</Pill><h2>{x.title}</h2></div>
        <div className="research-kv">
          <div><span>发生了什么</span><p>{x.event_summary}</p></div>
          <div><span>真正改变</span><p>{x.what_changed||'待分析'}</p></div>
          <div><span>为什么现在</span><p>{x.why_now||'待分析'}</p></div>
          <div><span>利润池</span><p>{x.profit_pool||'待判断'}</p></div>
          <div><span>谁受益 / 谁受损</span><p>{x.who_benefits||'—'} / {x.who_loses||'—'}</p></div>
          <div><span>中国映射</span><p>{x.china_mapping||'待验证'}</p></div>
          <div className="counter"><span>最强反方</span><p>{x.strongest_counter||'待补充'}</p></div>
        </div>
        <div className="actions"><button disabled={busy} className="primary-button" onClick={()=>void doResearch()}>{busy?<RefreshCw className="spin" size={15}/>:(research?'重新生成研究包':'生成研究包')}</button><button disabled={busy||!thesisReady} className="ghost-button" onClick={()=>void thesis()}>{thesisReady?'提出核心观点':'研究证据不足，暂不能提出观点'}</button></div>
      </article>
      {research&&<section className="section"><div className="section-title"><h2>研究包</h2><span>{grounding?.evidence_count||0} 个证据 · {grounding?.independent_source_count||0} 个独立来源 · {grounding?.grounded_units||0} 个可追溯判断</span></div>
        <div className="research-pack-grid">
          <ResearchColumn title="FACT" items={research.facts||[]} tone="green"/>
          <ResearchColumn title="CLAIM" items={research.claims||[]} tone="blue"/>
          <ResearchColumn title="INFER" items={research.inferences||[]} tone="amber"/>
        </div>
        <div className="research-risk-grid">
          <div><span>最强反方</span><p>{research.strongest_counter||'暂无'}</p></div>
          <div><span>证据缺口</span><p>{research.evidence_gap||'暂无'}</p></div>
        </div>
      </section>}
      <section className="section"><div className="section-title"><h2>证据链</h2><span>PRIMARY / VERIFIER / DISCOVERY 分层</span></div>
        <div className="evidence-grid">{(detail.evidence||[]).map((e:any)=><a key={e.id} href={e.url} target="_blank" rel="noreferrer" className="evidence-card"><div><Pill tone={e.source_role==='PRIMARY'?'green':e.source_role==='VERIFIER'?'blue':'neutral'}>{e.source_role}</Pill><Pill>{e.kind}</Pill></div><h3>{e.title}</h3><p>{e.summary}</p><small>{e.source_id}</small></a>)}</div>
      </section>
    </>
  }
  return <>
    <Header title="研究室" sub="不是所有值得看的东西都值得写。先弄清事实、机制和反方。"/>
    <div className="research-list">{items.map(x=><button key={x.id} className="research-row" onClick={()=>onSelect(x.id)}><div><div className="micro-row"><Pill>{x.action}</Pill><Pill>{x.cognition_status}</Pill></div><h3>{x.title}</h3><p>{x.what_changed||x.event_summary}</p></div><ChevronRight/></button>)}</div>
  </>
}
