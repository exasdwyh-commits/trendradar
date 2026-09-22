import { useEffect, useState } from 'react'
import { api } from '../api'
import type { Health } from '../types'
import { Empty, Header, Pill } from '../components/Common'

export function BlindEval(){
  const [data,setData]=useState<any>(null)
  const [picks,setPicks]=useState<string[]>([])
  const [busy,setBusy]=useState(false)
  const load=async()=>setData(await api.get('/api/blind/latest'))
  useEffect(()=>{void load()},[])
  if(!data)return <Empty>正在读取盲评…</Empty>
  const round=data.round
  if(!round)return <>
    <Header eyebrow="QUALITY LAB" title="盲评 10→3" sub="今天还没有可评估的候选轮次。daily 跑完并冻结候选池后，这里会自动出现。"/>
    <Empty>没有可评估轮次。</Empty>
  </>
  const toggle=(id:string)=>{
    if(round.submitted)return
    setPicks(current=>current.includes(id)?current.filter(x=>x!==id):current.length<3?[...current,id]:current)
  }
  const submit=async()=>{
    if(picks.length!==3)return
    setBusy(true)
    try{
      setData(await api.post('/api/blind/'+round.id+'/submit',{picks}))
    }finally{setBusy(false)}
  }
  const byId=new Map((round.items||[]).map((x:any)=>[x.candidate_id,x]))
  const systemTitles=(round.system_top3||[]).map((id:string)=>(byId.get(id) as any)?.title||id)
  return <>
    <Header eyebrow="QUALITY LAB" title="盲评 10→3" sub="先不看模型分数、分类和推荐理由，只凭题目与事实信号选出你认为最值得研究的 3 条。"/>
    <div className="blind-status">
      <Pill tone={round.submitted?'green':'amber'}>{round.submitted?'已提交':'请选择 3 条'}</Pill>
      <Pill tone={round.ranking_mode==='COGNITION'?'green':round.ranking_mode==='FAST'?'blue':'neutral'}>{round.ranking_mode||'RULE'} 排名</Pill>
      <span>{round.round_date}</span>
      {data.summary?.hit_rate!=null&&<span>近 {data.summary.rounds} 轮命中率 {(data.summary.hit_rate*100).toFixed(0)}%</span>}
    </div>
    <div className="blind-grid">{(round.items||[]).map((item:any,index:number)=>{
      const selected=picks.includes(item.candidate_id)
      const humanPicked=(round.human_picks||[]).includes(item.candidate_id)
      const systemPicked=(round.system_top3||[]).includes(item.candidate_id)
      return <button key={item.candidate_id} className={'blind-card '+(selected||humanPicked?'selected':'')} onClick={()=>toggle(item.candidate_id)}>
        <div className="blind-letter">{String.fromCharCode(65+index)}</div>
        <div><h3>{item.title}</h3><p>{item.event_summary||'暂无事件摘要'}</p>
        {round.submitted&&<div className="micro-row">{humanPicked&&<Pill tone="blue">我的选择</Pill>}{systemPicked&&<Pill tone="green">系统 TOP3</Pill>}</div>}</div>
      </button>
    })}</div>
    {!round.submitted?<div className="blind-submit"><span>已选 {picks.length}/3</span><button className="primary-button" disabled={picks.length!==3||busy} onClick={()=>void submit()}>{busy?'提交中…':'提交后揭晓系统 TOP3'}</button></div>:
      <>
        <div className="world-card"><span>本轮结果</span><p>命中 {round.hits}/3。系统 TOP3：{systemTitles.join('；')}</p><small>盲评只检验选题选择是否接近你的判断，不代表观点本身正确。</small></div>
        <CalibrationPanel data={data.calibration} mode={round.ranking_mode||'RULE'}/>
      </>}
  </>
}

function CalibrationPanel({data,mode}:{data:any;mode:string}){
  if(!data)return null
  const current=data.by_mode?.[mode]
  const rounds=current?.rounds||0
  if(rounds<3)return <div className="calibration-card"><span>{mode} 校准数据积累中</span><p>当前 {rounds} 轮。不同 ranking mode 分开统计；至少积累 3 轮后再看稳定差异，避免拿 RULE 结果误判 COGNITION。</p></div>
  const lanes=(current?.lanes||[]).slice(0,5)
  const disagreements=(current?.disagreements||[]).slice(0,6)
  return <section className="section">
    <div className="section-title"><h2>{mode} 校准视图</h2><span>只诊断，不自动改权重</span></div>
    <div className="calibration-grid">{lanes.map((x:any)=><div className="calibration-lane" key={x.key}><strong>{x.key}</strong><div><span>我选 {x.human}</span><span>系统选 {x.system}</span><span>重合 {x.overlap}</span></div></div>)}</div>
    {!!disagreements.length&&<div className="calibration-disagreements">{disagreements.map((x:any)=><div key={x.round_date+x.candidate_id+x.type}><Pill tone={x.type==='HUMAN_ONLY'?'blue':'amber'}>{x.type==='HUMAN_ONLY'?'我选·系统漏掉':'系统选·我没选'}</Pill><strong>{x.title}</strong><small>{x.round_date} · {x.lane} · {(x.source_ids||[]).join(' / ')}</small></div>)}</div>}
  </section>
}

export function Sources(){
  const [items,setItems]=useState<any[]>([])
  useEffect(()=>{Promise.all([
    api.get<{items:any[]}>('/api/sources'),
    api.get<{items:any[]}>('/api/source-yield')
  ]).then(([sources,yields])=>{
    const byId=new Map(yields.items.map(x=>[x.id,x]))
    setItems(sources.items.map(x=>({...x,...(byId.get(x.id)||{})})))
  })},[])
  return <>
    <Header eyebrow="PRO TOOLS" title="来源状态" sub="第一方事实源优先，并持续观察每个来源真正产出候选与 TOP3 的效率。"/>
    <div className="source-table">{items.map(s=><div className="source-row" key={s.id}><div><div className="micro-row"><Pill tone={s.role==='PRIMARY'?'green':s.role==='VERIFIER'?'blue':'neutral'}>{s.role}</Pill><Pill>T{s.tier}</Pill><Pill>{s.lane}</Pill></div><strong>{s.name}</strong><small>{s.url}</small><div className="source-yield"><span>采集 {s.intelligence_count||0}</span><span>候选 {s.candidate_count||0}</span><span>WRITE {s.write_count||0}</span><span>TOP3 {s.top3_count||0}</span></div></div><div className={s.consecutive_failures?'health bad':'health good'}>{s.last_success_at?'最近成功 '+s.last_success_at.slice(0,16):'尚未运行'}{s.last_error&&<span>{s.last_error}</span>}</div></div>)}</div>
  </>
}

export function System(){
  const [health,setHealth]=useState<Health|null>(null)
  const [ai,setAi]=useState<any>(null)
  useEffect(()=>{Promise.all([api.get<Health>('/api/health'),api.get('/api/ai-runs?limit=60')]).then(([h,a])=>{setHealth(h);setAi(a)})},[])
  if(!health)return <Empty>正在读取系统状态…</Empty>
  return <>
    <Header eyebrow="PRO TOOLS" title="系统状态" sub={`Schema v${health.schema_version??'—'} · 某个模型没配置时明确显示离线；重试、429、Token 与延迟也必须可观察。`}/>
    <div className="model-grid">{Object.entries(health.models||{}).map(([name,m])=><div className="model-card" key={name}><div className={m.enabled?'model-dot on':'model-dot'}/><div><strong>{name}</strong><p>{m.enabled?m.model:'未配置'}</p></div></div>)}</div>
    <section className="section"><div className="section-title"><h2>AI 调用质量</h2><span>按模型槽位与任务聚合</span></div>
      {!ai?.aggregate?.length?<Empty>还没有 AI 调用记录。</Empty>:<div className="source-table">{ai.aggregate.map((x:any)=><div className="source-row" key={x.slot+x.task}><div><div className="micro-row"><Pill>{x.slot}</Pill><Pill>{x.task}</Pill></div><strong>{x.ok_calls}/{x.calls} 成功</strong><small>输入 {x.input_tokens} · 输出 {x.output_tokens} · 重试 {x.retries}{x.cost_cny? ` · ¥${Number(x.cost_cny).toFixed(4)}` : ''}</small></div><div className="health good">平均 {x.avg_duration_ms} ms</div></div>)}</div>}
    </section>
    <section className="section"><div className="section-title"><h2>最近任务</h2></div><div className="system-run">{health.last_run?<><Pill tone={health.last_run.status==='SUCCESS'?'green':'amber'}>{health.last_run.status}</Pill><span>{health.last_run.started_at}</span></>:<span>尚未运行</span>}</div></section>
  </>
}
