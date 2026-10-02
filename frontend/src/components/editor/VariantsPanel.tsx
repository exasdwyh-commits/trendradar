import { useState } from 'react'
import { PLATFORM_NAME, api, type DocumentFull, type Platform, type Variant } from '../../lib/api'
import { ago, fmtDateTime } from '../../lib/format'
import { renderMarkdown } from '../../lib/markdown'
import { errorMessage, useToast } from '../toast'
import { Badge, Collapsible, IconButton, Loading, Menu } from '../ui'
import { Icon } from '../icons'
import { escapeHtml } from './editorUtils'

export default function VariantsPanel({ doc, reload, content, beforeAction }: { doc: DocumentFull; reload: () => void; content: string; beforeAction: () => Promise<boolean> }) {
  const { toast } = useToast()
  const [busy, setBusy] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(doc.variants[0]?.id ?? null)

  async function generate(platform: Platform) {
    setBusy(platform)
    try {
      if (!await beforeAction()) return
      const v = await api.post<Variant>(`/api/documents/${doc.id}/variants`, { platform })
      setOpen(v.id)
      reload()
      toast(`已生成${PLATFORM_NAME[platform]}版`, 'good')
    } catch (e) {
      toast(errorMessage(e), 'bad')
    } finally {
      setBusy(null)
    }
  }
  async function remove(id: string) {
    if (!window.confirm('删除这个平台版本？')) return
    await api.del(`/api/variants/${id}`)
    reload()
  }
  const empty = !content.trim()
  return (
    <div className="stack" style={{ gap: 12 }}>
      <div className="tiny muted">母稿写好后，一键生成各平台版本；复制即可粘贴到平台编辑器。</div>
      <div className="row" style={{ gap: 6 }}>
        <Menu
          align="left"
          trigger={<button className={`btn sm primary ${busy ? 'loading' : ''}`} disabled={empty}><Icon name="plus" size={13} />生成平台版本<Icon name="chevronDown" size={12} /></button>}
          items={(Object.keys(PLATFORM_NAME) as Platform[]).map((p) => ({ label: `${PLATFORM_NAME[p]}版`, onSelect: () => generate(p), hint: doc.variants.some((v) => v.platform === p) ? '已有' : undefined }))}
        />
        {empty && <span className="tiny faint">母稿还是空的。</span>}
      </div>
      <ExportRow docId={doc.id} label="母稿" beforeAction={beforeAction} />
      {doc.variants.map((v) => (
        <div key={v.id} className="card pad fade-in">
          <div className="row between nowrap">
            <button className="row nowrap" style={{ gap: 6, background: 'none', border: 0, cursor: 'pointer', padding: 0, color: 'inherit', minWidth: 0, textAlign: 'left' }} onClick={() => setOpen(open === v.id ? null : v.id)}>
              <Icon name="chevronRight" size={13} className="chev" style={{ transform: open === v.id ? 'rotate(90deg)' : undefined, transition: 'transform .2s', color: 'var(--fg-faint)' }} />
              <Badge tone="accent" small>{PLATFORM_NAME[v.platform]}</Badge>
              <b className="small ellipsis">{v.title}</b>
              <span className="tiny faint" style={{ whiteSpace: 'nowrap' }}>{ago(v.created_at)}{v.generated_by === 'fixture' ? ' · 演示生成' : ''}</span>
            </button>
            <IconButton icon="trash" tip="删除" onClick={() => remove(v.id)} />
          </div>
          {v.warnings.filter((w) => !w.startsWith('演示生成')).map((w) => <div key={w} className="notice warn small" style={{ marginTop: 6 }}>{w}</div>)}
          <Collapsible open={open === v.id}>
            <pre className="ai-pre" style={{ maxHeight: 300, marginTop: 8 }}>{v.content_md}</pre>
            {v.meta?.tags && v.meta.tags.length > 0 && <div className="tiny muted" style={{ marginBottom: 6 }}>{v.meta.tags.map((t) => `#${t}`).join(' ')}</div>}
            <ExportRow docId={doc.id} variantId={v.id} label={PLATFORM_NAME[v.platform]} plain={v.plain_text} md={v.content_md} />
          </Collapsible>
        </div>
      ))}
    </div>
  )
}

function ExportRow({ docId, variantId, label, plain, md, beforeAction }: { docId: string; variantId?: string; label: string; plain?: string; md?: string; beforeAction?: () => Promise<boolean> }) {
  const { toast } = useToast()
  const base = `/api/documents/${docId}/export`
  const qs = variantId ? `&variant_id=${variantId}` : ''
  async function copyHtml() {
    try {
      if (beforeAction && !await beforeAction()) return
      const html = await exported('html')
      const text = plain ?? await exported('txt')
      try {
        await navigator.clipboard.write([new ClipboardItem({ 'text/html': new Blob([html], { type: 'text/html' }), 'text/plain': new Blob([text], { type: 'text/plain' }) })])
        toast('已复制带排版的 HTML，可直接粘贴到公众号编辑器', 'good')
      } catch {
        await navigator.clipboard.writeText(html)
        toast('已复制 HTML 源码', 'good')
      }
    } catch (e) { toast(errorMessage(e), 'bad') }
  }
  async function copyText() {
    try {
      if (beforeAction && !await beforeAction()) return
      const text = plain ?? await exported('txt')
      await navigator.clipboard.writeText(text)
      toast('已复制纯文本', 'good')
    } catch (e) { toast(errorMessage(e), 'bad') }
  }
  async function exported(fmt: string) {
    const res = await fetch(`${base}?fmt=${fmt}${qs}`)
    if (!res.ok) throw new Error('导出失败，请重试')
    return res.text()
  }
  async function download(fmt: string) {
    try {
      if (beforeAction && !await beforeAction()) return
      const text = fmt === 'md' && md ? md : await exported(fmt)
      const url = URL.createObjectURL(new Blob([text], { type: fmt === 'html' ? 'text/html' : 'text/plain;charset=utf-8' }))
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `${label}.${fmt}`
      anchor.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (e) { toast(errorMessage(e), 'bad') }
  }
  return (
    <div className="row nowrap" style={{ gap: 6, marginTop: 8 }}>
      <span className="tiny muted" style={{ whiteSpace: 'nowrap' }}>{label}：</span>
      <button className="btn xs" onClick={copyHtml}><Icon name="copy" size={12} />公众号排版</button>
      <button className="btn xs" onClick={copyText}>纯文本</button>
      <Menu
        trigger={<button className="btn xs"><Icon name="upload" size={12} />导出<Icon name="chevronDown" size={11} /></button>}
        items={[
          { label: '下载 Markdown (.md)', icon: 'file', onSelect: () => download('md') },
          { label: '下载 HTML', icon: 'file', onSelect: () => download('html') },
          { label: '下载纯文本 (.txt)', icon: 'file', onSelect: () => download('txt') },
        ]}
      />
    </div>
  )
}

