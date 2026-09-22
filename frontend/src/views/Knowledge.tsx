import { useEffect, useState } from 'react'
import { api } from '../api'
import type { Trend, WorldModel } from '../types'
import { Empty, Header, Pill } from '../components/Common'

export function Trends(){
  const [data,setData]=useState<{items:Trend[];world_model?:WorldModel}|null>(null)
  useEffect(()=>{api.get<typeof data>('/api/trends').then(setData)},[])
  if(!data)return <Empty>正在读取趋势库…</Empty>
  return <>
    <Header title="趋势库" sub="不是标签库。先看最近哪些判断被强化、削弱或出现分歧。"/>
    {data.world_model?.summary&&<div className="world-card"><span>最近世界模型变化</span><p>{data.world_model.summary}</p><div className="world-counts"><Pill tone="green">强化 {(data.world_model.strengthened||[]).length}</Pill><Pill tone="amber">分歧 {(data.world_model.diverging||[]).length}</Pill><Pill>减弱 {(data.world_model.weakened||[]).length}</Pill><Pill tone="blue">新出现 {(data.world_model.new||[]).length}</Pill></div></div>}
    <div className="trend-list">{data.items.map(t=><article className="trend-row" key={t.id}><div className="micro-row"><Pill>{t.status}</Pill><Pill>{t.stage}</Pill><Pill tone={t.momentum==='STRENGTHENING'?'green':t.momentum==='DIVERGING'?'amber':'neutral'}>{t.momentum}</Pill></div><h2>{t.name}</h2><p>{t.judgement}</p><div className="trend-meta"><span>支持 {t.support_count}</span><span>反证 {t.counter_count}</span><span>待定 {t.uncertain_count}</span></div></article>)}</div>
  </>
}

export function Ledger(){
  const [items,setItems]=useState<any[]>([])
  const [tab,setTab]=useState<'pending'|'upcoming'|'reviewed'>('pending')
  const load=()=>api.get<{items:any[]}>('/api/ledger').then(x=>setItems(x.items))
  useEffect(()=>{void load()},[])
  const review=async(id:string,result:string)=>{await api.post('/api/ledger/'+id+'/review',{result});await load()}
  const filtered=items.filter(x=>{
    if(tab==='reviewed')return x.review_status==='REVIEWED'
    if(tab==='upcoming')return x.review_status==='UPCOMING'
    return x.review_status==='PENDING'||x.review_status==='DUE'
  })
  return <>
    <Header title="判断账本" sub="爆款不等于判断正确。这里记录你当时为什么这么想，以及未来如何验证。"/>
    <div className="ledger-tabs">
      <button className={tab==='pending'?'active':''} onClick={()=>setTab('pending')}>待验证</button>
      <button className={tab==='upcoming'?'active':''} onClick={()=>setTab('upcoming')}>即将到期</button>
      <button className={tab==='reviewed'?'active':''} onClick={()=>setTab('reviewed')}>已复盘</button>
    </div>
    {!filtered.length?<Empty>这个分组暂时没有判断。</Empty>:<div className="ledger">{filtered.map(x=><article key={x.id} className="ledger-row"><div className="ledger-time"><span>{x.created_at?.slice(0,10)}</span>{x.review_at&&<small>复盘 {x.review_at.slice(0,10)}</small>}</div><div><div className="micro-row"><Pill tone={x.review_status==='REVIEWED'?'green':x.review_status==='DUE'?'red':x.review_status==='UPCOMING'?'amber':'neutral'}>{x.review_status==='REVIEWED'?'已复盘':x.review_status==='DUE'?'已到期':x.review_status==='UPCOMING'?'即将到期':'待验证'}</Pill><Pill>{x.horizon}</Pill>{x.result&&<Pill tone="blue">{x.result}</Pill>}</div><h3>{x.judgement}</h3><p>若判断错误：{x.falsification_signal||'待补充验证条件'}</p>{x.review_status!=='REVIEWED'&&<div className="ledger-review"><span>现在复盘：</span><button onClick={()=>void review(x.id,'CORRECT')}>正确</button><button onClick={()=>void review(x.id,'DIRECTIONALLY_RIGHT')}>大方向正确</button><button onClick={()=>void review(x.id,'PARTIAL')}>部分成立</button><button onClick={()=>void review(x.id,'WRONG')}>错误</button></div>}</div></article>)}</div>}
  </>
}
