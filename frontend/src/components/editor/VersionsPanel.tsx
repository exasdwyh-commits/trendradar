import { useState } from 'react'
import { api, type DocumentFull } from '../../lib/api'
import { fmtDateTime } from '../../lib/format'
import { errorMessage, useToast } from '../toast'
import { Badge, IconButton, Loading } from '../ui'

const VERSION_SOURCE: Record<string, string> = { autosave: '自动', manual: '手动', ai: 'AI 前快照', restore: '恢复前快照', seed: '新建' }

export default function VersionsPanel({ doc, content, reload, onRestored, beforeAction }: { doc: DocumentFull; content: string; reload: () => void; onRestored: (d: DocumentFull) => void; beforeAction: () => Promise<boolean> }) {
    const { toast } = useToast()
    const [preview, setPreview] = useState<{ number: number; content: string } | null>(null)
    async function view(n: number) {
        const v = await api.get<{ content_md: string }>(`/api/documents/${doc.id}/versions/${n}`)
        setPreview({ number: n, content: v.content_md })
    }
  async function restore(n: number) {
    if (!window.confirm(`恢复到 v${n}？当前内容会先保存为快照。`)) return
    try {
      if (!await beforeAction()) return
      const d = await api.post<DocumentFull>(`/api/documents/${doc.id}/versions/${n}/restore`)
      onRestored(d)
      setPreview(null)
      reload()
      toast(`已恢复到 v${n}`, 'good')
    } catch (e) { toast(errorMessage(e), 'bad') }
  }
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="tiny muted">自动保存每 15 分钟留一个快照；⌘S 或「保存版本」随时留名。</div>
      {preview && (
        <div className="card pad ai-result">
          <div className="row between" style={{ marginBottom: 6 }}><b className="small">v{preview.number}</b><IconButton icon="x" tip="关闭" onClick={() => setPreview(null)} /></div>
          <div className="creation-comparison"><div><strong>所选版本</strong><pre>{preview.content}</pre></div><div><strong>当前正文</strong><pre>{content}</pre></div></div>
        </div>
      )}
      <div>
        {doc.versions.map((v) => (
          <div key={v.id} className={`row between nowrap version-row ${preview?.number === v.version_number ? 'fade-in' : ''}`}>
            <div style={{ minWidth: 0 }}>
              <div className="small"><b>v{v.version_number}</b> <span className="muted">{VERSION_SOURCE[v.source] ?? v.source}</span>{v.note && <span className="muted"> · {v.note}</span>}</div>
              <div className="tiny faint">{fmtDateTime(v.created_at)} · {v.word_count} 字</div>
            </div>
            <div className="row nowrap" style={{ gap: 2 }}>
              <IconButton icon="eye" tip="查看" onClick={() => view(v.version_number)} />
              <IconButton icon="history" tip="恢复到这个版本" onClick={() => restore(v.version_number)} />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ───────────────────────── 平台版本 ─────────────────────────

