import { useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, DOC_STATUS_NAME, PLATFORM_NAME, type BriefItem, type DocumentSummary, type WorkbenchOverview } from '../lib/api'
import { useFetch } from '../lib/hooks'
import { useNewDocument } from '../lib/useNewDocument'
import { ago, fmtDate } from '../lib/format'
import { Empty, ErrorNotice, Loading, ModeBadge } from '../components/ui'
import { Icon } from '../components/icons'
import { errorMessage, useToast } from '../components/toast'

export default function Workbench() {
  const { data, loading, error, reload } = useFetch<WorkbenchOverview>('/api/studio/overview')
  const { create, busy } = useNewDocument()
  const navigate = useNavigate()
  const { toast } = useToast()
  const [extending, setExtending] = useState<string | null>(null)
  const pending = useRef(false)

  async function extend(item: BriefItem) {
    if (pending.current) return
    pending.current = true
    setExtending(item.id)
    try {
      const result = await api.post<{ document_id: string }>(`/api/brief/items/${item.id}/extend`, { angle: item.angles[0] })
      navigate(`/studio/${result.document_id}`)
    } catch (e) {
      toast(errorMessage(e), 'bad')
    } finally {
      pending.current = false
      setExtending(null)
    }
  }

  return (
    <div className="workbench">
      <div className="page-head">
        <div><h1>工作台</h1><div className="sub">从一个好选题开始，把母稿写扎实，再改编到各个平台。</div></div>
        <button className={`btn primary ${busy ? 'loading' : ''}`} disabled={busy} onClick={create}><Icon name="plus" size={15} />新建公众号母稿</button>
      </div>
      {!!error && <div className="stack"><ErrorNotice error={error} /><button className="btn" onClick={reload}>重新获取工作台</button></div>}
      {loading && !data && <Loading rows={5} />}
      {data && <>
        <ol className="creation-flow" aria-label="日常创作流程">
          {[
            { label: '找选题', hint: `${data.topic_count} 条候选`, to: '/brief' },
            { label: '存素材', hint: `${data.material_count} 条素材`, to: '/materials' },
            { label: '写母稿', hint: `${data.counts.idea + data.counts.draft} 篇进行中`, to: '/studio' },
            { label: '多平台发布', hint: `${data.counts.ready} 篇待发布`, to: '/publish' },
          ].map((step, i) => <li key={step.to}><Link to={step.to}><span className="flow-number">{i + 1}</span><span><b>{step.label}</b><span className="tiny muted">{step.hint}</span></span><Icon name="chevronRight" size={14} /></Link></li>)}
        </ol>
        <div className="workbench-columns">
          <div className="stack">
            <section className="card resume-card" aria-labelledby="resume-title">
              <div className="row between"><span className="small muted">接着上次的进度</span><Icon name="pen" size={20} /></div>
              {data.resume ? <>
                <h2 id="resume-title">{data.resume.title}</h2>
                <div className="row small muted"><ModeBadge mode={data.resume.data_mode} small /><span>{DOC_STATUS_NAME[data.resume.status]}</span><span>{PLATFORM_NAME[data.resume.target_platform]}</span><span>{data.resume.word_count} 字 · v{data.resume.current_version}</span><span>{ago(data.resume.updated_at)}更新</span></div>
                <p className="resume-thesis clamp-2">{data.resume.thesis || '继续完善核心判断、素材依据和正文。'}</p>
                <div className="row"><Link className="btn primary" to={`/studio/${data.resume.id}`}><Icon name="edit" size={15} />继续写作</Link><Link className="btn ghost" to="/studio">全部稿件<Icon name="chevronRight" size={14} /></Link></div>
              </> : <>
                <h2 id="resume-title">给下一个想法留一页</h2>
                <p className="resume-thesis">{data.counts.ready ? '手上的稿件已准备好发布。也可以从简报挑一个切口，开始下一篇。' : '从简报选一个切口，或新建母稿写下核心判断。素材、大纲和 AI 助手会在编辑器里接上。'}</p>
                <Link className="btn primary" to="/brief">去挑选题<Icon name="chevronRight" size={14} /></Link>
              </>}
            </section>
            <section aria-labelledby="ready-title">
              <div className="workbench-section-head"><h2 id="ready-title">待发布 <span className="small muted">{data.counts.ready}</span></h2><Link to="/publish" className="small muted">进入发布中心<Icon name="chevronRight" size={13} /></Link></div>
              {data.ready_documents.length ? <div className="card work-list">{data.ready_documents.map((doc) => <WorkRow key={doc.id} doc={doc} />)}</div> : <div className="workbench-empty small muted">写完后在编辑器标记「待发」，即可改编平台版本、导出并记录发布链接。</div>}
            </section>
            <section aria-labelledby="recent-title">
              <div className="workbench-section-head"><h2 id="recent-title">最近的稿件</h2><Link to="/studio" className="small muted">查看全部<Icon name="chevronRight" size={13} /></Link></div>
              {data.recent_documents.length ? <div className="card work-list">{data.recent_documents.map((doc) => <WorkRow key={doc.id} doc={doc} />)}</div> : <Empty title="还没有稿件" hint="新建母稿，或从选题简报延伸创作。" />}
            </section>
          </div>
          <div className="stack">
            <section className="card workbench-aside" aria-labelledby="topics-title">
              <div className="workbench-section-head"><h2 id="topics-title">选题候选</h2><Link to="/brief" className="small muted">看完整简报</Link></div>
              <p className="tiny muted">{data.brief_day === data.today ? '今天的简报' : `最近一期 · ${fmtDate(data.brief_day)}`} · 选择一个切口直接开写</p>
              {data.topics.length ? data.topics.map((item) => <article key={item.id} className="work-topic">
                <div className="row tiny muted"><ModeBadge mode={item.origin} small /><span>{item.source_name || '选题简报'}</span></div>
                <h3>{item.title}</h3><p className="small muted clamp-2">{item.angles[0] || item.why || item.summary}</p>
                <button className={`btn sm ${extending === item.id ? 'loading' : ''}`} disabled={!!extending} onClick={() => extend(item)}>从这个切口开写<Icon name="chevronRight" size={13} /></button>
              </article>) : <div className="workbench-empty"><p className="small muted">暂时没有新的选题。刷新简报，或从自己的笔记开始。</p><Link to="/brief" className="btn sm">去选题简报</Link></div>}
            </section>
            <section className="card workbench-aside" aria-labelledby="capture-title">
              <div className="workbench-section-head"><h2 id="capture-title">素材随手记</h2><Icon name="bookmark" size={16} /></div>
              <p className="small muted">把观点、引文和链接留下，写作时再绑定到稿件。</p>
              <div className="capture-actions"><Link className="btn" to="/materials?add=note"><Icon name="plus" size={14} />记一条笔记</Link><Link className="btn" to="/materials?add=url"><Icon name="link" size={14} />收藏链接</Link></div>
              {data.recent_materials.length > 0 && <ul className="recent-material-links">{data.recent_materials.map((m) => <li key={m.id}><Link to={`/materials?focus=${m.id}`}><span className="clamp-1">{m.title}</span><Icon name="chevronRight" size={13} /></Link></li>)}</ul>}
            </section>
          </div>
        </div>
      </>}
    </div>
  )
}

function WorkRow({ doc }: { doc: DocumentSummary }) {
  return <Link className="work-row" to={`/studio/${doc.id}`}>
    <span className="work-row-main"><span className="work-row-title clamp-1">{doc.title}</span><span className="tiny muted">{PLATFORM_NAME[doc.target_platform]} · {doc.word_count} 字 · {ago(doc.updated_at)}更新</span></span>
    <span className={`work-status ${doc.status}`}>{DOC_STATUS_NAME[doc.status]}</span><Icon name="chevronRight" size={14} />
  </Link>
}
