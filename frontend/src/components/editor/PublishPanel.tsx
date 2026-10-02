import { useState } from 'react'
import { PLATFORM_NAME, api, type DocumentFull, type Platform } from '../../lib/api'
import { fmtDateTime } from '../../lib/format'
import { errorMessage, useToast } from '../toast'
import { Badge, IconButton, Menu } from '../ui'
import { Icon } from '../icons'

export default function PublishPanel({ doc, reload, navigate }: { doc: DocumentFull; reload: () => void; navigate: (p: string) => void }) {
  const { toast } = useToast()
  const [platform, setPlatform] = useState<Platform>(doc.target_platform)
  const [url, setUrl] = useState('')
  const [note, setNote] = useState('')
  async function record() {
    try {
      const variant = doc.variants.find((v) => v.platform === platform)
      await api.post(`/api/documents/${doc.id}/publications`, { platform, external_url: url || null, note: note || null, variant_id: variant?.id ?? null })
      setUrl(''); setNote('')
      reload()
      toast(`已记录${PLATFORM_NAME[platform]}发布`, 'good')
    } catch (e) {
      toast(errorMessage(e), 'bad')
    }
  }
  return (
    <div className="stack" style={{ gap: 12 }}>
      <div className="tiny muted">V1 不直连平台 API：在平台后台发布后，把链接记在这里，形成发布记录与复盘账本。</div>
      {doc.status !== 'ready' && doc.status !== 'published' && (
        <button className="btn sm" onClick={async () => { await api.patch(`/api/documents/${doc.id}`, { status: 'ready', save_mode: 'autosave' }); reload(); toast('已标记为待发', 'good') }}><Icon name="check" size={13} />标记为待发</button>
      )}
      <div className="card pad stack" style={{ gap: 8 }}>
        <Menu
          align="left"
          trigger={<button className="btn sm" style={{ width: '100%', justifyContent: 'space-between' }}>{PLATFORM_NAME[platform]}<Icon name="chevronDown" size={12} /></button>}
          items={(Object.keys(PLATFORM_NAME) as Platform[]).map((p) => ({ label: PLATFORM_NAME[p], active: p === platform, onSelect: () => setPlatform(p) }))}
        />
        <input className="input sm" placeholder="发布链接（可选）" value={url} onChange={(e) => setUrl(e.target.value)} />
        <input className="input sm" placeholder="备注（可选）" value={note} onChange={(e) => setNote(e.target.value)} />
        <button className="btn sm primary" onClick={record}><Icon name="send" size={13} />记录发布</button>
      </div>
      {doc.publications.map((p) => (
        <div key={p.id} className="row between nowrap version-row">
          <div className="small" style={{ minWidth: 0 }}><Badge tone="good" small>{PLATFORM_NAME[p.platform]}</Badge> {p.external_url ? <a href={p.external_url} target="_blank" rel="noreferrer" className="ellipsis" style={{ display: 'inline-block', maxWidth: 200, verticalAlign: 'bottom' }}>{p.external_url}</a> : <span className="muted">无链接</span>}{p.note && <div className="tiny muted">{p.note}</div>}</div>
          <div className="row nowrap" style={{ gap: 4 }}><span className="tiny faint">{fmtDateTime(p.published_at)}</span><IconButton icon="trash" tip="删除记录" onClick={async () => { await api.del(`/api/publications/${p.id}`); reload() }} /></div>
        </div>
      ))}
      <button className="btn sm ghost" onClick={() => navigate('/publish')}>打开发布中心 →</button>
    </div>
  )
}
