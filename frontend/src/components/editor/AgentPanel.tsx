import { useEffect, useRef, useState } from 'react'
import { PLATFORM_NAME, api, type Platform } from '../../lib/api'
import { AGENT_PHASES, AGENT_STATUS, type AgentProposal, type AgentRun } from '../../lib/writingAgent'
import { renderMarkdown } from '../../lib/markdown'
import { errorMessage } from '../toast'
import { Loading } from '../ui'

export default function AgentPanel({ documentId, active, available, beforeAction, adopt, onWorkspaceChange }: {
  documentId: string; active: boolean; available: boolean
  beforeAction: () => Promise<boolean>; adopt: (run: AgentRun) => Promise<AgentRun>
  onWorkspaceChange?: () => void
}) {
  const path = `/api/documents/${documentId}/agent`
  const [run, setRun] = useState<AgentRun | null>(null)
  const [proposal, setProposal] = useState<AgentProposal | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [pausing, setPausing] = useState(false)
  const [error, setError] = useState('')
  const [instruction, setInstruction] = useState('')
  const [platforms, setPlatforms] = useState<Platform[]>(['xiaohongshu', 'zhihu'])
  const mounted = useRef(false)
  const activeRef = useRef(active)
  const keepGoing = useRef(false)
  const busyRef = useRef(false)
  activeRef.current = active
  useEffect(() => { if (!active) keepGoing.current = false }, [active])
  function display(next: AgentRun | null) {
    if (!mounted.current) return
    setRun(next)
    if (next?.status === 'awaiting_outline') setProposal(structuredClone(next.state.proposal))
  }
  useEffect(() => {
    mounted.current = true
    const controller = new AbortController()
    api.get<AgentRun | null>(path, { signal: controller.signal }).then(next => {
      if (!mounted.current) return
      display(next)
      if (next) { setInstruction(next.state.instruction); setPlatforms(next.state.platforms) }
    }).catch(e => { if (!controller.signal.aborted && mounted.current) setError(errorMessage(e)) })
      .finally(() => { if (mounted.current) setLoading(false) })
    return () => { mounted.current = false; keepGoing.current = false; controller.abort() }
    // Reading progress never starts model work.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path])
  useEffect(() => {
    if (!run?.running || busy || !active) return
    const controller = new AbortController()
    const timer = window.setInterval(() => {
      api.get<AgentRun>(path, { signal: controller.signal }).then(display)
        .catch(e => { if (!controller.signal.aborted && mounted.current) setError(errorMessage(e)) })
    }, 2500)
    return () => { window.clearInterval(timer); controller.abort() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.running, busy, active, path])
  async function drive(initial: AgentRun) {
    let current = initial
    setPausing(false)
    keepGoing.current = true
    while (mounted.current && activeRef.current && keepGoing.current && (AGENT_PHASES.includes(current.status) || current.status === 'failed')) {
      current = await api.post<AgentRun>(`${path}/advance`, { run_id: current.id, revision: current.revision })
      display(current)
      if (current.status === 'failed' || current.running) break
    }
  }
  async function operate(task: () => Promise<void>, flush = true) {
    if (busyRef.current || run?.running) return
    busyRef.current = true
    setBusy(true); setError('')
    try {
      if (flush && !await beforeAction()) throw new Error('请先成功保存当前稿件，再执行 Agent。')
      if (mounted.current && activeRef.current) await task()
    } catch (e) {
      if (mounted.current) {
        setError(errorMessage(e))
        // A lost response may have completed its step; read progress before retrying.
        try { display(await api.get<AgentRun | null>(path)) } catch { /* retain the last checkpoint */ }
      }
    } finally {
      busyRef.current = false; keepGoing.current = false
      if (mounted.current) { setBusy(false); setPausing(false) }
    }
  }
  function start(restart = false) {
    void operate(async () => {
      const next = await api.post<AgentRun>(`${path}/start`, { instruction, platforms, restart })
      display(next); await drive(next)
    })
  }
  function confirm() {
    if (!run || !proposal) return
    void operate(async () => {
      const next = await api.post<AgentRun>(`${path}/confirm`, { run_id: run.id, revision: run.revision, proposal })
      onWorkspaceChange?.()
      display(next); await drive(next)
    })
  }
  function editProposal(changes: Partial<AgentProposal>) { setProposal(p => p ? { ...p, ...changes } : p) }
  const locked = busy || !!run?.running
  const settingsLocked = locked || (!!run && !['failed', 'completed'].includes(run.status))
  const state = run?.state
  const warnings = [...new Set([...(state?.warnings ?? []), ...(state?.drafts.flatMap(d => d.warnings) ?? []), ...(state?.review?.warnings ?? []), ...(state?.variants.flatMap(v => v.warnings) ?? [])])]
  if (loading) return <Loading rows={3} />
  return <div className="creation-workspace agent-workspace">
    <p className="small muted">先规划，你确认后连续起草、审稿并改编。候选稿单独保存，最后由你采用到正文。</p>
    {!available && <p className="notice warn small">真实创作需要配置写作模型。演示稿件可体验模板流程。</p>}
    <details className="agent-settings" open={!run || run.status === 'failed' || run.status === 'completed'}>
      <summary>创作要求与目标平台</summary>
      <label className="creation-field">这篇想怎么写<textarea aria-label="Agent 创作要求" rows={3} maxLength={2000} disabled={settingsLocked} value={instruction} onChange={e => setInstruction(e.target.value)} placeholder="例如：写给创业者，分析利润变化的机制，语气克制；缺资料先列出来。" /></label>
      <fieldset className="creation-fieldset" disabled={settingsLocked}><legend className="small">公众号母稿之外，还准备哪些版本</legend><div className="agent-platforms">{(['xiaohongshu', 'zhihu', 'toutiao', 'x'] as Platform[]).map(p => <label key={p}><input type="checkbox" checked={platforms.includes(p)} onChange={e => setPlatforms(e.target.checked ? [...platforms, p] : platforms.filter(v => v !== p))} />{PLATFORM_NAME[p]}</label>)}</div></fieldset>
      {run && <p className="tiny muted">改动要求后点「重新规划」；重试继续原任务。</p>}
    </details>
    {error && <p role="alert" className="notice bad">{error}</p>}
    {state?.error && <p role="alert" className="notice bad">{state.error}</p>}
    {run && <div className="agent-progress" role="status" aria-live="polite"><strong>{AGENT_STATUS[run.status] ?? run.status}</strong><span className="tiny muted">已起草 {state?.drafts.length ?? 0}/{state?.proposal?.sections.length ?? 0} 节 · 平台版本 {state?.variants.length ?? 0}/{state?.platforms.length ?? 0}{state?.model === 'fixture' ? ' · 演示模板' : ''}</span></div>}
    <div className="creation-actions">
      {!run && <button className="btn primary" disabled={locked || !available} onClick={() => start()}>整理素材并规划</button>}
      {run && (AGENT_PHASES.includes(run.status) || run.status === 'failed') && <button className="btn primary sm" disabled={locked || !available} onClick={() => void operate(() => drive(run))}>{run.status === 'failed' ? '重试当前步骤' : '继续执行'}</button>}
      {busy && <button className="btn sm" disabled={pausing} onClick={() => { keepGoing.current = false; setPausing(true) }}>{pausing ? '当前步骤完成后暂停' : '暂停后续步骤'}</button>}
      {!busy && run?.running && <span className="small muted">当前步骤执行中，等待进度更新…</span>}
      <button className="btn sm" disabled={locked} onClick={() => void operate(async () => { display(await api.get<AgentRun | null>(path)) }, false)}>刷新进度</button>
    </div>
    {run && AGENT_PHASES.includes(run.status) && !locked && <p className="tiny muted">已暂停，可从当前步骤继续。</p>}
    <p className="tiny muted">关闭面板或离开页面，会在当前步骤完成后暂停；重开后点「继续执行」。进度已保存，每次重试只处理当前步骤。</p>
    {run?.status === 'awaiting_outline' && proposal && <fieldset className="creation-fieldset" disabled={locked}>
      <h4>确认写作方向与大纲</h4>
      {(['title', 'audience', 'question', 'proposition'] as const).map(key => <label className="creation-field" key={key}>{({ title: '候选标题', audience: '读者', question: '要回答的问题', proposition: '核心判断' })[key]}<input maxLength={key === 'title' ? 200 : 2000} value={proposal[key]} onChange={e => editProposal({ [key]: e.target.value })} /></label>)}
      {proposal.gaps.length > 0 && <div className="notice warn small"><b>还缺哪些资料</b><ul>{proposal.gaps.map((gap, i) => <li key={i}>{gap}</li>)}</ul><p>可先去素材面板补齐后重新规划，也可保留待补充标记继续起草。</p></div>}
      {proposal.excerpts.length > 0 && <details className="creation-card"><summary>查看 Agent 选取的 {proposal.excerpts.length} 条原文摘录</summary>{proposal.excerpts.map(e => <div key={e.id}><p className="small"><b>{e.source_title}</b> · {e.fact}</p><blockquote>{e.quote}</blockquote></div>)}</details>}
      {proposal.sections.map((section, index) => <div className="creation-card" key={section.id}>
        <label className="creation-field">第 {index + 1} 节标题<input maxLength={200} value={section.title} onChange={e => editProposal({ sections: proposal.sections.map((s, i) => i === index ? { ...s, title: e.target.value } : s) })} /></label>
        <label className="creation-field">论证目标<textarea rows={2} maxLength={2000} value={section.goal} onChange={e => editProposal({ sections: proposal.sections.map((s, i) => i === index ? { ...s, goal: e.target.value } : s) })} /></label>
        <span className="tiny muted">约 {section.target_words} 字 · {section.evidence_ids.length} 条依据</span>
      </div>)}
      <p className="tiny muted">确认后还有 {proposal.sections.length + 1 + (state?.platforms.length ?? 0)} 个生成步骤，使用项目配置的模型与额度。确认会把当前创作规划更新为这份大纲。</p>
      <button className="btn primary sm" disabled={locked || !available} onClick={confirm}>确认大纲并连续起草</button>
    </fieldset>}
    {state?.draft_md && <details className="creation-card" open={run?.status === 'awaiting_adoption'}><summary>候选母稿</summary><div className="md agent-draft" dangerouslySetInnerHTML={{ __html: renderMarkdown(state.draft_md) }} /></details>}
    {state?.review && <details className="creation-card" open={run?.status === 'awaiting_adoption'}><summary>审稿发现 {state.review.output.issues?.length ?? 0} 项</summary>
      {!state.review.output.issues?.length && <p className="small muted">本次未提出替换建议，仍需你核对事实、来源与判断。</p>}
      {state.review.output.issues?.map((issue, i) => <div key={i} className="agent-review"><b>{issue.reason}</b><blockquote>{issue.quote}</blockquote><p className="small muted">建议：{issue.suggestion}</p></div>)}
      <p className="tiny muted">建议尚未自动应用。采用母稿后，可在创作规划的审稿步骤中逐段修改。</p>
    </details>}
    {state?.variants.map(variant => <details className="creation-card" key={variant.id}><summary>{PLATFORM_NAME[variant.platform]}候选版本</summary><div className="md agent-draft" dangerouslySetInnerHTML={{ __html: renderMarkdown(variant.output.content_md ?? '') }} /></details>)}
    {warnings.length > 0 && <details className="creation-card"><summary>生成提示与需核对事项（{warnings.length}）</summary>{warnings.map(w => <p className="notice warn small" key={w}>{w}</p>)}</details>}
    {run?.status === 'awaiting_adoption' && <div className="creation-actions"><button className="btn primary sm" disabled={locked} onClick={() => void operate(async () => display(await adopt(run)), false)}>采用母稿{state?.variants.length ? `和 ${state.variants.length} 个平台版本` : ''}（保存原稿快照）</button></div>}
    {run && !busy && !run.running && ['awaiting_outline', 'awaiting_adoption', 'failed', 'completed'].includes(run.status) && <button className="btn ghost sm" disabled={!available} onClick={() => start(true)}>重新规划</button>}
  </div>
}
