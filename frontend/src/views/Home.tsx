import { useEffect, useState } from 'react'
import { ArrowRight, ChevronRight } from 'lucide-react'
import { api } from '../api'
import type { Candidate, Thesis, WorldModel } from '../types'
import { Empty, Header, Pill } from '../components/Common'

export function Today({onResearch}:{onResearch:(id:string)=>void}){
  const [data,setData]=useState<{today:Candidate[];pending_decisions:Thesis[];world_model?:WorldModel}|null>(null)
  useEffect(()=>{api.get<typeof data>('/api/dashboard').then(setData).catch(()=>setData({today:[],pending_decisions:[]}))},[])
  if(!data)return <Empty>正在整理今天的商业变化…</Empty>
  const items=data.today||[]
  return <>
    <Header title="今天最值得理解的商业变化" sub="后台可以抓很多，但你的第一屏永远只保留 3 件真正值得看的事。"/>
    {!items.length?<Empty>还没有结果。运行一次 daily 后，这里只留下优中选优的商业信号。</Empty>:
      <div className="today-grid">
        <FocusCard item={items[0]} index={0} onResearch={onResearch}/>
        <div className="today-stack">{items.slice(1).map((x,i)=><FocusCard key={x.id} item={x} index={i+1} onResearch={onResearch}/>)}</div>
      </div>}
    <section className="section">
      <div className="section-title"><h2>今天还需要我决定</h2><span>只放不可替代的人类判断</span></div>
      {!data.pending_decisions?.length?<Empty>没有。系统只在需要你拍板时打扰你。</Empty>:
        <div className="list">{data.pending_decisions.slice(0,3).map(t=><div className="list-row" key={t.id}><div><Pill tone="amber">观点待确认</Pill><h3>{t.thesis}</h3><p>{t.candidate_title}</p></div><ChevronRight/></div>)}</div>}
    </section>
    {data.world_model?.summary&&<section className="world-strip"><span>今日世界模型更新</span><p>{data.world_model.summary}</p></section>}
  </>
}

function FocusCard({item,index,onResearch}:{item:Candidate;index:number;onResearch:(id:string)=>void}){
  const corroborated=(item.source_count||0)>=2 && (item.quality_source_count||0)>=1
  return <article className={`focus-card rank-${index}`}>
    <div className="focus-topline"><div className="card-kicker">{index===0?'今日首选':index===1?'值得关注':'继续观察'}</div><Pill tone={corroborated?'green':'amber'}>{corroborated?`已交叉验证 ${item.source_count} 源`:'待第二来源'}</Pill></div>
    <h2>{item.title}</h2>
    <p className="event">{item.event_summary}</p>
    <dl><div><dt>真正改变</dt><dd>{item.what_changed||'等待认知层分析'}</dd></div><div><dt>商业含义</dt><dd>{item.profit_pool||'等待利润池判断'}</dd></div></dl>
    <button className="primary-button" onClick={()=>onResearch(item.id)}>进入研究 <ArrowRight size={15}/></button>
  </article>
}

export function Decisions({onDraft}:{onDraft:(doc:string)=>void}){
  const [items,setItems]=useState<Thesis[]|null>(null)
  const load=()=>api.get<{items:Thesis[]}>('/api/theses?status=PENDING').then(x=>setItems(x.items))
  useEffect(()=>{void load()},[])
  const confirm=async(id:string)=>{await api.post('/api/theses/'+id+'/confirm',{horizon:'12个月'});const d=await api.post<{document_id:string}>('/api/theses/'+id+'/draft');onDraft(d.document_id)}
  const hold=async(id:string)=>{await api.post('/api/theses/'+id+'/hold');await load()}
  if(items===null)return <Empty>正在读取待确认观点…</Empty>
  return <>
    <Header title="待我决定" sub="模型负责研究，人只决定：这个判断我是否愿意承担。"/>
    {!items.length?<Empty>现在没有需要你确认的观点。</Empty>:<div className="decision-list">{items.map(x=>
      <article className="decision-card" key={x.id}>
        <Pill tone="amber">核心观点待确认</Pill><h2>{x.thesis}</h2><p className="source-line">{x.candidate_title}</p>
        <div className="decision-grid">
          <div><span>支持证据</span><ul>{(x.support_json||[]).map((s,i)=><li key={i}>{s}</li>)}</ul></div>
          <div><span>最强反方</span><ul>{(x.counter_json||[]).map((s,i)=><li key={i}>{s}</li>)}</ul></div>
        </div>
        <div className="falsify"><span>什么出现时，我应该承认这个判断错了？</span><p>{x.falsification_signal||'还缺少明确验证信号。'}</p></div>
        <div className="actions"><button className="primary-button" onClick={()=>void confirm(x.id)}>认同，进入创作</button><button className="ghost-button" onClick={()=>void hold(x.id)}>暂不下结论</button></div>
      </article>)}</div>}
  </>
}
