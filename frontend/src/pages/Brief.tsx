import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, type BriefItem, type BriefPage } from '../lib/api'
import { useFetch } from '../lib/hooks'
import { ago, fmtDate } from '../lib/format'
import { Badge, Collapsible, Empty, ErrorNotice, IconButton, Loading, Menu, ModeBadge, useStored } from '../components/ui'
import { Icon } from '../components/icons'
import { errorMessage, useToast } from '../components/toast'
import { looksEnglish, TranslationPanel, useTranslatedTitle } from '../components/translation'

type Section = 'story' | 'signal' | 'opportunity'
const SECTIONS: Section[] = ['story', 'signal', 'opportunity']
const SECTION_TITLE: Record<Section, string> = { story: '今日值得写', signal: '正在升温的用户痛点', opportunity: '产品机会' }
const SECTION_HINT: Record<Section, string> = {
  story: '来自商业信源的动态，按「值得写的程度」排序；每条给出机制判断和可直接开写的切口。',
  signal: '来自 HN / Reddit / GitHub 的真实抱怨聚类，按速度排序——用户正在集中吐槽什么。',
  opportunity: '机会雷达里评分最高的产品机会，可作为「一人公司 / 商业模式」类选题。',
}

export default function Brief() {
  const [day, setDay] = useState<string | null>(null)
  const { data, error, loading, reload } = useFetch<BriefPage>(`/api/brief${day ? `?day=${day}` : ''}`)
  const [busy, setBusy] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [open, setOpen] = useStored<Record<string, boolean>>('ui.brief.sections', { story: true, signal: true, opportunity: true })
  const [hidden, setHidden] = useState<Set<string>>(new Set())
  const navigate = useNavigate()
  const { toast } = useToast()
  const pollRef = useRef<number | null>(null)

  useEffect(() => () => { if (pollRef.current) window.clearInterval(pollRef.current) }, [])

  async function refresh() {
    setRefreshing(true)
    try {
      await api.post('/api/jobs/run', { type: 'brief' })
      toast('正在抓取商业信源并重建简报，通常需要 1–3 分钟', 'info')
      const started = Date.now()
      pollRef.current = window.setInterval(async () => {
        try {
          const jobs = await api.get<{ running: { type: string | null } }>('/api/jobs')
          const stillRunning = jobs.running?.type === 'brief'
          if (!stillRunning || Date.now() - started > 300_000) {
            if (pollRef.current) window.clearInterval(pollRef.current)
            pollRef.current = null
            setRefreshing(false)
            reload()
            if (!stillRunning) toast('简报已更新', 'good')
          }
        } catch { /* keep polling */ }
      }, 5000)
    } catch (e) {
      setRefreshing(false)
      toast(errorMessage(e), 'bad')
    }
  }

  async function rebuild() {
    setBusy('rebuild')
    try {
      await api.post('/api/brief/rebuild')
      reload()
      toast('已用库里现有内容重排今天的简报', 'good')
    } catch (e) {
      toast(errorMessage(e), 'bad')
    } finally {
      setBusy(null)
    }
  }

  async function act(item: BriefItem, action: 'saved' | 'dismissed' | 'extend' | 'reassess', angle?: string) {
    setBusy(item.id)
    try {
      if (action === 'reassess') {
        const result = await api.post<{ model: string; input_characters: number }>(`/api/brief/items/${item.id}/reassess`)
        reload(); toast(`已用 ${result.model} 重新评估（读取 ${result.input_characters} 字符原文）`, 'good'); return
      }
      if (action === 'extend') {
        const res = await api.post<{ document_id: string }>(`/api/brief/items/${item.id}/extend`, { angle })
        navigate(`/studio/${res.document_id}`)
        return
      }
      if (action === 'dismissed') {
        setHidden((s) => new Set(s).add(item.id))
        await new Promise((r) => setTimeout(r, 200))
      }
      await api.post(`/api/brief/items/${item.id}/status`, { status: action })
      toast(action === 'saved' ? '已存入素材库' : '已忽略这条', 'good')
      reload()
    } catch (e) {
      toast(errorMessage(e), 'bad')
      setHidden((s) => { const n = new Set(s); n.delete(item.id); return n })
    } finally {
      setBusy(null)
    }
  }

  const total = data ? Object.values(data.counts).reduce((a, b) => a + b, 0) : 0
  const noModel = data && !data.models.fast

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>简报速览</h1>
          <div className="sub">一页看完今天值得写的东西。看到好的，直接「延伸创作」。</div>
        </div>
        <div className="actions">
          {data && data.days.length > 1 && (
            <Menu
              align="right"
              trigger={<button className="btn sm"><Icon name="clock" size={14} />{data.day === data.today ? `今天 ${fmtDate(data.day)}` : fmtDate(data.day)}<Icon name="chevronDown" size={13} /></button>}
              items={data.days.map((d) => ({ label: d === data.today ? `今天 · ${d}` : d, active: d === data.day, onSelect: () => setDay(d) }))}
            />
          )}
          <button className={`btn sm ${busy === 'rebuild' ? 'loading' : ''}`} onClick={rebuild} title="不抓取，只用库里已有内容重排今天的简报"><Icon name="layers" size={14} />重排</button>
          <button className={`btn sm primary ${refreshing ? 'loading' : ''}`} disabled={refreshing} onClick={refresh}><Icon name="refresh" size={14} />抓取并刷新</button>
        </div>
      </div>

      <ErrorNotice error={error} />
      {loading && !data && <Loading rows={6} />}

      {data && (
        <>
          <div className="status-strip">
            <span>{fmtDate(data.day)} · {total} 条</span>
            <ModeBadge mode={data.data_mode} />
            {noModel && <Badge tone="warn">未配置 FAST_MODEL：按规则 / 演示评分，没有 AI 判断</Badge>}
            {refreshing && <span className="row nowrap" style={{ gap: 6 }}><span className="spinner" style={{ width: 11, height: 11 }} />抓取中…</span>}
            {data.last_job && <span className="faint">上次任务 {data.last_job.job_type} · {ago(data.last_job.started_at)} · {data.last_job.status}</span>}
          </div>

          {total === 0 && (
            <Empty
              title="今天还没有简报"
              hint="点「抓取并刷新」从商业信源采集，或在「系统 → 任务」里运行演示数据。"
              action={<button className="btn primary" onClick={refresh}>抓取并刷新</button>}
            />
          )}

          {SECTIONS.map((section) => {
            const items = data.sections[section].filter((i) => !hidden.has(i.id) || i.status !== 'new')
            const all = data.sections[section]
            if (!all.length) return null
            const isOpen = open[section] ?? true
            return (
              <section key={section} className="brief-section">
                <div className={`disclosure md brief-section-head ${isOpen ? 'open' : ''}`} style={{ display: 'block' }}>
                  <div className="disclosure-head">
                    <button type="button" className="disclosure-btn" onClick={() => setOpen({ ...open, [section]: !isOpen })} aria-expanded={isOpen}>
                      <Icon name="chevronRight" size={14} className="chev" />
                      <span className="disclosure-title">{SECTION_TITLE[section]}</span>
                      <span className="disclosure-hint">{all.length}</span>
                      <span className="disclosure-hint hide-md" style={{ marginLeft: 10 }}>{SECTION_HINT[section]}</span>
                    </button>
                  </div>
                </div>
                <Collapsible open={isOpen}>
                  <div className="card brief-list">
                    {items.map((item, i) => (
                      <BriefRow key={item.id} item={item} index={i} busy={busy === item.id} leaving={hidden.has(item.id)} onAct={act} lanes={data.lanes} />
                    ))}
                  </div>
                </Collapsible>
              </section>
            )
          })}

          {data.recent_materials.length > 0 && (
            <section className="recent-materials">
              <div className="section-title"><h2>最近收藏的素材</h2><Link to="/materials" className="small">素材库 →</Link></div>
              <div className="card">
                <table className="table">
                  <tbody>
                    {data.recent_materials.map((m) => (
                      <tr key={m.id} className="link" onClick={() => navigate(`/materials?focus=${m.id}`)}>
                        <td style={{ width: 60 }}><ModeBadge mode={m.origin} small /></td>
                        <td><span className="ellipsis" style={{ display: 'block', maxWidth: 640 }}>{m.title}</span><div className="tiny muted">{m.source_name ?? m.kind}</div></td>
                        <td className="tiny faint" style={{ width: 90, textAlign: 'right' }}>{ago(m.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      )}
    </div>
  )
}

function BriefRow({ item, index, busy, leaving, onAct, lanes }: {
  item: BriefItem; index: number; busy: boolean; leaving: boolean
  onAct: (i: BriefItem, a: 'saved' | 'dismissed' | 'extend' | 'reassess', angle?: string) => void; lanes: Record<string, string>
}) {
  const [open, setOpen] = useState(false)
  const [translatedTitle, setTranslatedTitle] = useState<string | null>(null)
  const titleTranslation = useTranslatedTitle('brief_item', item.id, looksEnglish(item.title), item.title)
  const displayTitle = translatedTitle ?? titleTranslation.data?.title ?? item.title
  const showTranslationTitle = useCallback((title: string | null) => setTranslatedTitle(title ?? item.title), [item.title])
  const used = item.status === 'used'
  const saved = item.status === 'saved'
  const detailLink = item.ref_type === 'signal' ? `/signals/${item.ref_id}` : item.ref_type === 'pain_cluster' ? `/clusters/${item.ref_id}` : `/opportunities/${item.ref_id}`
  const score = Math.round(item.score)
  const { toast } = useToast()
  return (
    <div className={`brief-row ${used ? 'used' : ''} ${open ? 'open' : ''} ${leaving ? 'leaving' : ''}`} style={{ animationDelay: leaving ? undefined : `${Math.min(index, 8) * 30}ms` }}>
      <div className="score-col"><span className={`score-pill ${score >= 85 ? 'top' : score >= 70 ? 'hi' : ''}`} title="值得写的程度">{score}</span></div>
      <div className="body">
        <div className="meta-line">
          <ModeBadge mode={item.origin} small />
          {item.lane && <Badge tone="neutral" small>{lanes[item.lane] ?? item.lane_name ?? item.lane}</Badge>}
          {item.source_name && <span>{item.source_name}</span>}
          {item.meta?.published_at ? <span className="faint">{ago(String(item.meta.published_at))}</span> : null}
          {item.meta?.method === 'rule' && <span className="faint" title="未配置 FAST_MODEL，按规则评分">规则评分</span>}
          {saved && <Badge tone="accent" small>已收藏</Badge>}
          {used && <Badge tone="good" small>已延伸</Badge>}
        </div>
        <div className="title clamp-2">
          {item.url ? <a href={item.url} target="_blank" rel="noreferrer" title={item.title}>{displayTitle}</a> : <Link to={detailLink} title={item.title}>{displayTitle}</Link>}
        </div>
        {item.why && <div className={`why ${open ? '' : 'clamp-2'}`}>{item.why}</div>}
        {item.angles.length > 0 && (
          <div className="angles">
            {item.angles.map((a) => (
              <button key={a} className="chip" disabled={busy} title="用这个切口开始写" onClick={() => onAct(item, 'extend', a)}><Icon name="pen" size={11} />{a}</button>
            ))}
          </div>
        )}
      </div>
      <div className="row-actions">
        <div className="material-action">
          {!saved && !used ? (
            <IconButton icon="bookmark" tip="存为素材" disabled={busy} onClick={() => onAct(item, 'saved')} />
          ) : item.material_id ? (
            <Link className="iconbtn active" to={`/materials?focus=${item.material_id}`} aria-label="查看已存素材" data-tip="查看已存素材"><Icon name="bookmark" size={15} /></Link>
          ) : null}
        </div>
        {used && item.document_id ? (
          <Link className="btn sm primary" to={`/studio/${item.document_id}`}><Icon name="file" size={13} />打开稿件</Link>
        ) : (
          <button className={`btn sm primary ${busy ? 'loading' : ''}`} disabled={busy} onClick={() => onAct(item, 'extend')}><Icon name="pen" size={13} />延伸创作</button>
        )}
        <Menu
          label="更多"
          trigger={<button type="button" className="iconbtn" aria-label="更多"><Icon name="more" size={16} /></button>}
          items={[
            ...(item.section === 'story' ? [{ label: busy ? '评估中…' : '重新评估选题（Agnes）', icon: 'refresh' as const, onSelect: () => { if (!busy) onAct(item, 'reassess') } }] : []),
            { label: '查看原始记录', icon: 'external', onSelect: () => window.open(detailLink, '_self') },
            ...(item.url ? [{ label: '复制链接', icon: 'link' as const, onSelect: () => { navigator.clipboard.writeText(item.url as string).then(() => toast('已复制链接', 'good')).catch(() => undefined) } }] : []),
            ...(item.url ? [{ label: '打开原文', icon: 'external' as const, href: item.url }] : []),
            '-' as const,
            ...(!used ? [{ label: '今天不看这条', icon: 'eyeOff' as const, danger: true, onSelect: () => onAct(item, 'dismissed') }] : []),
          ]}
        />
        <IconButton icon="chevronDown" tip={open ? '收起' : '摘要'} className="expand" onClick={() => setOpen(!open)} />
      </div>
      <div className="detail">
        <Collapsible open={open}>
          <div className="detail-inner">
            {open && looksEnglish(item.title + item.summary) ? <TranslationPanel refType="brief_item" refId={item.id} originalContent={item.summary || '（无摘要）'} onTitle={showTranslationTitle} /> : item.summary || '（无摘要）'}
            <div style={{ marginTop: 6 }}><Link to={detailLink} className="tiny" style={{ color: 'var(--accent)' }}>查看原始记录 →</Link></div>
          </div>
        </Collapsible>
      </div>
    </div>
  )
}
