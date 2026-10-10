import { useEffect, useState } from 'react'
import { ArrowRight, ChevronRight } from 'lucide-react'
import { api } from '../api'
import type { Candidate, SignalBoard, SignalState, Thesis, WorldModel } from '../types'
import { Empty, Header, Pill } from '../components/Common'

type DashboardData={
  today:Candidate[]
  signals?:SignalBoard
  pending_decisions:Thesis[]
  world_model?:WorldModel
}

export function Today({onResearch}:{onResearch:(id:string)=>void}){
  const [data,setData]=useState<DashboardData|null>(null)
  useEffect(()=>{api.get<DashboardData>('/api/dashboard').then(setData).catch(()=>setData({today:[],pending_decisions:[]}))},[])
  if(!data)return <Empty>正在整理今天的商业变化…</Empty>
  const items=data.today||[]
  const signals=data.signals
  const openResearch=(id:string)=>{
    void api.post('/api/candidates/'+id+'/feedback',{action:'OPENED',note:'today-board'}).catch(()=>undefined)
    onResearch(id)
  }
  return <>
    <Header title="今天最值得理解的商业变化" sub="不是重复新闻列表：先看今天新出现什么、什么正在升温，再决定哪 1–3 件值得进入研究。"/>
    {signals?.run_id&&<section className="section">
      <div className="section-title"><h2>今日信号态势</h2><span>{signals.ranking_mode||'RULE'} · {signals.run_at||''}</span></div>
      <div className="list">
        <div className="list-row"><div><Pill tone="green">首次出现 {signals.summary.NEW||0}</Pill><p>今天第一次进入候选池，需要快速判断是否值得继续跟踪。</p></div></div>
        <div className="list-row"><div><Pill tone="amber">持续升温 {signals.summary.RISING||0}</Pill><p>评分、排名或独立来源数相比上一轮明显增强。</p></div></div>
        <div className="list-row"><div><Pill>持续跟踪 {signals.summary.TRACKING||0}</Pill><p>仍在候选池中，但暂未出现足够强的新动量。</p></div></div>
      </div>
    </section>}
    {!items.length?<Empty>还没有结果。运行一次 daily 后，这里只留下优中选优的商业信号。</Empty>:
      <div className="today-grid">
        <FocusCard item={items[0]} index={0} onResearch={openResearch}/>
        <div className="today-stack">{items.slice(1).map((x,i)=><FocusCard key={x.id} item={x} index={i+1} onResearch={openResearch}/>)}</div>
      </div>}
    {!!signals?.items?.length&&<section className="section">
      <div className="section-title"><h2>信号看板</h2><span>按当前内容排名展示，状态来自跨日候选历史</span></div>
      <div className="list">{signals.items.slice(0,8).map(item=><button className="list-row" key={item.id} onClick={()=>openResearch(item.id)}>
        <div><SignalPill signal={item.signal}/><h3>{item.title}</h3><p>{signalDelta(item.signal)}</p></div><ChevronRight/>
      </button>)}</div>
    </section>}
    <section className="section">
      <div className="section-title"><h2>今天还需要我决定</h2><span>只放不可替代的人类判断</span></div>
      {!data.pending_decisions?.length?<Empty>没有。系统只在需要你拍板时打扰你。</Empty>:
        <div className="list">{data.pending_decisions.slice(0,3).map(t=><div className="list-row" key={t.id}><div><Pill tone="amber">观点待确认</Pill><h3>{t.thesis}</h3><p>{t.candidate_title}</p></div><ChevronRight/></div>)}</div>}
    </section>
    {data.world_model?.summary&&<section className="world-strip"><span>今日世界模型更新</span><p>{data.world_model.summary}</p></section>}
  </>
}

function SignalPill({signal}:{signal?:SignalState}){
  if(signal?.status==='NEW')return <Pill tone="green">首次出现</Pill>
  if(signal?.status==='RISING')return <Pill tone="amber">持续升温</Pill>
  return <Pill>持续跟踪</Pill>
}

function signalDelta(signal?:SignalState){
  if(!signal)return '尚未形成跨日历史。'
  const bits:string[]=[]
  if(signal.rank_delta)bits.push(`排名 ${signal.rank_delta>0?'↑':'↓'}${Math.abs(signal.rank_delta)}`)
  if(signal.score_delta)bits.push(`内容分 ${signal.score_delta>0?'+':''}${signal.score_delta}`)
  if(signal.source_delta)bits.push(`独立来源 ${signal.source_delta>0?'+':''}${signal.source_delta}`)
  if(!bits.length)bits.push(`已连续进入候选池 ${signal.history_count} 轮`)
  return bits.join(' · ')
}

function FocusCard({item,index,onResearch}:{item:Candidate;index:number;onResearch:(id:string)=>void}){
  const corroborated=(item.source_count||0)>=2 && (item.quality_source_count||0)>=1
  return <article className={`focus-card rank-${index}`}>
    <div className="focus-topline"><div className="card-kicker">{index===0?'今日首选':index===1?'值得关注':'继续观察'}</div><div className="actions"><SignalPill signal={item.signal}/><Pill tone={corroborated?'green':'amber'}>{corroborated?`已交叉验证 ${item.source_count} 源`:'待第二来源'}</Pill></div></div>
    <h2>{item.title}</h2>
    <p className="event">{item.event_summary}</p>
    <dl><div><dt>真正改变</dt><dd>{item.what_changed||'等待认知层分析'}</dd></div><div><dt>商业含义</dt><dd>{item.profit_pool||'等待利润池判断'}</dd></div></dl>
    <p className="source-line">{signalDelta(item.signal)}</p>
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
