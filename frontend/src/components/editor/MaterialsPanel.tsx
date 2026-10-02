import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type DocumentFull, type Material } from '../../lib/api'
import { ago, fmtDateTime } from '../../lib/format'
import { useFetch } from '../../lib/hooks'
import { errorMessage, useToast } from '../toast'
import { Badge, Disclosure, ErrorNotice, IconButton, Loading, Menu, ModeBadge } from '../ui'
import { Icon } from '../icons'
import { LANES } from './editorUtils'

export default function MaterialsPanel({ doc, reload, onInsert }: { doc: DocumentFull; reload: () => void; onInsert: (t: string) => void }) {
  const { toast } = useToast()
  const [url, setUrl] = useState('')
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [addOpen, setAddOpen] = useState(doc.materials.length === 0)
  const [libOpen, setLibOpen] = useState(false)
  const { data: library } = useFetch<{ items: Material[] }>(libOpen ? (q.length >= 1 ? `/api/materials?q=${encodeURIComponent(q)}` : '/api/materials') : null)
  const bound = new Set(doc.materials.map((m) => m.id))

  async function addUrl() {
    if (!url.trim()) return
    setBusy(true)
    try {
      const m = await api.post<Material>('/api/materials', { kind: 'url', url: url.trim() })
      await api.post(`/api/documents/${doc.id}/materials`, { material_id: m.id })
      setUrl('')
      reload()
      toast('已抓取并绑定到本稿', 'good')
    } catch (e) {
      toast(errorMessage(e), 'bad')
    } finally {
      setBusy(false)
    }
  }
  async function bind(materialId: string) {
    await api.post(`/api/documents/${doc.id}/materials`, { material_id: materialId })
    reload()
    toast('已绑定素材', 'good')
  }
  async function unbind(materialId: string) {
    await api.del(`/api/documents/${doc.id}/materials/${materialId}`)
    reload()
  }

  return (
    <div>
      <div className="tiny muted" style={{ marginBottom: 10 }}>AI 只会使用这里绑定的素材和正文中的事实；引用时会标注来源。</div>
      <div className="stack" style={{ gap: 8, marginBottom: 12 }}>
        {doc.materials.map((m) => (
          <div key={m.id} className="card pad material-card fade-in">
            <div className="row between nowrap" style={{ alignItems: 'flex-start' }}>
              <div style={{ minWidth: 0 }}>
                <div className="row" style={{ gap: 6, marginBottom: 4 }}><ModeBadge mode={m.origin} small />{m.relation === 'seed' && <Badge tone="accent" small>起点</Badge>}{m.lane && <span className="tiny faint">{LANES[m.lane] ?? m.lane}</span>}</div>
                <div style={{ fontWeight: 600, fontSize: 13, lineHeight: 1.4 }}>{m.url ? <a href={m.url} target="_blank" rel="noreferrer">{m.title}</a> : m.title}</div>
                <div className="tiny muted">{m.source_name}{m.published_at ? ` · ${fmtDateTime(m.published_at)}` : ''}</div>
              </div>
              <Menu
                trigger={<button type="button" className="iconbtn" aria-label="更多"><Icon name="more" size={15} /></button>}
                items={[
                  ...(m.quote ? [{ label: '插入引文', icon: 'note' as const, onSelect: () => onInsert(`> ${m.quote}\n> — ${m.source_name ?? m.title}${m.url ? `，${m.url}` : ''}`) }] : []),
                  ...(m.url ? [{ label: '插入来源', icon: 'link' as const, onSelect: () => onInsert(`（来源：[${m.source_name ?? m.title}](${m.url})）`) }] : []),
                  { label: '素材详情', icon: 'external', onSelect: () => window.open(`/materials?focus=${m.id}`, '_self') },
                  '-',
                  { label: '解除绑定', icon: 'x', danger: true, onSelect: () => unbind(m.id) },
                ]}
              />
            </div>
            {m.quote && <blockquote className="quote small" style={{ marginTop: 8 }}>{m.quote}</blockquote>}
            {(m.quote || m.url) && (
              <div className="row" style={{ gap: 6, marginTop: 8 }}>
                {m.quote && <button className="btn xs" onClick={() => onInsert(`> ${m.quote}\n> — ${m.source_name ?? m.title}${m.url ? `，${m.url}` : ''}`)}>插入引文</button>}
                {m.url && <button className="btn xs" onClick={() => onInsert(`（来源：[${m.source_name ?? m.title}](${m.url})）`)}>插入来源</button>}
              </div>
            )}
          </div>
        ))}
      </div>

      <Disclosure size="sm" title="添加链接" hint="自动抓取标题 / 摘要 / 正文" open={addOpen} onToggle={() => setAddOpen(!addOpen)}>
        <div className="row nowrap" style={{ gap: 6, padding: '4px 0 10px' }}>
          <input className="input sm" placeholder="https://…" value={url} onChange={(e) => setUrl(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && addUrl()} style={{ flex: 1 }} />
          <button className={`btn sm ${busy ? 'loading' : ''}`} disabled={busy || !url} onClick={addUrl}>添加</button>
        </div>
      </Disclosure>
      <Disclosure size="sm" title="从素材库绑定" open={libOpen} onToggle={() => setLibOpen(!libOpen)}>
        <div style={{ padding: '4px 0 8px' }}>
          <div className="search"><Icon name="search" size={13} /><input className="input sm" placeholder="搜索素材库" value={q} onChange={(e) => setQ(e.target.value)} /></div>
          <div className="stack" style={{ gap: 4, marginTop: 6, maxHeight: 260, overflow: 'auto' }}>
            {(library?.items ?? []).filter((m) => !bound.has(m.id)).slice(0, 30).map((m) => (
              <button key={m.id} className="history-row" onClick={() => bind(m.id)} title="绑定到本稿">
                <span className="ellipsis" style={{ minWidth: 0 }}><ModeBadge mode={m.origin} small /> {m.title}</span>
                <Icon name="plus" size={13} />
              </button>
            ))}
            {library && library.items.filter((m) => !bound.has(m.id)).length === 0 && <div className="tiny faint">没有可绑定的素材</div>}
          </div>
        </div>
      </Disclosure>
    </div>
  )
}

// ───────────────────────── 版本 ─────────────────────────

const VERSION_SOURCE: Record<string, string> = { autosave: '自动', manual: '手动', ai: 'AI 前快照', restore: '恢复前快照', seed: '新建' }

