import { useEffect, useState } from 'react'
import { api, type DocumentFull } from '../lib/api'
import { renderMarkdown } from '../lib/markdown'
import { errorMessage, useToast } from './toast'
import { Loading } from './ui'

export interface Section {
  id: string; title: string; goal: string; evidence_ids: string[]; target_words: number; content_md: string
}
export interface Plan {
  audience: string; question: string; proposition: string; unique_angle: string; counterargument: string
  gaps: string; author_notes: string; style: string; examples: string; forbidden: string
  article_type: string; target_words: number; sections: Section[]; outline_confirmed: boolean
}
interface Excerpt {
  id: string; material_id: string; fact: string; quote: string; note: string; stance: string
  source_title: string; source_url?: string; source_date?: string; stale: boolean
}
export interface Workspace {
  plan: Plan; revision: number; excerpts: Excerpt[]; checks: { id: string; ok: boolean; label: string; details?: string[] }[]
}
interface Proposal {
  id: string; section_id?: string; output: { content_md?: string; issues?: { quote: string; reason: string; suggestion: string }[] }
  model: string; warnings: string[]; input_scope: { quote_characters: number; body_characters: number; evidence_ids: string[] }
}
type Step = 'plan' | 'evidence' | 'outline' | 'review'
const STEPS: { id: Step; label: string }[] = [
  { id: 'plan', label: '1 立项' }, { id: 'evidence', label: '2 证据' }, { id: 'outline', label: '3 分节写作' }, { id: 'review', label: '4 审稿' },
]
const FIELDS: [keyof Pick<Plan, 'audience' | 'question' | 'proposition' | 'unique_angle' | 'counterargument' | 'gaps' | 'author_notes'>, string, string][] = [
  ['audience', '给谁看', '读者身份、已有知识与关心的事'], ['question', '这篇回答什么', '提出一个具体问题'],
  ['proposition', '核心判断', '用一句话写清你的结论'], ['unique_angle', '你的独特角度', '相比新闻复述，多提供什么判断'],
  ['counterargument', '反方与边界', '什么情况会推翻这个判断'], ['gaps', '还缺哪些资料', '需补充的事实、口径或案例'],
  ['author_notes', '我的观察与经验', '你的经验、判断与例子；模型会区分事实与判断'],
]
export default function CreationPanel({ doc, content, beforeAction, onReplaceAll, onReviewReplace, reload }: {
  doc: DocumentFull; content: string; beforeAction: () => Promise<boolean>; onReplaceAll: (text: string) => void
  onReviewReplace: (baseline: string, quote: string, suggestion: string) => Promise<boolean>; reload: () => void
}) {
  const { toast } = useToast()
  const path = `/api/documents/${doc.id}/workspace`
  const backupKey = `creation.${doc.id}`
  const [state, setState] = useState<Workspace | null>(null)
  const [plan, setPlan] = useState<Plan | null>(null)
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [step, setStep] = useState<Step>('plan')
  const [materialId, setMaterialId] = useState(doc.materials[0]?.id ?? '')
  const [quote, setQuote] = useState('')
  const [fact, setFact] = useState('')
  const [note, setNote] = useState('')
  const [stance, setStance] = useState('support')
  const [candidate, setCandidate] = useState<Proposal | null>(null)
  const [assembled, setAssembled] = useState('')
  const [review, setReview] = useState<Proposal | null>(null)
  const [baseline, setBaseline] = useState('')
  const material = doc.materials.find((m) => m.id === materialId)

  useEffect(() => {
    let alive = true
    api.get<Workspace>(path).then((next) => {
      if (!alive) return
      setState(next); setPlan(next.plan)
      try {
        const draft = JSON.parse(localStorage.getItem(backupKey) ?? 'null')
        if (draft?.plan && typeof draft.revision === 'number') {
          setPlan(draft.plan); setState({ ...next, revision: draft.revision }); setDirty(true)
          toast('已恢复未保存的创作规划。若服务器已有新版本，保存时会提醒刷新。', 'info')
        }
      } catch { /* server copy stays available */ }
    }).catch((e) => { if (alive) setError(errorMessage(e)) })
    return () => { alive = false }
  }, [path, backupKey, toast])
  useEffect(() => {
    if (!dirty || !plan || !state) return
    try { localStorage.setItem(backupKey, JSON.stringify({ plan, revision: state.revision })) }
    catch { setError('规划本地备份不可用，请先保存再离开。') }
  }, [dirty, plan, state, backupKey])
  useEffect(() => {
    const protect = (event: BeforeUnloadEvent) => { if (dirty || busy) { event.preventDefault(); event.returnValue = '' } }
    window.addEventListener('beforeunload', protect)
    return () => window.removeEventListener('beforeunload', protect)
  }, [dirty, busy])

  function accept(next: Workspace) {
    setState(next); setPlan(next.plan); setDirty(false); setAssembled('')
    try { localStorage.removeItem(backupKey) } catch { /* optional backup */ }
  }
  async function run(label: string, task: () => Promise<void>) {
    if (busy) return
    setBusy(label); setError('')
    try { await task() } catch (e) { setError(errorMessage(e)); toast(errorMessage(e), 'bad') }
    finally { setBusy('') }
  }
  function change<K extends keyof Plan>(key: K, value: Plan[K]) {
    setPlan((p) => p ? { ...p, [key]: value, outline_confirmed: key === 'sections' ? p.outline_confirmed : false } : p)
    setDirty(true); setAssembled('')
  }
  function sectionChange(id: string, changes: Partial<Section>) {
    if (plan) change('sections', plan.sections.map((s) => s.id === id ? { ...s, ...changes } : s))
  }
  async function save() {
    if (!state || !plan) return
    const { outline_confirmed: _confirmed, ...changes } = plan
    accept(await api.patch<Workspace>(path, { revision: state.revision, changes }))
    toast('规划已保存；正文保持原样', 'good')
  }
  if (!state || !plan) return error ? <div role="alert" className="notice bad">{error}<button className="btn sm" onClick={() => window.location.reload()}>重新加载</button></div> : <Loading rows={4} />
  const saved = !dirty && !busy
  return <div className="creation-workspace">
    <nav className="creation-steps" aria-label="创作步骤">{STEPS.map((s) => <button type="button" key={s.id} className={step === s.id ? 'active' : ''} onClick={() => setStep(s.id)}>{s.label}</button>)}</nav>
    <div className="creation-savebar"><span className="tiny muted">{dirty ? '规划未保存 · 已本地备份' : `规划 v${state.revision} · ${plan.outline_confirmed ? '大纲已确认' : '大纲待确认'}`}</span><button className="btn sm" disabled={!dirty || !!busy} onClick={() => run('保存规划', save)}>保存规划</button></div>
    {error && <div className="notice bad" role="alert">{error}<button className="btn sm" disabled={!!busy} onClick={() => run('刷新', async () => { if (!dirty || window.confirm('刷新将丢弃本地未保存的规划，读取服务器最新版本。')) accept(await api.get<Workspace>(path)) })}>刷新规划</button></div>}
    {busy && <p className="tiny" role="status">{busy}… 请稍候</p>}
    <fieldset disabled={!!busy} className="creation-fieldset">
      {step === 'plan' && <>
        <p className="tiny muted">先确定要回答的问题，再围绕证据写作。多篇素材可在「素材」栏绑定到同一稿件。</p>
        {FIELDS.map(([key, label, placeholder]) => <label className="creation-field" key={key}>{label}<textarea rows={key === 'author_notes' ? 4 : 2} value={plan[key]} placeholder={placeholder} onChange={(e) => change(key, e.target.value)} /></label>)}
        <details className="creation-card"><summary>写作偏好与篇幅</summary>
          <label className="creation-field">文章类型<input value={plan.article_type} onChange={(e) => change('article_type', e.target.value)} /></label>
          <label className="creation-field">目标字数<input type="number" min={100} max={20000} value={plan.target_words} onChange={(e) => change('target_words', +e.target.value)} /></label>
          {(['style', 'examples', 'forbidden'] as const).map((key, i) => <label className="creation-field" key={key}>{['我的语气与风格', '喜欢的表达示例', '不要使用的表达'][i]}<textarea rows={3} value={plan[key]} onChange={(e) => change(key, e.target.value)} /></label>)}
        </details>
      </>}
      {step === 'evidence' && <>
        <p className="tiny muted">复制素材中的原文；你的推断写在备注。摘录会保留来源与日期，资料变化时会提示重新核对。</p>
        {!doc.materials.length ? <p>先到「素材」栏绑定一篇资料。</p> : <>
          <label className="creation-field">选择资料<select value={materialId} onChange={(e) => { setMaterialId(e.target.value); setQuote('') }}>{doc.materials.map((m) => <option key={m.id} value={m.id}>{m.title}</option>)}</select></label>
          <details className="creation-card" open><summary>查看原文 · 可选中文字</summary><pre className="creation-source" onMouseUp={() => { const selected = window.getSelection()?.toString(); if (selected) setQuote(selected) }}>{material?.content || material?.quote || material?.summary || '素材暂无正文'}</pre></details>
          <label className="creation-field">这条证据说明什么<input value={fact} maxLength={1000} onChange={(e) => setFact(e.target.value)} /></label>
          <label className="creation-field">原文摘录<textarea rows={4} value={quote} maxLength={6000} onChange={(e) => setQuote(e.target.value)} /></label>
          <label className="creation-field">个人备注<textarea rows={2} value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} /></label>
          <label className="creation-field">立场<select value={stance} onChange={(e) => setStance(e.target.value)}><option value="support">支持判断</option><option value="counter">反方证据</option><option value="context">背景资料</option></select></label>
          <button className="btn primary sm" disabled={!quote.trim() || !fact.trim()} onClick={() => run('保存摘录', async () => { await api.post(`${path}/excerpts`, { material_id: materialId, fact, quote, note, stance }); const next = await api.get<Workspace>(path); setState((s) => s ? { ...s, excerpts: next.excerpts, checks: next.checks } : next); setFact(''); setQuote(''); setNote(''); toast('摘录已保存', 'good') })}>保存证据摘录</button>
        </>}
        {state.excerpts.map((item) => <article className="creation-card" key={item.id}><strong>{item.fact}</strong><span className="tiny muted"> · {{ support: '支持', counter: '反方', context: '背景' }[item.stance]}</span>{item.stale && <p className="notice warn">来源已变化或解绑，请核对后重新摘录</p>}<blockquote>{item.quote}</blockquote><p className="tiny muted">{item.source_url && /^https?:\/\//.test(item.source_url) ? <a href={item.source_url} target="_blank" rel="noreferrer">{item.source_title}</a> : item.source_title} · {item.source_date || '日期未提供'}</p>{item.note && <p className="tiny">我的备注：{item.note}</p>}<button className="btn sm" disabled={!saved} onClick={() => run('移除摘录', async () => { if (window.confirm('移除这条摘录及其章节关联？大纲需重新确认。')) accept(await api.del<Workspace>(`${path}/excerpts/${item.id}?revision=${state.revision}`)) })}>移除</button></article>)}
      </>}
      {step === 'outline' && <>
        <p className="tiny muted">大纲独立于正文。先保存、确认结构，再按节生成；采用候选稿后可组装为母稿。生成和审稿使用 MiMo。</p>
        {plan.sections.map((section, index) => <article className="creation-card" key={section.id}>
          <div className="creation-section-head"><strong>第 {index + 1} 节</strong><div><button className="btn sm" disabled={!index} aria-label={`上移第${index + 1}节`} onClick={() => { const next = [...plan.sections]; [next[index - 1], next[index]] = [next[index], next[index - 1]]; change('sections', next) }}>↑</button><button className="btn sm" disabled={index === plan.sections.length - 1} aria-label={`下移第${index + 1}节`} onClick={() => { const next = [...plan.sections]; [next[index + 1], next[index]] = [next[index], next[index + 1]]; change('sections', next) }}>↓</button><button className="btn sm" onClick={() => { if (window.confirm('删除本节大纲与已保存的分节正文？母稿不受影响。')) change('sections', plan.sections.filter((s) => s.id !== section.id)) }}>移除</button></div></div>
          <label className="creation-field">章节标题<input value={section.title} maxLength={200} onChange={(e) => sectionChange(section.id, { title: e.target.value })} /></label>
          <label className="creation-field">本节要证明什么<textarea rows={2} value={section.goal} maxLength={2000} onChange={(e) => sectionChange(section.id, { goal: e.target.value })} /></label>
          <label className="creation-field">本节目标字数<input type="number" min={50} max={5000} value={section.target_words} onChange={(e) => sectionChange(section.id, { target_words: +e.target.value })} /></label>
          <div className="tiny muted">选择本节证据 · {section.evidence_ids.length} 条</div>
          {state.excerpts.map((item) => <label className="creation-evidence-option" key={item.id}><input type="checkbox" checked={section.evidence_ids.includes(item.id)} disabled={!!item.stale} onChange={(e) => sectionChange(section.id, { evidence_ids: e.target.checked ? [...section.evidence_ids, item.id] : section.evidence_ids.filter((id) => id !== item.id) })} />{item.fact}{item.stale ? '（需核对）' : ''}</label>)}
          <label className="creation-field">分节正文（可手动编辑）<textarea rows={5} value={section.content_md} placeholder="候选稿经你采用后存入这里" onChange={(e) => sectionChange(section.id, { content_md: e.target.value })} /></label>
          <button className="btn sm" disabled={!saved || !plan.outline_confirmed} onClick={() => run('生成本节候选稿', async () => { setCandidate(await api.post<Proposal>(`${path}/sections/${section.id}/generate`, { revision: state.revision })); reload() })}>{section.content_md ? '重新生成本节' : '生成本节'}</button>
        </article>)}
        <div className="creation-actions"><button className="btn sm" disabled={plan.sections.length >= 20} onClick={() => change('sections', [...plan.sections, { id: crypto.randomUUID(), title: `章节 ${plan.sections.length + 1}`, goal: '', evidence_ids: [], target_words: 400, content_md: '' }])}>＋ 添加章节</button><button className="btn primary sm" disabled={!saved || !plan.sections.length || plan.outline_confirmed} onClick={() => run('确认大纲', async () => accept(await api.post<Workspace>(`${path}/confirm`, { revision: state.revision })))}>确认大纲</button><button className="btn sm" disabled={!saved || !plan.outline_confirmed || !plan.sections.length || plan.sections.some((s) => !s.content_md.trim())} onClick={() => run('组装预览', async () => { const next = await api.post<{ content_md: string }>(`${path}/assemble`, { revision: state.revision }); setAssembled(next.content_md) })}>预览组装母稿</button></div>
        {doc.ai_actions.some((a) => a.action === 'section') && <details className="creation-card"><summary>分节候选历史（可重新打开）</summary>{doc.ai_actions.filter((a) => a.action === 'section').map((a) => <button className="history-row" key={a.id} onClick={() => setCandidate({ ...(a.output as unknown as Proposal), id: a.id })}>{a.model} · {a.accepted ? '已采用' : '未采用'} · {a.created_at}</button>)}</details>}
        {candidate && <article className="creation-card creation-candidate"><h4>本节候选稿 · {candidate.model}</h4><p className="tiny muted">输入 {candidate.input_scope.evidence_ids.length} 条证据、{candidate.input_scope.quote_characters} 字符原文</p>{candidate.warnings.map((warning) => <p className="notice warn" key={warning}>{warning}</p>)}<div className="creation-comparison"><div><strong>当前分节</strong><pre>{plan.sections.find((s) => s.id === candidate.section_id)?.content_md || '尚无正文'}</pre></div><div><strong>候选稿</strong><pre>{candidate.output.content_md}</pre></div></div><button className="btn primary sm" disabled={!saved} onClick={() => run('采用本节', async () => { accept(await api.post<Workspace>(`${path}/sections/${candidate.section_id}/adopt`, { revision: state.revision, action_id: candidate.id })); setCandidate(null); reload() })}>采用本节</button><button className="btn sm" onClick={() => setCandidate(null)}>放弃候选</button></article>}
        {assembled && <article className="creation-card"><h4>母稿预览</h4><div className="md" dangerouslySetInnerHTML={{ __html: renderMarkdown(assembled) }} /><button className="btn primary sm" disabled={!saved} onClick={() => onReplaceAll(assembled)}>应用到正文（先存快照）</button></article>}
      </>}
      {step === 'review' && <>
        <h4>发布前检查</h4><p className="tiny muted">这些检查用于发现遗漏，不代表事实已核验。平台版本仍需按最新母稿核对。</p>
        {state.checks.map((check) => <div className={`creation-check ${check.ok ? 'pass' : 'pending'}`} key={check.id}><span>{check.ok ? '✓' : '○'}</span><div>{check.label}{check.details?.map((detail) => <p className="tiny" key={detail}>{detail}</p>)}</div></div>)}
        <div className="creation-actions"><button className="btn sm" onClick={() => run('检查当前正文', async () => { if (await beforeAction()) { const next = await api.get<Workspace>(path); setState((s) => s ? { ...s, checks: next.checks, excerpts: next.excerpts } : next) } })}>刷新检查</button><button className="btn primary sm" disabled={!saved || !content.trim()} onClick={() => run('MiMo 审稿', async () => { if (!await beforeAction()) return; setBaseline(content); setReview(await api.post<Proposal>(`${path}/review`)); reload() })}>审阅当前正文</button></div>
        {review && <><p className="tiny muted">{review.model} · 审阅 {review.input_scope.body_characters} 字符、{review.input_scope.evidence_ids.length} 条摘录</p>{content !== baseline && <p className="notice warn">正文已改变，请重新审稿后再采用建议。</p>}{review.warnings.map((w) => <p className="notice warn" key={w}>{w}</p>)}{!review.output.issues?.length && <p>本次未发现需替换的段落，仍请人工核对来源和判断。</p>}{review.output.issues?.map((issue, index) => <article className="creation-card" key={index}><p><strong>问题 {index + 1}</strong> · {issue.reason}</p><blockquote>{issue.quote}</blockquote><label className="creation-field">建议文字（可编辑）<textarea rows={4} value={issue.suggestion} onChange={(e) => setReview({ ...review, output: { ...review.output, issues: review.output.issues!.map((v, i) => i === index ? { ...v, suggestion: e.target.value } : v) } })} /></label><button className="btn sm" disabled={content !== baseline || !issue.suggestion.trim()} onClick={() => run('采用审稿建议', async () => { if (await onReviewReplace(baseline, issue.quote, issue.suggestion)) { setReview(null); toast('已替换该段，请重新审阅更新后的正文', 'good') } })}>仅替换此段（先存快照）</button></article>)}</>}
      </>}
    </fieldset>
  </div>
}
