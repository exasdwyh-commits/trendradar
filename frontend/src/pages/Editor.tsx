import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { renderMarkdown } from '../lib/markdown'
import {
  DOC_STATUS_NAME, PLATFORM_NAME, api,
  type Capabilities, type DocStatus, type DocumentFull, type Platform,
} from '../lib/api'
import { useFetch } from '../lib/hooks'
import { ago } from '../lib/format'
import { Badge, Disclosure, ErrorNotice, IconButton, Loading, Menu, ModeBadge, Segmented, useStored } from '../components/ui'
import { Icon } from '../components/icons'
import { errorMessage, useToast } from '../components/toast'
import CreationPanel, { type Workspace } from '../components/CreationPanel'

import AIPanel from '../components/editor/AIPanel'
import MaterialsPanel from '../components/editor/MaterialsPanel'
import VersionsPanel from '../components/editor/VersionsPanel'
import VariantsPanel from '../components/editor/VariantsPanel'
import PublishPanel from '../components/editor/PublishPanel'
import AgentPanel from '../components/editor/AgentPanel'
import type { AgentRun } from '../lib/writingAgent'
import {
  countWords,
  escapeHtml,
  LANES,
  STATUS_ICON,
  TABS,
  type Selection,
  type Tab,
  type View,
} from '../components/editor/editorUtils'

// Keep writes ordered even when the editor unmounts and opens the same document again.
const documentSaveQueues = new Map<string, Promise<unknown>>()

export default function Editor() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { toast } = useToast()
  const { data: doc, error, reload } = useFetch<DocumentFull>(id ? `/api/documents/${id}` : null)
  const { data: caps } = useFetch<Capabilities>('/api/studio/capabilities')

  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [thesis, setThesis] = useState('')
  const [loaded, setLoaded] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [savedAt, setSavedAt] = useState<Date | null>(null)
  const [view, setView] = useStored<View>('ui.editor.view', typeof window !== 'undefined' && window.innerWidth < 1400 ? 'edit' : 'split')
  const [tab, setTab] = useStored<Tab>('ui.editor.tab', 'ai')
  const [creationOpened, setCreationOpened] = useState(tab === 'creation')
  const [agentOpened, setAgentOpened] = useState(tab === 'agent')
  const [applyingAgent, setApplyingAgent] = useState(false)
  const [workspaceEpoch, setWorkspaceEpoch] = useState(0)
  const [panelOpen, setPanelOpen] = useStored<boolean>('ui.editor.panel', true)
  const [selection, setSelection] = useState<Selection>({ start: 0, end: 0, text: '' })
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const dirtyRef = useRef(false)
  const latestRef = useRef({ id, title, content, thesis })
  latestRef.current = { id, title, content, thesis }
  dirtyRef.current = dirty
  const pendingSaves = useRef(0)
  const mounted = useRef(false)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])

  // hydrate local state once per document (server → local), keep local edits otherwise
  useEffect(() => {
    if (doc && loaded !== doc.id) {
      let draft: { title: string; content: string; thesis: string } | null = null
      try {
        const raw = localStorage.getItem(`draft.${doc.id}`)
        const saved = raw ? JSON.parse(raw) : null
        if (saved && ['title', 'content', 'thesis'].every((key) => typeof saved[key] === 'string')) draft = saved
      } catch { /* The server copy remains available when storage is disabled. */ }
      const recovered = !!draft && (draft.title !== doc.title || draft.content !== doc.content_md || draft.thesis !== doc.thesis)
      setTitle(recovered ? draft!.title : doc.title)
      setContent(recovered ? draft!.content : doc.content_md)
      setThesis(recovered ? draft!.thesis : doc.thesis)
      setLoaded(doc.id)
      setDirty(recovered)
      setSavedAt(null)
      if (recovered) toast('已恢复本地未保存草稿，将自动保存', 'info')
    }
  }, [doc, loaded, toast])

  useEffect(() => {
    if (!id || loaded !== id || !dirty) return
    try { localStorage.setItem(`draft.${id}`, JSON.stringify({ title, content, thesis })) }
    catch { toast('本地草稿备份不可用，请保存后再离开页面', 'warn') }
  }, [id, loaded, dirty, title, content, thesis, toast])

  useEffect(() => {
    function protect(event: BeforeUnloadEvent) {
      if (!dirtyRef.current && pendingSaves.current === 0) return
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', protect)
    return () => window.removeEventListener('beforeunload', protect)
  }, [])

  const persist = useCallback((mode: 'autosave' | 'manual' | 'ai', note?: string, override?: Partial<{ title: string; content_md: string; thesis: string }>) => {
    if (!id || loaded !== id) return Promise.resolve(false)
    const body = { title, content_md: content, thesis, ...override, save_mode: mode, note }
    pendingSaves.current += 1
    setSaving(true)
    const request = (documentSaveQueues.get(id) ?? Promise.resolve()).then(async () => {
      try {
        await api.patch<DocumentFull>(`/api/documents/${id}`, body)
        const latest = latestRef.current
        const same = latest.id === id && latest.title === body.title && latest.content === body.content_md && latest.thesis === body.thesis
        if (same) {
          try {
            const draft = JSON.parse(localStorage.getItem(`draft.${id}`) ?? 'null')
            if (draft && draft.title === body.title && draft.content === body.content_md && draft.thesis === body.thesis) localStorage.removeItem(`draft.${id}`)
          } catch { /* optional local backup */ }
          if (mounted.current) { setSavedAt(new Date()); setDirty(false); dirtyRef.current = false }
        }
        if (mounted.current && latest.id === id) {
          if (mode !== 'autosave') reload()
          if (mode === 'manual') toast('已保存为新版本', 'good')
        }
        return true
      } catch (e) {
        if (mounted.current && latestRef.current.id === id) toast(errorMessage(e), 'bad')
        return false
      } finally {
        pendingSaves.current -= 1
        if (mounted.current) setSaving(pendingSaves.current > 0)
      }
    })
    documentSaveQueues.set(id, request)
    void request.then(() => { if (documentSaveQueues.get(id) === request) documentSaveQueues.delete(id) })
    return request
  }, [id, loaded, title, content, thesis, reload, toast])

  // autosave 1.5s after the last keystroke
  useEffect(() => {
    if (!dirty) return
    dirtyRef.current = true
    const t = setTimeout(() => { if (dirtyRef.current) persist('autosave') }, 1500)
    return () => clearTimeout(t)
  }, [dirty, title, content, thesis, persist])

  // Cmd/Ctrl+S = named version, Cmd/Ctrl+\ = toggle side panel
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') { e.preventDefault(); persist('manual', '手动保存') }
      if ((e.metaKey || e.ctrlKey) && e.key === '\\') { e.preventDefault(); setPanelOpen((o) => !o) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [persist, setPanelOpen])

  const wordCount = useMemo(() => countWords(content), [content])
  const previewHtml = useMemo(() => renderMarkdown(content || ''), [content])

  function edit(next: string) { setContent(next); setDirty(true) }
  function captureSelection() {
    const el = textareaRef.current
    if (!el) return
    setSelection({ start: el.selectionStart, end: el.selectionEnd, text: el.value.slice(el.selectionStart, el.selectionEnd) })
  }
  function insertAtCursor(text: string) {
    const el = textareaRef.current
    const pos = el ? el.selectionStart : content.length
    const glue = pos > 0 && content[pos - 1] !== '\n' ? '\n\n' : ''
    const next = content.slice(0, pos) + glue + text + '\n' + content.slice(pos)
    edit(next)
    setView((v) => (v === 'preview' ? 'split' : v))
  }
  function replaceSelection(text: string) {
    if (selection.end <= selection.start) { insertAtCursor(text); return }
    edit(content.slice(0, selection.start) + text + content.slice(selection.end))
    setSelection({ start: selection.start, end: selection.start + text.length, text })
  }
  function replaceAll(text: string, newTitle?: string) {
    if (!window.confirm('用生成内容替换整篇正文？当前版本会先保存为快照。')) return
    const baseline = latestRef.current.content
    persist('autosave').then(async (flushed) => {
      if (!flushed) return
      const saved = await persist('ai', '应用 AI 初稿前的快照')
      if (!saved) return
      if (latestRef.current.content !== baseline) { toast('保存期间正文已改变，请重新检查候选稿后再应用', 'warn'); return }
      setContent(text)
      if (newTitle) setTitle(newTitle)
      setDirty(true)
    })
  }
  async function changeStatus(status: DocStatus) {
    if (!await persist('autosave')) return
    if (status === 'ready') {
      const workspace = await api.get<Workspace>(`/api/documents/${id}/workspace`)
      const pending = workspace.checks.filter((check) => !check.ok)
      if (pending.length && !window.confirm(`发布前还有 ${pending.length} 项需要人工核对：\n${pending.map((c) => c.label).join('\n')}\n\n仍将状态标记为待发布？`)) {
        setCreationOpened(true); setTab('creation'); setPanelOpen(true)
        return
      }
    }
    await api.patch(`/api/documents/${id}`, { status, save_mode: 'autosave' })
    reload()
    toast(`状态已改为「${DOC_STATUS_NAME[status]}」`, 'good')
  }
  async function changePlatform(platform: Platform) {
    await api.patch(`/api/documents/${id}`, { target_platform: platform, save_mode: 'autosave' })
    reload()
  }
  function openTab(t: Tab) {
    if (t === 'creation') setCreationOpened(true)
    if (t === 'agent') setAgentOpened(true)
    if (panelOpen && tab === t) setPanelOpen(false)
    else { setTab(t); setPanelOpen(true) }
  }

  async function beforeAgentAction(): Promise<boolean> {
    try {
      if (localStorage.getItem(`creation.${id}`)) {
        toast('请先在创作规划中保存未保存的修改，再执行 Agent', 'warn')
        return false
      }
    } catch { /* optional local backup */ }
    return persist('autosave')
  }

  async function adoptAgent(run: AgentRun): Promise<AgentRun> {
    setApplyingAgent(true)
    try {
      if (!await beforeAgentAction()) throw new Error('请先成功保存当前稿件与规划，再采用候选稿。')
      const result = await api.post<AgentRun>(`/api/documents/${id}/agent/adopt`, { run_id: run.id, revision: run.revision })
      if (mounted.current && latestRef.current.id === id) {
        setContent(result.state.draft_md)
        setTitle(result.state.proposal?.title || title)
        setThesis(result.state.proposal?.proposition || '')
        setDirty(false); dirtyRef.current = false; setSavedAt(new Date())
        setWorkspaceEpoch(v => v + 1)
        try { localStorage.removeItem(`draft.${id}`) } catch { /* optional local backup */ }
        reload(); toast('已采用 Agent 母稿与平台版本，原稿快照已保留', 'good')
      }
      return result
    } finally { if (mounted.current) setApplyingAgent(false) }
  }

  if (error) return <ErrorNotice error={error} />
  if (!doc) return <Loading rows={4} />

  const saveState = saving ? '保存中…' : dirty ? '未保存' : savedAt ? `已保存 ${savedAt.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })}` : `v${doc.current_version}`
  const tabCount: Record<Tab, number> = { agent: 0, creation: 0, ai: doc.ai_actions.length, materials: doc.materials.length, versions: doc.versions.length, variants: doc.variants.length, publish: doc.publications.length }

  return (
    <div className="editor-shell">
      <div className="editor-top">
        <div className="left">
          <IconButton icon="arrowLeft" tip="返回创作列表" tipSide="bottom" onClick={() => navigate('/studio')} />
          <input className="editor-title" disabled={applyingAgent} value={title} placeholder="标题" onChange={(e) => { setTitle(e.target.value); setDirty(true) }} />
        </div>
        <div className="right">
          <ModeBadge mode={doc.data_mode} small />
          <Menu
            trigger={<button className="btn sm"><Icon name={STATUS_ICON[doc.status]} size={13} />{DOC_STATUS_NAME[doc.status]}<Icon name="chevronDown" size={12} /></button>}
            items={(Object.keys(DOC_STATUS_NAME) as DocStatus[]).map((s) => ({ label: DOC_STATUS_NAME[s], icon: STATUS_ICON[s], active: s === doc.status, onSelect: () => changeStatus(s) }))}
          />
          <Menu
            trigger={<button className="btn sm" title="目标平台（影响初稿的长度与结构）">{PLATFORM_NAME[doc.target_platform]}<Icon name="chevronDown" size={12} /></button>}
            items={(Object.keys(PLATFORM_NAME) as Platform[]).map((p) => ({ label: PLATFORM_NAME[p], active: p === doc.target_platform, onSelect: () => changePlatform(p) }))}
          />
          <Segmented<View>
            small value={view} onChange={setView}
            options={[{ value: 'edit', label: '编辑', icon: 'edit' }, { value: 'split', label: '分栏', icon: 'split' }, { value: 'preview', label: '预览', icon: 'eye' }]}
          />
          {view === 'preview' && <span className={`save-state hide-md ${dirty ? 'dirty' : ''}`}>{wordCount} 字 · {saveState}</span>}
          <button className={`btn sm ${saving ? 'loading' : ''}`} onClick={() => persist('manual', window.prompt('版本备注（可选）', '') ?? undefined)} title="⌘/Ctrl+S"><Icon name="save" size={13} />保存版本</button>
          <IconButton icon="panel" tip={panelOpen ? '收起侧栏 (⌘\\)' : '展开侧栏 (⌘\\)'} tipSide="left" active={panelOpen} onClick={() => setPanelOpen(!panelOpen)} />
        </div>
      </div>

      <div className="editor-body">
        <div className={`editor-panes ${view}`}>
          {view !== 'preview' && (
            <div className="editor-pane">
              <div className="editor-toolbar">
                <input className="thesis-input" disabled={applyingAgent} value={thesis} placeholder="核心判断（一句话：这篇文章要证明什么）" onChange={(e) => { setThesis(e.target.value); setDirty(true) }} />
              </div>
              <textarea
                ref={textareaRef}
                className="editor-textarea"
                disabled={applyingAgent}
                value={content}
                onChange={(e) => edit(e.target.value)}
                onSelect={captureSelection}
                onKeyUp={captureSelection}
                onMouseUp={captureSelection}
                placeholder={'用 Markdown 写作。## 二级标题、> 引用、- 列表。\n选中一段文字后可在右侧「AI 助手」里改写。'}
                spellCheck={false}
              />
              <div className="editor-status tiny muted">
                <span>{selection.text ? `已选中 ${countWords(selection.text)} 字` : '未选中文字'}</span>
                <span className="faint">自动保存 · ⌘S 保存版本 · ⌘\ 侧栏</span>
                <span style={{ marginLeft: 'auto' }} className={dirty ? 'save-state dirty' : 'save-state'}>{wordCount} 字 · {saveState}</span>
              </div>
            </div>
          )}
          {view !== 'edit' && (
            <div className="editor-pane preview">
              <article className="md preview-article" dangerouslySetInnerHTML={{ __html: `${/^\s*# /.test(content) ? '' : `<h1>${escapeHtml(title || '未命名稿件')}</h1>`}${previewHtml}` }} />
            </div>
          )}
        </div>

        <aside className="editor-side">
          <div className="side-rail">
            {TABS.map((t) => (
              <button key={t.id} type="button" className={`iconbtn ${panelOpen && tab === t.id ? 'active' : ''}`} data-tip={t.label} data-tip-side="left" aria-label={t.label} onClick={() => openTab(t.id)}>
                <Icon name={t.icon} size={17} />
                {tabCount[t.id] > 0 && <span className="n">{tabCount[t.id]}</span>}
              </button>
            ))}
            <span className="grow" />
          </div>
          <div className={`side-panel ${tab === 'creation' || tab === 'agent' ? 'creation-side' : ''} ${panelOpen ? 'open' : ''}`}>
            <div className="side-panel-inner">
              <div className="side-panel-head">
                <h3><Icon name={TABS.find((t) => t.id === tab)?.icon ?? 'sparkles'} size={14} style={{ marginRight: 6, color: 'var(--accent)' }} />{TABS.find((t) => t.id === tab)?.label}</h3>
                <IconButton icon="x" tip="收起" tipSide="left" onClick={() => setPanelOpen(false)} />
              </div>
              <div className="side-panel-body">
                {agentOpened && <div hidden={tab !== 'agent'}><AgentPanel key={doc.id} documentId={doc.id} active={tab === 'agent' && panelOpen}
                  available={!!caps?.model_available || doc.data_mode === 'mock'} beforeAction={beforeAgentAction} adopt={adoptAgent}
                  onWorkspaceChange={() => setWorkspaceEpoch(v => v + 1)} /></div>}
                {creationOpened && <div hidden={tab !== 'creation'}><CreationPanel key={`${doc.id}-${workspaceEpoch}`} doc={doc} content={content} reload={reload}
                  beforeAction={() => persist('autosave')} onReplaceAll={replaceAll}
                  onReviewReplace={async (baseline, quote, suggestion) => {
                    if (latestRef.current.content !== baseline || baseline.split(quote).length !== 2) {
                      toast('原文已变化或存在多处相同段落，请重新审稿或手动定位修改', 'warn'); return false
                    }
                    if (!await persist('ai', '采用审稿建议前的快照')) return false
                    if (latestRef.current.content !== baseline) { toast('正文已变化，请重新审稿', 'warn'); return false }
                    edit(baseline.replace(quote, () => suggestion)); return true
                  }} /></div>}
                {tab === 'ai' && (
                  <AIPanel
                    doc={doc} caps={caps} selection={selection}
                    onInsert={insertAtCursor} onReplaceSelection={replaceSelection} onReplaceAll={replaceAll}
                    onTitle={(t) => { setTitle(t); setDirty(true) }} onThesis={(t) => { setThesis(t); setDirty(true) }}
                    reload={reload} beforeAction={() => persist('autosave')}
                  />
                )}
                {tab === 'materials' && <MaterialsPanel doc={doc} reload={reload} onInsert={insertAtCursor} />}
                {tab === 'versions' && <VersionsPanel doc={doc} content={content} reload={reload} beforeAction={() => persist('autosave')} onRestored={(d) => { setContent(d.content_md); setTitle(d.title); setDirty(false); try { localStorage.removeItem(`draft.${d.id}`) } catch { /* optional backup */ } }} />}
                {tab === 'variants' && <VariantsPanel doc={doc} reload={reload} content={content} beforeAction={() => persist('autosave')} />}
                {tab === 'publish' && <PublishPanel doc={doc} reload={reload} navigate={navigate} />}
              </div>
            </div>
          </div>
        </aside>
      </div>
    </div>
  )
}

// ───────────────────────── AI 助手 ─────────────────────────
