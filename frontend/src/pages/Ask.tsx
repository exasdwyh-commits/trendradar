import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type AskResult } from '../lib/api'
import { useFetch } from '../lib/hooks'
import { fmtDateTime } from '../lib/format'
import { ErrorNotice, Markdown, ModeBadge } from '../components/ui'

const EXAMPLES = ['给开发者做什么产品一个周末能做出来？', '哪些机会的付费意愿最强？', '小企业主有哪些竞争薄弱的问题？']

export default function Ask() {
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [result, setResult] = useState<AskResult | null>(null)
  const { data: history, reload } = useFetch<{ items: { id: string; question: string; answer_md: string; citations: string[]; generated_by: string; created_at: string }[] }>('/api/ask')

  async function run(question: string) {
    if (!question.trim()) return
    setBusy(true)
    setError(null)
    try {
      setResult(await api.post<AskResult>('/api/ask', { question: question.trim() }))
      reload()
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="page-head"><div><h1>问答</h1><div className="sub">只依据本库里的机会与证据回答——不会去开放互联网找答案。</div></div></div>
      <form className="row" style={{ marginBottom: 10 }} onSubmit={(e) => { e.preventDefault(); run(q) }}>
        <input className="input" style={{ flex: 1 }} placeholder="问问雷达里的机会…" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="btn primary" disabled={busy}>{busy ? '思考中…' : '提问'}</button>
      </form>
      <div className="row small muted" style={{ marginBottom: 20 }}>{EXAMPLES.map((e) => <button key={e} className="btn sm" onClick={() => { setQ(e); run(e) }}>{e}</button>)}</div>
      <ErrorNotice error={error} />
      {result && (
        <div className="card pad stack">
          <div className="row between"><h2>{result.question}</h2><div className="row"><ModeBadge mode={result.data_mode} /><span className="tiny muted">回答来自 {result.generated_by}</span></div></div>
          <Markdown text={result.answer_md} />
          {result.candidates.length > 0 && (
            <div>
              <div className="tiny muted" style={{ marginBottom: 4 }}>引用的机会</div>
              <div className="row">{result.candidates.filter((c) => result.citations.includes(c.id)).map((c) => <Link key={c.id} to={`/opportunities/${c.id}`} className="badge accent">{c.title} · {Math.round(c.opportunity_score)}</Link>)}</div>
            </div>
          )}
          <details className="tiny muted"><summary>检索计划</summary><pre className="mono">{JSON.stringify(result.plan, null, 2)}</pre></details>
        </div>
      )}
      {history && history.items.length > 0 && (
        <>
          <div className="section-title"><h2>最近的问题</h2></div>
          <div className="stack">{history.items.slice(0, 8).map((h) => <div key={h.id} className="card pad"><div className="row between"><b>{h.question}</b><span className="tiny faint">{h.generated_by} · {fmtDateTime(h.created_at)}</span></div><div className="small" style={{ marginTop: 6 }}><Markdown text={h.answer_md} /></div></div>)}</div>
        </>
      )}
    </>
  )
}
