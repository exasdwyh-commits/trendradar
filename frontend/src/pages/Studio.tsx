import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { DOC_STATUS_NAME, PLATFORM_NAME, api, type DocStatus, type DocumentSummary } from '../lib/api'
import { useFetch } from '../lib/hooks'
import { useNewDocument } from '../lib/useNewDocument'
import { ago } from '../lib/format'
import { Badge, Empty, ErrorNotice, IconButton, Loading, Menu, ModeBadge } from '../components/ui'
import { Icon } from '../components/icons'
import { errorMessage, useToast } from '../components/toast'

const STATUS_TONE: Record<string, 'neutral' | 'accent' | 'good' | 'warn' | 'bad'> = { idea: 'neutral', draft: 'accent', ready: 'warn', published: 'good', archived: 'bad' }

export default function Studio() {
  const [filters, setFilters] = useSearchParams()
  const status = filters.get('status') ?? ''
  const setStatus = (next: string) => setFilters(next ? { status: next } : {})
  const [q, setQ] = useState('')
  const params = new URLSearchParams()
  if (status) params.set('status', status)
  if (q) params.set('q', q)
  const { data, error, loading, reload } = useFetch<{ items: DocumentSummary[] }>(`/api/documents?${params.toString()}`)
  const navigate = useNavigate()
  const { toast } = useToast()
  const { create: createBlank, busy } = useNewDocument()

  async function setDocStatus(id: string, next: DocStatus) {
    try {
      await api.patch(`/api/documents/${id}`, { status: next, save_mode: 'manual', note: `状态改为${DOC_STATUS_NAME[next]}` })
      reload()
      toast(`已改为「${DOC_STATUS_NAME[next]}」`, 'good')
    } catch (e) { toast(errorMessage(e), 'bad') }
  }
  async function remove(d: DocumentSummary) {
    if (!window.confirm(`删除稿件「${d.title || '未命名'}」？此操作不可恢复。`)) return
    try {
      await api.del(`/api/documents/${d.id}`)
      reload()
      toast('已删除', 'good')
    } catch (e) { toast(errorMessage(e), 'bad') }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>稿件</h1>
          <div className="sub">灵感 → 草稿 → 待发 → 已发布。先完成一篇母稿，再生成各平台版本。</div>
        </div>
        <div className="actions">
          <button className={`btn sm primary ${busy ? 'loading' : ''}`} disabled={busy} onClick={createBlank}><Icon name="plus" size={14} />新建稿件</button>
        </div>
      </div>

      <div className="row" style={{ marginBottom: 14 }}>
        <div className="tabs">
          {['', 'idea', 'draft', 'ready', 'published', 'archived'].map((s) => (
            <button key={s} className={status === s ? 'active' : ''} onClick={() => setStatus(s)}>{s ? DOC_STATUS_NAME[s as DocStatus] : '全部'}</button>
          ))}
        </div>
        <div className="search" style={{ maxWidth: 280, flex: 1 }}><Icon name="search" size={14} /><input className="input sm" aria-label="搜索稿件" placeholder="搜索标题 / 核心判断" value={q} onChange={(e) => setQ(e.target.value)} /></div>
      </div>

      <ErrorNotice error={error} />
      {loading && !data && <Loading rows={5} />}
      {data && data.items.length === 0 && (
        <Empty title={status || q ? '没有匹配的稿件' : '还没有稿件'} hint={status || q ? '换个状态或搜索词，也可以清除筛选。' : '从选题简报延伸创作，或新建公众号母稿。'} action={status || q ? <button className="btn" onClick={() => { setStatus(''); setQ('') }}>清除筛选</button> : <Link className="btn" to="/brief">去选题简报</Link>} />
      )}
      {data && data.items.length > 0 && (
        <div className="card fade-in">
          <div className="table-wrap">
          <table className="table">
            <thead>
              <tr><th>标题</th><th>状态</th><th>平台</th><th style={{ textAlign: 'right' }}>字数</th><th className="hide-md">素材</th><th className="hide-md">版本</th><th>更新</th><th /></tr>
            </thead>
            <tbody>
              {data.items.map((d) => (
                <tr key={d.id}>
                  <td style={{ maxWidth: 460 }}>
                    <Link to={`/studio/${d.id}`} className="row nowrap" style={{ gap: 8 }}><ModeBadge mode={d.data_mode} small /><span style={{ fontWeight: 600 }} className="ellipsis">{d.title || <span className="faint">未命名稿件</span>}</span></Link>
                    {d.thesis && <div className="tiny muted clamp-1" style={{ marginTop: 3 }}>{d.thesis}</div>}
                  </td>
                  <td><Badge tone={STATUS_TONE[d.status]}>{DOC_STATUS_NAME[d.status]}</Badge></td>
                  <td className="small" style={{ whiteSpace: 'nowrap' }}>{PLATFORM_NAME[d.target_platform]}{d.variant_count > 0 && <span className="faint"> +{d.variant_count}</span>}{d.publication_count > 0 && <span className="faint"> · 已发 {d.publication_count}</span>}</td>
                  <td className="mono small" style={{ textAlign: 'right' }}>{d.word_count}</td>
                  <td className="small hide-md">{d.material_count}</td>
                  <td className="small hide-md">v{d.current_version}</td>
                  <td className="small muted" style={{ whiteSpace: 'nowrap' }}>{ago(d.updated_at)}</td>
                  <td onClick={(e) => e.stopPropagation()} style={{ width: 44 }}>
                    <span className="hover-only">
                      <Menu
                        trigger={<span><IconButton icon="more" tip="更多" /></span>}
                        items={[
                          { label: '打开', icon: 'edit', onSelect: () => navigate(`/studio/${d.id}`) },
                          '-',
                          ...(['idea', 'draft', 'ready', 'published'] as DocStatus[]).filter((s) => s !== d.status).map((s) => ({ label: `标记为${DOC_STATUS_NAME[s]}`, onSelect: () => setDocStatus(d.id, s) })),
                          '-' as const,
                          ...(d.status !== 'archived' ? [{ label: '归档', icon: 'trash' as const, onSelect: () => setDocStatus(d.id, 'archived') }] : [{ label: '取消归档', icon: 'history' as const, onSelect: () => setDocStatus(d.id, 'draft') }]),
                          { label: '删除', icon: 'x', danger: true, onSelect: () => remove(d) },
                        ]}
                      />
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </div>
      )}
    </div>
  )
}
