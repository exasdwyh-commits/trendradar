import { useState } from 'react'
import {
  Binoculars, CheckCircle2, PenLine, RadioTower, TrendingUp,
  NotebookTabs, Database, Settings, Search
} from 'lucide-react'
import { Decisions, Today } from './views/Home'
import { Research } from './views/Research'
import { Publish, Studio } from './views/Content'
import { Ledger, Trends } from './views/Knowledge'
import { BlindEval, Sources, System } from './views/QualityLab'

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

export default App
