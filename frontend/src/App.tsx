import { useEffect, useMemo, useState } from 'react'
import {
  Binoculars, CheckCircle2, FileText, PenLine, RadioTower, TrendingUp,
  NotebookTabs, Database, Settings, Plus, ArrowRight, RefreshCw, ExternalLink,
  Download, Check, Search, ChevronRight
} from 'lucide-react'
import { api } from './api'
import Editor from './components/Editor'
import type {
  Candidate, DocumentDetail, DocumentSummary, Health, PlatformVariant,
  ResearchPack, Thesis, Trend, WorldModel
} from './types'

type View='today'|'decisions'|'research'|'studio'|'publish'|'trends'|'ledger'|'blind'|'sources'|'system'

const nav:{view:View;label:string;icon:typeof Binoculars}[]=[
  {view:'today',label:'今日重点',icon:Binoculars},
  {view:'decisions',label:'待我决定',icon:CheckCircle2},
  {view:'research',label:'研究室',icon:Search},
  {view:'studio',label:'创作中心',icon:PenLine},
  {view:'publish',label:'发布中心',icon:RadioTower},
  {view:'trends',label:'趋势库',icon:TrendingUp},
  {view:'ledger',label:'判断账本',icon:NotebookTabs},
]
const tools:{view:View;label:string;icon:typeof Database}[]=[
  {view:'blind',label:'盲评 10→3',icon:CheckCircle2},
  {view:'sources',label:'来源状态',icon:Database},
  {view:'system',label:'系统状态',icon:Settings},
]
const platformName:Record<string,string>={WECHAT:'公众号',XIAOHONGSHU:'小红书',ZHIHU:'知乎',TOUTIAO:'头条',X:'X'}

function Header({eyebrow='BUSINESS COGNITION',title,sub,action}:{eyebrow?:string;title:string;sub:string;action?:React.ReactNode}){
  return <div className="page-head"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{sub}</p></div>{action}</div>
}
function Empty({children}:{children:React.ReactNode}){return <div className="empty-state">{children}</div>}
function Pill({children,tone='neutral'}:{children:React.ReactNode;tone?:string}){return <span className={`pill tone-${tone}`}>{children}</span>}

function App(){
  const [view,setView]=useState<View>('today')
  const [selectedCandidate,setSelectedCandidate]=useState<string|null>(null)
  const [selectedDocument,setSelectedDocument]=useState<string|null>(null)
  const [refreshKey,setRefreshKey]=useState(0)

  const navigate=(next:View)=>{setView(next);setSelectedCandidate(null);if(next!=='studio')setSelectedDocument(null)}
  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="coin">硬</div><div><strong>硬币先生</strong><span>商业内容操作系统</span></div></div>
      <nav className="main-nav">{nav.map(item=>{
        const Icon=item.icon
        return <button key={item.view} className={view===item.view?'active':''} onClick={()=>navigate(item.view)}><Icon size={17}/><span>{item.label}</span></button>
      })}</nav>
      <div className="nav-label">专业工具</div>
      <nav className="main-nav muted-nav">{tools.map(item=>{
        const Icon=item.icon
        return <button key={item.view} className={view===item.view?'active':''} onClick={()=>navigate(item.view)}><Icon size={16}/><span>{item.label}</span></button>
      })}</nav>
      <div className="sidebar-foot">发现 → 理解 → 判断<br/>→ 创作 → 发布 → 复盘</div>
    </aside>
    <main className={selectedDocument&&view==='studio'?'main editor-main':'main'}>
      {view==='today'&&<Today onResearch={id=>{setSelectedCandidate(id);setView('research')}}/>}
      {view==='decisions'&&<Decisions onDraft={doc=>{setSelectedDocument(doc);setView('studio')}}/>}
      {view==='research'&&<Research selected={selectedCandidate} onSelect={setSelectedCandidate} onDecision={()=>setView('decisions')}/>}
      {view==='studio'&&<Studio selected={selectedDocument} onSelect={setSelectedDocument} refreshKey={refreshKey} bump={()=>setRefreshKey(x=>x+1)}/>}
      {view==='publish'&&<Publish/>}
      {view==='trends'&&<Trends/>}
      {view==='ledger'&&<Ledger/>}
      {view==='blind'&&<BlindEval/>}
      {view==='sources'&&<Sources/>}
      {view==='system'&&<System/>}
    </main>
  </div>
}

function Today({onResearch}:{onResearch:(id:string)=>void}){
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

function Decisions({onDraft}:{onDraft:(doc:string)=>void}){
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

function Research({selected,onSelect,onDecision}:{selected:string|null;onSelect:(id:string|null)=>void;onDecision:()=>void}){
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

function Studio({selected,onSelect,refreshKey,bump}:{selected:string|null;onSelect:(id:string)=>void;refreshKey:number;bump:()=>void}){
  const [documents,setDocuments]=useState<DocumentSummary[]>([])
  const [detail,setDetail]=useState<DocumentDetail|null>(null)
  const [saving,setSaving]=useState(false)
  const load=async()=>{const d=await api.get<{items:DocumentSummary[]}>('/api/documents');setDocuments(d.items)}
  useEffect(()=>{void load()},[refreshKey])
  useEffect(()=>{if(selected)api.get<DocumentDetail>('/api/documents/'+selected).then(setDetail);else setDetail(null)},[selected,refreshKey])
  const create=async()=>{const d=await api.post<{document_id:string}>('/api/documents',{title:'未命名文章'});await load();onSelect(d.document_id)}
  if(selected&&detail){
    const reload=async()=>setDetail(await api.get<DocumentDetail>('/api/documents/'+selected))
    const save=async(title:string,json:Record<string,unknown>,html:string,text:string,note?:string)=>{
      setSaving(true);try{await api.put('/api/documents/'+selected,{title,content_json:json,content_html:html,plain_text:text,source:'MANUAL',note});await reload();bump()}finally{setSaving(false)}
    }
    const restore=async(v:number)=>{await api.post('/api/documents/'+selected+'/restore/'+v);await reload();bump()}
    const imagePlan=async()=>{await api.post('/api/documents/'+selected+'/image-plan');await reload()}
    const variant=async(platform:string)=>{await api.post('/api/documents/'+selected+'/variant',{platform});await reload()}
    const aiEdit=async(payload:{selected_text:string;instruction:string;before_context:string;after_context:string})=>{
      return api.post<{replacement:string;warning?:string;used_evidence_ids?:string[]}>('/api/documents/'+selected+'/edit-selection',payload)
    }
    return <Editor document={detail} saving={saving} onSave={save} onRestore={restore} onImagePlan={imagePlan} onVariant={variant} onAiEdit={aiEdit}/>
  }
  return <>
    <Header eyebrow="CONTENT STUDIO" title="创作中心" sub="从系统选题开始，也可以完全从自己的想法开始。母稿是资产，不是一次性AI输出。"
      action={<button className="primary-button" onClick={()=>void create()}><Plus size={16}/>新建文章</button>}/>
    {!documents.length?<Empty>还没有文章。可以从已确认的观点进入，也可以直接新建空白稿。</Empty>:
      <div className="document-grid">{documents.map(d=><button className="document-card" key={d.id} onClick={()=>onSelect(d.id)}><div className="doc-icon"><FileText/></div><div className="doc-body"><div className="micro-row"><Pill>{d.status}</Pill><span>v{d.current_version}</span><span>{d.variant_count} 个平台版本</span></div><h2>{d.title}</h2><p>{d.thesis||d.candidate_title||'自主创作'}</p><small>更新于 {d.updated_at.replace('T',' ').slice(0,16)}</small></div><ArrowRight/></button>)}</div>}
  </>
}

function Publish(){
  const [documents,setDocuments]=useState<DocumentSummary[]>([])
  const [variants,setVariants]=useState<PlatformVariant[]>([])
  const [busy,setBusy]=useState<string|null>(null)
  const load=async()=>{const [d,v]=await Promise.all([api.get<{items:DocumentSummary[]}>('/api/documents'),api.get<{items:PlatformVariant[]}>('/api/publish')]);setDocuments(d.items);setVariants(v.items)}
  useEffect(()=>{void load()},[])
  const generate=async(doc:string,platform:string)=>{setBusy(doc+platform);try{await api.post('/api/documents/'+doc+'/variant',{platform});await load()}finally{setBusy(null)}}
  const exportOne=async(id:string)=>{const d=await api.post<{url:string}>('/api/platform-variants/'+id+'/export');window.open(d.url,'_blank')}
  const published=async(id:string)=>{const url=window.prompt('可选：粘贴已发布页面链接')||undefined;await api.post('/api/platform-variants/'+id+'/published',{external_url:url});await load()}
  return <>
    <Header eyebrow="PUBLISHING" title="发布中心" sub="一篇母稿，多种平台表达。先做平台适配与导出；平台授权接入后再逐步升级为直发。"/>
    <section className="section">
      <div className="section-title"><h2>生成平台版本</h2><span>不简单截短，而是按平台重构表达</span></div>
      <div className="publish-docs">{documents.map(d=><div className="publish-doc" key={d.id}><div><h3>{d.title}</h3><p>{d.thesis||'自主创作母稿'}</p></div><div className="platform-actions">{['WECHAT','XIAOHONGSHU','ZHIHU','TOUTIAO'].map(p=><button disabled={busy===d.id+p} key={p} onClick={()=>void generate(d.id,p)}>{platformName[p]}</button>)}</div></div>)}</div>
    </section>
    <section className="section">
      <div className="section-title"><h2>发布队列</h2><span>当前支持平台版生成、导出与发布记录</span></div>
      {!variants.length?<Empty>还没有平台版本。</Empty>:<div className="variant-list">{variants.map(v=><article className="variant-card" key={v.id}><div className="variant-head"><Pill tone="blue">{platformName[v.platform]||v.platform}</Pill><Pill tone={v.status==='PUBLISHED'?'green':'neutral'}>{v.status}</Pill></div><h3>{v.title}</h3><p>{v.content_text?.slice(0,180)}{v.content_text?.length>180?'…':''}</p><div className="actions"><button className="ghost-button" onClick={()=>void exportOne(v.id)}><Download size={15}/>导出</button>{v.status!=='PUBLISHED'&&<button className="primary-button" onClick={()=>void published(v.id)}><Check size={15}/>标记已发布</button>}{v.external_url&&<a className="text-link" href={v.external_url} target="_blank" rel="noreferrer">打开发布页 <ExternalLink size={13}/></a>}</div></article>)}</div>}
    </section>
  </>
}

function Trends(){
  const [data,setData]=useState<{items:Trend[];world_model?:WorldModel}|null>(null)
  useEffect(()=>{api.get<typeof data>('/api/trends').then(setData)},[])
  if(!data)return <Empty>正在读取趋势库…</Empty>
  return <>
    <Header title="趋势库" sub="不是标签库。先看最近哪些判断被强化、削弱或出现分歧。"/>
    {data.world_model?.summary&&<div className="world-card"><span>最近世界模型变化</span><p>{data.world_model.summary}</p><div className="world-counts"><Pill tone="green">强化 {(data.world_model.strengthened||[]).length}</Pill><Pill tone="amber">分歧 {(data.world_model.diverging||[]).length}</Pill><Pill>减弱 {(data.world_model.weakened||[]).length}</Pill><Pill tone="blue">新出现 {(data.world_model.new||[]).length}</Pill></div></div>}
    <div className="trend-list">{data.items.map(t=><article className="trend-row" key={t.id}><div className="micro-row"><Pill>{t.status}</Pill><Pill>{t.stage}</Pill><Pill tone={t.momentum==='STRENGTHENING'?'green':t.momentum==='DIVERGING'?'amber':'neutral'}>{t.momentum}</Pill></div><h2>{t.name}</h2><p>{t.judgement}</p><div className="trend-meta"><span>支持 {t.support_count}</span><span>反证 {t.counter_count}</span><span>待定 {t.uncertain_count}</span></div></article>)}</div>
  </>
}

function Ledger(){
  const [items,setItems]=useState<any[]>([])
  useEffect(()=>{api.get<{items:any[]}>('/api/ledger').then(x=>setItems(x.items))},[])
  return <>
    <Header title="判断账本" sub="爆款不等于判断正确。这里记录你当时为什么这么想，以及未来如何验证。"/>
    {!items.length?<Empty>还没有被确认的长期判断。</Empty>:<div className="ledger">{items.map(x=><article key={x.id} className="ledger-row"><div className="ledger-time">{x.created_at?.slice(0,10)}</div><div><div className="micro-row"><Pill tone={x.reviewed_at?'green':'amber'}>{x.reviewed_at?'已复盘':'待验证'}</Pill><Pill>{x.horizon}</Pill></div><h3>{x.judgement}</h3><p>若判断错误：{x.falsification_signal||'待补充验证条件'}</p></div></article>)}</div>}
  </>
}


function BlindEval(){
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
        <CalibrationPanel data={data.calibration}/>
      </>}
  </>
}

function CalibrationPanel({data}:{data:any}){
  if(!data)return null
  if((data.rounds||0)<3)return <div className="calibration-card"><span>校准数据积累中</span><p>当前 {data.rounds||0} 轮。至少积累 3 轮后再看系统偏好与人工偏好的稳定差异，避免根据单日结果调参。</p></div>
  const lanes=(data.lanes||[]).slice(0,5)
  const disagreements=(data.disagreements||[]).slice(0,6)
  return <section className="section">
    <div className="section-title"><h2>校准视图</h2><span>只诊断，不自动改权重</span></div>
    <div className="calibration-grid">{lanes.map((x:any)=><div className="calibration-lane" key={x.key}><strong>{x.key}</strong><div><span>我选 {x.human}</span><span>系统选 {x.system}</span><span>重合 {x.overlap}</span></div></div>)}</div>
    {!!disagreements.length&&<div className="calibration-disagreements">{disagreements.map((x:any)=><div key={x.round_date+x.candidate_id+x.type}><Pill tone={x.type==='HUMAN_ONLY'?'blue':'amber'}>{x.type==='HUMAN_ONLY'?'我选·系统漏掉':'系统选·我没选'}</Pill><strong>{x.title}</strong><small>{x.round_date} · {x.lane} · {(x.source_ids||[]).join(' / ')}</small></div>)}</div>}
  </section>
}

function Sources(){
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

function System(){
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

export default App
