import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, type Material } from '../lib/api'
import { useFetch } from '../lib/hooks'
import { ago, fmtDateTime } from '../lib/format'
import { Badge, Collapsible, Disclosure, Empty, ErrorNotice, IconButton, Loading, Menu, ModeBadge } from '../components/ui'
import { Icon } from '../components/icons'
import { errorMessage, useToast } from '../components/toast'
import { looksEnglish, TranslationPanel } from '../components/translation'

const KIND_NAME: Record<string, string> = { story: '商业动态', signal: '用户信号', cluster: '痛点簇', opportunity: '产品机会', url: '链接', note: '笔记' }

export default function Materials() {
  const [params, setParams] = useSearchParams()
  const focus = params.get('focus')
  const [q, setQ] = useState('')
  const [kind, setKind] = useState('')
  const [archived, setArchived] = useState(false)
  const qs = new URLSearchParams()
  if (q) qs.set('q', q)
  if (kind) qs.set('kind', kind)
  if (archived) qs.set('archived', '1')
  const { data, error, loading, reload } = useFetch<{ items: Material[]; kinds: Record<string, number> }>(`/api/materials?${qs.toString()}`)
  const { data: detail, reload: reloadDetail } = useFetch<Material>(focus ? `/api/materials/${focus}` : null, [focus])
  const navigate = useNavigate()
  const { toast } = useToast()
  const [adding, setAdding] = useState<'url' | 'note' | null>(() => params.get('add') === 'note' ? 'note' : params.get('add') === 'url' ? 'url' : null)
  const [url, setUrl] = useState('')
  const [note, setNote] = useState({ title: '', content: '' })
  const [busy, setBusy] = useState(false)
  const [bodyOpen, setBodyOpen] = useState(false)

  async function addUrl() {
    if (!url.trim()) return
    setBusy(true)
    try {
      const m = await api.post<Material>('/api/materials', { kind: 'url', url: url.trim() })
      setUrl(''); setAdding(null)
      reload()
      setParams({ focus: m.id })
      toast('已抓取并存入素材库', 'good')
    } catch (e) {
      toast(errorMessage(e), 'bad')
    } finally {
      setBusy(false)
    }
  }
  async function addNote() {
    if (!note.title.trim()) return
    setBusy(true)
    try {
      const m = await api.post<Material>('/api/materials', { kind: 'note', title: note.title.trim(), content: note.content })
      setNote({ title: '', content: '' }); setAdding(null)
      reload()
      setParams({ focus: m.id })
      toast('笔记已保存', 'good')
    } catch (e) {
      toast(errorMessage(e), 'bad')
    } finally {
      setBusy(false)
    }
  }
  async function extend(m: Material) {
    const res = await api.post<{ document_id: string }>(`/api/materials/${m.id}/extend`)
    navigate(`/studio/${res.document_id}`)
  }
  async function toggleArchive(m: Material) {
    await api.patch(`/api/materials/${m.id}`, { archived: !m.archived })
    reload(); reloadDetail()
    toast(m.archived ? '已取消归档' : '已归档', 'good')
  }
  const close = () => setParams({})

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>素材库</h1>
          <div className="sub">收藏的动态、信号、链接与笔记。所有 AI 写作都只依据这里的事实。</div>
        </div>
        <div className="actions">
          <Menu
            trigger={<button className="btn sm primary"><Icon name="plus" size={14} />添加素材<Icon name="chevronDown" size={12} /></button>}
            items={[
              { label: '粘贴链接（自动抓取）', icon: 'link', onSelect: () => setAdding('url') },
              { label: '写一条笔记', icon: 'note', onSelect: () => setAdding('note') },
            ]}
          />
        </div>
      </div>

      <Collapsible open={adding !== null}>
        <div className="card pad" style={{ marginBottom: 14 }}>
          {adding === 'url' && (
            <div>
              <div className="small muted" style={{ marginBottom: 6 }}>粘贴链接，自动抓取标题 / 摘要 / 正文</div>
              <div className="row nowrap" style={{ gap: 6 }}>
                <input className="input" aria-label="素材链接" placeholder="https://…" value={url} autoFocus onChange={(e) => setUrl(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && addUrl()} />
                <button className={`btn ${busy ? 'loading' : ''}`} disabled={busy || !url} onClick={addUrl}>抓取</button>
                <button className="btn ghost" onClick={() => setAdding(null)}>取消</button>
              </div>
            </div>
          )}
          {adding === 'note' && (
            <div className="stack" style={{ gap: 6 }}>
              <input className="input" aria-label="笔记标题" placeholder="标题" value={note.title} autoFocus onChange={(e) => setNote({ ...note, title: e.target.value })} />
              <textarea className="input" aria-label="笔记内容" rows={3} placeholder="内容（数据、观点、引用……）" value={note.content} onChange={(e) => setNote({ ...note, content: e.target.value })} />
              <div className="row" style={{ gap: 6 }}>
                <button className={`btn primary ${busy ? 'loading' : ''}`} disabled={busy || !note.title} onClick={addNote}>保存笔记</button>
                <button className="btn ghost" onClick={() => setAdding(null)}>取消</button>
              </div>
            </div>
          )}
        </div>
      </Collapsible>

      <div className="row" style={{ marginBottom: 14 }}>
        <div className="tabs">
          <button className={kind === '' ? 'active' : ''} onClick={() => setKind('')}>全部</button>
          {Object.entries(data?.kinds ?? {}).map(([k, n]) => <button key={k} className={kind === k ? 'active' : ''} onClick={() => setKind(k)}>{KIND_NAME[k] ?? k} {n}</button>)}
        </div>
        <div className="search" style={{ maxWidth: 260, flex: 1 }}><Icon name="search" size={14} /><input className="input sm" placeholder="搜索标题 / 摘要 / 引文" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        <label className="small muted row nowrap" style={{ gap: 6, cursor: 'pointer' }}><input type="checkbox" className="toggle" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> 已归档</label>
      </div>

      <ErrorNotice error={error} />
      {loading && !data && <Loading rows={6} />}
      {data && data.items.length === 0 && <Empty title="素材库是空的" hint="在简报里点「存为素材」，或添加链接 / 笔记。" action={<Link className="btn" to="/brief">去简报</Link>} />}

      {data && data.items.length > 0 && (
        <div className={`materials-layout ${detail ? 'with-detail' : ''}`}>
          <div className="card">
            <table className="table">
              <tbody>
                {data.items.map((m) => (
                  <tr key={m.id} className={`link ${focus === m.id ? 'selected' : ''}`} onClick={() => setParams({ focus: m.id })}>
                    <td style={{ width: 60 }}><ModeBadge mode={m.origin} small /></td>
                    <td>
                      <div style={{ fontWeight: 600 }} className="clamp-1">{m.title}</div>
                      <div className="tiny muted">{KIND_NAME[m.kind] ?? m.kind}{m.source_name ? ` · ${m.source_name}` : ''}{m.document_count ? ` · 用于 ${m.document_count} 篇` : ''}</div>
                    </td>
                    <td className="tiny faint" style={{ width: 90, textAlign: 'right' }}>{ago(m.created_at)}</td>
                    <td style={{ width: 44 }} onClick={(e) => e.stopPropagation()}>
                      <span className="hover-only"><IconButton icon="pen" tip="延伸创作" onClick={() => extend(m)} /></span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {detail && (
            <>
              <div className="drawer-backdrop" onClick={close} />
              <div className="card pad detail-pane">
                <div className="row between nowrap" style={{ alignItems: 'flex-start' }}>
                  <div className="row" style={{ gap: 6 }}><ModeBadge mode={detail.origin} small /><Badge tone="neutral" small>{KIND_NAME[detail.kind] ?? detail.kind}</Badge>{detail.archived ? <Badge tone="bad" small>已归档</Badge> : null}</div>
                  <IconButton icon="x" tip="关闭" onClick={close} />
                </div>
                <h3 style={{ margin: '8px 0 4px', lineHeight: 1.4 }}>{detail.url ? <a href={detail.url} target="_blank" rel="noreferrer">{detail.title} <Icon name="external" size={12} /></a> : detail.title}</h3>
                <div className="tiny muted">{detail.source_name}{detail.author ? ` · ${detail.author}` : ''}{detail.published_at ? ` · ${fmtDateTime(detail.published_at)}` : ''}</div>
                {looksEnglish(detail.title + detail.content + detail.summary) ? <TranslationPanel key={detail.id} refType="material" refId={detail.id} originalContent={detail.content || detail.summary || detail.quote} /> : <>
                {detail.summary && <p className="small" style={{ marginTop: 10, lineHeight: 1.6 }}>{detail.summary}</p>}
                {detail.quote && <blockquote className="quote small" style={{ marginTop: 8 }}>{detail.quote}</blockquote>}
                {detail.content && detail.content !== detail.summary && (
                  <div style={{ marginTop: 6 }}>
                    <Disclosure size="sm" title="正文" hint={`${detail.content.length} 字`} open={bodyOpen} onToggle={() => setBodyOpen(!bodyOpen)}>
                      <pre className="ai-pre" style={{ maxHeight: 300 }}>{detail.content}</pre>
                    </Disclosure>
                  </div>
                )}
                </>}
                {detail.tags.length > 0 && <div className="tiny muted" style={{ marginTop: 8 }}>{detail.tags.map((t) => `#${t}`).join(' ')}</div>}
                {detail.ref_type && detail.ref_id && (
                  <div className="tiny" style={{ marginTop: 8 }}>
                    <Link style={{ color: 'var(--accent)' }} to={detail.ref_type === 'signal' ? `/signals/${detail.ref_id}` : detail.ref_type === 'pain_cluster' ? `/clusters/${detail.ref_id}` : detail.ref_type === 'opportunity' ? `/opportunities/${detail.ref_id}` : '#'}>查看原始记录 →</Link>
                  </div>
                )}
                <div className="row" style={{ gap: 6, marginTop: 14 }}>
                  <button className="btn primary sm" onClick={() => extend(detail)}><Icon name="pen" size={13} />延伸创作</button>
                  <button className="btn sm" onClick={() => toggleArchive(detail)}>{detail.archived ? '取消归档' : '归档'}</button>
                </div>
                {detail.documents && detail.documents.length > 0 && (
                  <div style={{ marginTop: 14 }}>
                    <div className="tiny muted" style={{ marginBottom: 4 }}>用于稿件</div>
                    {detail.documents.map((d) => <div key={d.id} className="small"><Link to={`/studio/${d.id}`}><Icon name="file" size={12} /> {d.title}</Link></div>)}
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
