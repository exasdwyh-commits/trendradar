import { useEffect, useRef, useState } from 'react'
import { PLATFORM_NAME, api, type AIResult, type Capabilities, type DocumentFull, type Platform } from '../../lib/api'
import { ago } from '../../lib/format'
import { errorMessage, useToast } from '../toast'
import { Badge, Collapsible, Disclosure, IconButton, Loading, Menu, ModeBadge } from '../ui'
import { Icon, type IconName } from '../icons'
import { actionName, countWords, escapeHtml, REWRITE_LABEL, type Selection } from './editorUtils'

export default function AIPanel({ doc, caps, selection, onInsert, onReplaceSelection, onReplaceAll, onTitle, onThesis, reload, beforeAction }: {
  doc: DocumentFull; caps: Capabilities | null; selection: Selection
  onInsert: (t: string) => void; onReplaceSelection: (t: string) => void; onReplaceAll: (t: string, title?: string) => void
  onTitle: (t: string) => void; onThesis: (t: string) => void; reload: () => void
  beforeAction: () => Promise<boolean>
}) {
  const { toast } = useToast()
  const [busy, setBusy] = useState<string | null>(null)
  const [result, setResult] = useState<AIResult | null>(null)
  const [mode, setMode] = useState('concise')
  const [instruction, setInstruction] = useState('')
  const [sectionId, setSectionId] = useState<string>('')
  const [historyOpen, setHistoryOpen] = useState(false)
  const resultRef = useRef<HTMLDivElement>(null)
  useEffect(() => { if (result) resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }, [result])
  const demo = doc.data_mode === 'mock'
  const available = caps ? caps.model_available || demo : true
  const [sections, setSections] = useState<{ id: string; title: string }[]>([])
  useEffect(() => {
    api.get<{ plan?: { sections?: { id: string; title: string }[] } }>(`/api/documents/${doc.id}/workspace`)
      .then((w) => setSections(w.plan?.sections ?? []))
      .catch(() => undefined)
  }, [doc.id])

  async function run(action: string, options: Record<string, unknown> = {}) {
    setBusy(action)
    try {
      if (!await beforeAction()) return
      const reqOptions = sectionId ? { ...options, section_id: sectionId } : options
      const res = await api.post<AIResult>(`/api/documents/${doc.id}/ai/${action}`, reqOptions)
      setResult(res)
      reload()
    } catch (e) {
      toast(errorMessage(e), 'bad')
    } finally {
      setBusy(null)
    }
  }
  async function accept(res: AIResult, apply: () => void) {
    apply()
    api.patch(`/api/documents/${doc.id}/ai/${res.id}`, { accepted: true }).catch(() => undefined)
  }
  const actions: { id: string; label: string; icon: IconName; options?: Record<string, unknown>; wide?: boolean }[] = [
    { id: 'angles', label: '选题角度', icon: 'compass' },
    { id: 'outline', label: '大纲', icon: 'note' },
    { id: 'draft', label: `${PLATFORM_NAME[doc.target_platform]}初稿`, icon: 'file', options: { platform: doc.target_platform }, wide: true },
    { id: 'titles', label: '起标题', icon: 'spark' },
    { id: 'summary', label: '三句话摘要', icon: 'layers' },
  ]

  return (
    <div>
      {!available && (
        <div className="notice small" style={{ marginBottom: 12 }}>
          未配置写作模型（{caps?.writing_slot}）。在 <code>.env</code> 里设置 <code>WRITING_MODEL_*</code> 或 <code>ANALYSIS_MODEL_*</code> 后重启即可使用；演示素材构成的稿件可离线体验。
        </div>
      )}
      {demo && <div className="tiny muted" style={{ marginBottom: 10 }}>演示素材构成的稿件：AI 助手返回<b>模板输出</b>（标注「演示生成」），不代表真实模型质量。</div>}
      {doc.materials.length === 0 && <div className="tiny muted" style={{ marginBottom: 10 }}>还没有绑定素材。AI 只会使用素材和正文里的事实——先在「素材」页签添加，或直接开始写。</div>}

      {sections.length > 0 && (
        <div className="panel-section" style={{ marginBottom: 8 }}>
          <div className="panel-label"><Icon name="layers" size={12} />限定参考章节素材</div>
          <select className="input sm" value={sectionId} onChange={(e) => setSectionId(e.target.value)} style={{ width: '100%' }}>
            <option value="">全部素材与大纲</option>
            {sections.map((s, idx) => (
              <option key={s.id} value={s.id}>第 {idx + 1} 节：{s.title || '未命名章节'}</option>
            ))}
          </select>
        </div>
      )}

      <div className="panel-section">
        <div className="panel-label"><Icon name="sparkles" size={12} />从素材出发</div>
        <div className="ai-actions">
          {actions.map((a) => (
            <button key={a.id} type="button" className={`ai-action ${a.wide ? 'wide' : ''}`} disabled={!!busy || !available} onClick={() => run(a.id, a.options)}>
              {busy === a.id ? <span className="spinner" style={{ width: 13, height: 13 }} /> : <Icon name={a.icon} size={15} />}
              {busy === a.id ? '生成中…' : a.label}
            </button>
          ))}
        </div>
      </div>

      <div className="panel-section">
        <div className="panel-label"><Icon name="edit" size={12} />改写选中文字 {selection.text ? <span className="faint">（{countWords(selection.text)} 字）</span> : <span className="faint">（先在左侧选中一段）</span>}</div>
        <div className="row nowrap" style={{ gap: 6 }}>
          <Menu
            align="left"
            trigger={<button className="btn sm">{REWRITE_LABEL[mode] ?? mode}<Icon name="chevronDown" size={12} /></button>}
            items={Object.keys(caps?.rewrite_modes ?? REWRITE_LABEL).map((m) => ({ label: REWRITE_LABEL[m] ?? m, active: m === mode, hint: undefined, onSelect: () => setMode(m) }))}
          />
          {mode === 'custom' && <input className="input sm" placeholder="例如：把第二句改成反问" value={instruction} onChange={(e) => setInstruction(e.target.value)} style={{ flex: 1 }} />}
          <button className={`btn sm primary ${busy === 'rewrite' ? 'loading' : ''}`} disabled={!!busy || !available || !selection.text} onClick={() => run('rewrite', { selection: selection.text, mode, instruction: instruction || undefined })} style={{ marginLeft: 'auto' }}>改写</button>
        </div>
        {caps?.rewrite_modes?.[mode] && <div className="tiny faint" style={{ marginTop: 4 }}>{caps.rewrite_modes[mode]}</div>}
      </div>

      {result && (
        <div className="card pad ai-result" style={{ marginBottom: 12, scrollMarginTop: 8 }} ref={resultRef}>
          <div className="row between" style={{ marginBottom: 8 }}>
            <div className="row" style={{ gap: 6 }}>
              <b className="small">{actionName(result.action)}</b>
              <Badge tone={result.generated_by === 'fixture' ? 'warn' : 'good'} small>{result.generated_by === 'fixture' ? '演示生成' : result.model}</Badge>
            </div>
            <IconButton icon="x" tip="关闭" onClick={() => setResult(null)} />
          </div>
          {result.warnings.filter((w) => !w.startsWith('演示生成')).map((w) => <div key={w} className="notice warn small" style={{ marginBottom: 8 }}>{w}</div>)}
          <AIOutput result={result} onInsert={(t) => accept(result, () => onInsert(t))} onReplaceSelection={(t) => accept(result, () => onReplaceSelection(t))} onReplaceAll={(t, title) => accept(result, () => onReplaceAll(t, title))} onTitle={(t) => accept(result, () => onTitle(t))} onThesis={(t) => accept(result, () => onThesis(t))} hasSelection={!!selection.text} />
        </div>
      )}

      {doc.ai_actions.length > 0 && (
        <Disclosure size="sm" title="历史" hint={`${doc.ai_actions.length} 次`} open={historyOpen} onToggle={() => setHistoryOpen(!historyOpen)}>
          <div className="stack" style={{ gap: 6, padding: '4px 0 8px' }}>
            {doc.ai_actions.filter((a) => a.action !== 'section' && a.action !== 'review').map((a) => (
              <button key={a.id} className="history-row" onClick={() => setResult({ id: a.id, action: a.action, output: a.output, model: a.model, generated_by: a.generated_by, warnings: a.warnings })}>
                <span>{actionName(a.action)}{a.mode ? ` · ${REWRITE_LABEL[a.mode] ?? PLATFORM_NAME[a.mode as Platform] ?? a.mode}` : ''}</span>
                <span className="faint">{a.accepted ? '已采用 · ' : ''}{ago(a.created_at)}</span>
              </button>
            ))}
          </div>
        </Disclosure>
      )}
    </div>
  )
}

function AIOutput({ result, onInsert, onReplaceSelection, onReplaceAll, onTitle, onThesis, hasSelection }: {
  result: AIResult; onInsert: (t: string) => void; onReplaceSelection: (t: string) => void; onReplaceAll: (t: string, title?: string) => void; onTitle: (t: string) => void; onThesis: (t: string) => void; hasSelection: boolean
}) {
  const { toast } = useToast()
  const copyText = (t: string) => navigator.clipboard.writeText(t).then(() => toast('已复制', 'good')).catch(() => undefined)
  const out = result.output as Record<string, unknown>
  if (result.action === 'angles') {
    const angles = (out.angles as { title: string; angle: string; why_now: string; risk: string }[]) ?? []
    return (
      <div className="stack" style={{ gap: 8 }}>
        {angles.map((a) => (
          <div key={a.title} className="ai-item">
            <div style={{ fontWeight: 600 }}>{a.title}</div>
            {a.angle && <div className="small muted">{a.angle}</div>}
            <div className="tiny faint">{a.why_now && <>为什么现在：{a.why_now}　</>}{a.risk && <>风险：{a.risk}</>}</div>
            <div className="row" style={{ gap: 6, marginTop: 6 }}>
              <button className="btn xs" onClick={() => onTitle(a.title)}>设为标题</button>
              <button className="btn xs" onClick={() => onThesis(a.angle || a.title)}>设为核心判断</button>
              <button className="btn xs" onClick={() => onInsert(`## ${a.title}\n\n${a.angle}`)}>插入</button>
            </div>
          </div>
        ))}
      </div>
    )
  }
  if (result.action === 'outline') {
    return (
      <div>
        {out.thesis ? <div className="small" style={{ marginBottom: 8 }}><b>核心判断：</b>{String(out.thesis)} <button className="btn xs" onClick={() => onThesis(String(out.thesis))}>采用</button></div> : null}
        <pre className="ai-pre">{String(out.outline_md ?? '')}</pre>
        <div className="row" style={{ gap: 6 }}>
          <button className="btn sm primary" onClick={() => onInsert(String(out.outline_md ?? ''))}>插入到光标</button>
          <button className="btn sm" onClick={() => copyText(String(out.outline_md ?? ''))}><Icon name="copy" size={13} />复制</button>
        </div>
      </div>
    )
  }
  if (result.action === 'draft') {
    const text = String(out.content_md ?? '')
    return (
      <div>
        {out.title ? <div className="small" style={{ marginBottom: 6 }}><b>{String(out.title)}</b></div> : null}
        <pre className="ai-pre" style={{ maxHeight: 320 }}>{text}</pre>
        <div className="row" style={{ gap: 6 }}>
          <button className="btn sm primary" onClick={() => onReplaceAll(text, out.title ? String(out.title) : undefined)}>替换全文</button>
          <button className="btn sm" onClick={() => onInsert(text)}>插入到光标</button>
          <button className="btn sm" onClick={() => copyText(text)}><Icon name="copy" size={13} />复制</button>
        </div>
      </div>
    )
  }
  if (result.action === 'titles') {
    const titles = (out.titles as { title: string; subtitle: string; style: string }[]) ?? []
    return (
      <div className="stack" style={{ gap: 6 }}>
        {titles.map((t) => (
          <div key={t.title} className="row between ai-item nowrap">
            <div style={{ minWidth: 0 }}><div style={{ fontWeight: 600 }}>{t.title}</div>{t.subtitle && <div className="tiny muted">{t.subtitle}</div>}</div>
            <div className="row nowrap" style={{ gap: 6 }}>{t.style && <span className="tiny faint">{t.style}</span>}<button className="btn xs" onClick={() => onTitle(t.title)}>用这个</button></div>
          </div>
        ))}
      </div>
    )
  }
  if (result.action === 'rewrite') {
    const text = String(out.text ?? '')
    return (
      <div>
        <pre className="ai-pre">{text}</pre>
        <div className="row" style={{ gap: 6 }}>
          <button className="btn sm primary" disabled={!hasSelection} onClick={() => onReplaceSelection(text)}>替换选中</button>
          <button className="btn sm" onClick={() => onInsert(text)}>插入到光标</button>
          <button className="btn sm" onClick={() => copyText(text)}><Icon name="copy" size={13} />复制</button>
        </div>
      </div>
    )
  }
  if (result.action === 'variant') {
    return <pre className="ai-pre">{String(out.content_md ?? '')}</pre>
  }
  return <div className="small">{String(out.summary ?? JSON.stringify(out))}</div>
}

// ───────────────────────── 素材 ─────────────────────────

