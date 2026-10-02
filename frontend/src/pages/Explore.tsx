import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, type ExploreResult } from '../lib/api'
import { useFetch } from '../lib/hooks'
import { PERSONA_NAME, fmtDateTime, titleCase, zh } from '../lib/format'
import { Badge, Empty, ErrorNotice, ModeBadge } from '../components/ui'

const COVERAGE_NAME: Record<string, string> = { unserved: '无人服务', underserved: '服务不足', served: '已有服务', crowded: '拥挤' }
const PRESETS = ['AI coding agent management', 'freelancer repetitive workflow', 'small business automation']

export default function Explore() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [live, setLive] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [result, setResult] = useState<ExploreResult | null>(null)
  const { data: history, reload } = useFetch<{ items: { id: string; query: string; status: string; created_at: string }[] }>('/api/explore')
  const { data: session } = useFetch<{ result: ExploreResult; status: string }>(id ? `/api/explore/${id}` : null)
  useEffect(() => { if (session?.result?.session_id) { setResult(session.result); setQuery(session.result.query) } }, [session])

  async function run(q: string) {
    if (!q.trim()) return
    setBusy(true)
    setError(null)
    try {
      const r = await api.post<ExploreResult>('/api/explore', { query: q.trim(), live })
      setResult(r)
      reload()
      navigate(`/explore/${r.session_id}`, { replace: true })
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="page-head">
        <div><h1>探索</h1><div className="sub">输入一个市场、人群或痛点，得到痛点簇、现有产品、空白点——证据足够时还会生成机会草案。</div></div>
      </div>
      <form className="row" style={{ marginBottom: 10 }} onSubmit={(e) => { e.preventDefault(); run(query) }}>
        <input className="input" style={{ flex: 1 }} placeholder="例如：invoicing for freelance designers（英文信源，英文关键词效果更好）" value={query} onChange={(e) => setQuery(e.target.value)} />
        <label className="row small muted" style={{ gap: 6 }}><input type="checkbox" className="toggle" checked={live} onChange={(e) => setLive(e.target.checked)} /> 同时查询真实信源</label>
        <button className="btn primary" disabled={busy}>{busy ? '探索中…' : '探索'}</button>
      </form>
      <div className="row small muted" style={{ marginBottom: 20 }}>预设：{PRESETS.map((p) => <button key={p} className="btn sm" onClick={() => { setQuery(p); run(p) }}>{p}</button>)}</div>
      {busy && <div className="notice info" style={{ marginBottom: 14 }}>正在检索已存信号{live ? '、真实信源' : ''}与产品索引……真实信源可能需要 10–30 秒。</div>}
      <ErrorNotice error={error} />

      {result && (
        <div className="stack">
          <div className="card pad">
            <div className="row between"><h2>{result.query}</h2><div className="row"><ModeBadge mode={result.data_mode} /><span className="tiny muted">新增 {result.new_signals} · 库内召回 {result.recalled_signals}</span></div></div>
            {result.overview && <p className="muted" style={{ marginTop: 6 }}>{result.overview}</p>}
            <div className="row tiny muted" style={{ marginTop: 8 }}>
              {Object.entries(result.sources).map(([sid, s]) => <span key={sid} className={`badge ${s.ok ? 'neutral' : 'bad'}`}>{sid} · {s.mode}{s.ok ? ` · ${s.signals ?? 0}` : ' · 失败'}</span>)}
              {result.warnings.map((w) => <span key={w} className="badge warn">{w}</span>)}
            </div>
          </div>

          <div className="two-col">
            <div className="stack">
              <div className="section-title" style={{ margin: 0 }}><h2>痛点簇（{result.clusters.length}）</h2></div>
              {result.clusters.length === 0 && <Empty title="没有找到相关的痛点信号" hint={live ? '换个更宽泛的说法；真实信源也可能被限流。' : '启用真实信源，或先写入演示数据。'} />}
              {result.clusters.map((c) => (
                <div key={c.id} className="card pad">
                  <div className="row between">
                    <div className="row"><ModeBadge mode={c.data_mode} small /><Badge tone={c.coverage === 'unserved' ? 'good' : c.coverage === 'underserved' ? 'accent' : 'neutral'}>{zh(COVERAGE_NAME, c.coverage)}</Badge><span className="tiny muted">{zh(PERSONA_NAME, c.persona)} · {titleCase(c.category)}</span></div>
                    <span className="tiny muted">{c.signal_count} signals · {c.unique_users} users · {c.source_count} sources · rel {c.relevance.toFixed(2)}</span>
                  </div>
                  <div style={{ fontWeight: 600, marginTop: 6 }}>{c.label}</div>
                  {c.summary && <div className="small muted">{c.summary}</div>}
                  <div className="stack" style={{ gap: 6, marginTop: 8 }}>
                    {c.signals.slice(0, 3).map((s) => <div key={s.id} className="quote small">{s.excerpt}<div className="src"><a href={s.url} target="_blank" rel="noreferrer">{s.title}</a> · {s.source_id}</div></div>)}
                  </div>
                  {(c.closest_products.length > 0 || c.complaints.length > 0) && (
                    <div className="row tiny muted" style={{ marginTop: 8 }}>
                      {c.closest_products.length > 0 && <span>最接近的产品：{c.closest_products.map((p) => <Link key={p.id} to={`/products/${p.id}`} style={{ fontWeight: 500 }}>{p.name} </Link>)}</span>}
                      {c.complaints.slice(0, 4).map((x) => <Badge key={x} tone="warn">{x}</Badge>)}
                    </div>
                  )}
                </div>
              ))}
            </div>
            <div className="stack">
              {result.opportunity_draft && (
                <div className="card pad" style={{ borderColor: 'var(--accent)' }}>
                  <div className="tiny muted" style={{ textTransform: 'uppercase', letterSpacing: '.05em' }}>机会草案</div>
                  {result.opportunity_draft.unavailable ? <div className="small" style={{ marginTop: 6 }}>{result.opportunity_draft.unavailable}</div> : (
                    <>
                      <div className="row between" style={{ marginTop: 4 }}><div style={{ fontWeight: 600, fontSize: 15 }}>{result.opportunity_draft.title}</div><span className="score-big" style={{ fontSize: 24 }}>{Math.round(result.opportunity_draft.opportunity_score ?? 0)}</span></div>
                      <div className="small muted" style={{ marginTop: 4 }}>{result.opportunity_draft.core_pain}</div>
                      <div className="small" style={{ marginTop: 8 }}><b>切入点：</b> {result.opportunity_draft.wedge}</div>
                      <div className="row" style={{ marginTop: 10 }}><ModeBadge mode={result.opportunity_draft.data_mode} small /><Link className="btn sm" to={`/opportunities/${result.opportunity_draft.id}`}>打开机会 →</Link></div>
                    </>
                  )}
                </div>
              )}
              <div className="card pad">
                <h3 style={{ marginBottom: 8 }}>现有产品（{result.products.length}）</h3>
                {result.products.length === 0 && <div className="small muted">产品索引里没有匹配项。采集 Product Hunt 数据后会出现在这里。</div>}
                <div className="stack" style={{ gap: 8 }}>
                  {result.products.map((p) => (
                    <div key={p.id} className="row between small">
                      <div style={{ minWidth: 0 }}><Link to={`/products/${p.id}`} style={{ fontWeight: 500 }}>{p.name}</Link> <span className="muted">{p.tagline}</span></div>
                      <div className="row tiny muted" style={{ flexShrink: 0 }}><ModeBadge mode={p.origin} small /><span>{p.votes} 票</span>{p.pricing && <span>{p.pricing}</span>}</div>
                    </div>
                  ))}
                </div>
              </div>
              <div className="card pad">
                <h3 style={{ marginBottom: 8 }}>空白点</h3>
                {result.gaps.length === 0 && <div className="small muted">每个痛点簇都有贴近的产品且没有反复出现的抱怨——没有明显空白。</div>}
                <div className="stack" style={{ gap: 8 }}>{result.gaps.map((g) => <div key={g.cluster_id} className="small"><Badge tone={g.coverage === 'unserved' ? 'good' : g.coverage === 'underserved' ? 'accent' : 'warn'}>{zh(COVERAGE_NAME, g.coverage)}</Badge> {g.label}{g.complaints.length > 0 && <div className="tiny muted">抱怨：{g.complaints.join(' · ')}</div>}</div>)}</div>
              </div>
            </div>
          </div>
        </div>
      )}

      {!result && history && history.items.length > 0 && (
        <>
          <div className="section-title"><h2>最近的探索</h2></div>
          <div className="card">
            <table className="table"><tbody>{history.items.map((h) => <tr key={h.id} className="link" onClick={() => navigate(`/explore/${h.id}`)}><td>{h.query}</td><td className="muted small">{h.status}</td><td className="muted small">{fmtDateTime(h.created_at)}</td></tr>)}</tbody></table>
          </div>
        </>
      )}
    </>
  )
}
