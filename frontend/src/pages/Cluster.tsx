import { Link, useParams } from 'react-router-dom'
import { useFetch } from '../lib/hooks'
import { PERSONA_NAME, fmtDate, titleCase, zh } from '../lib/format'
import { ErrorNotice, Loading, ModeBadge, Sparkline, StageBadge } from '../components/ui'

interface Cluster {
  id: string; label: string; summary?: string; persona?: string; category?: string; stage: string; velocity: number; acceleration: number; signal_count: number; unique_users: number; source_count: number
  first_seen?: string; last_seen?: string; data_mode: string; label_source: string; analysis_status: string; analysis_error?: string; session_id?: string | null
  signals: { id: string; external_id: string; source_id: string; origin: string; url: string; title: string; author?: string; created_at?: string; engagement: Record<string, number>; rule_score: number; similarity: number; relevance?: number; excerpt: string }[]
  opportunity?: { id: string; title: string; opportunity_score: number; status: string } | null
  series: number[]
}

export default function ClusterPage() {
  const { id } = useParams()
  const { data: c, error, loading } = useFetch<Cluster>(`/api/clusters/${id}`)
  if (loading && !c) return <Loading />
  if (error) return <ErrorNotice error={error} />
  if (!c) return null
  return (
    <>
      <div className="row small muted" style={{ marginBottom: 10 }}><Link to="/radar">痛点雷达</Link><span>/</span><span>痛点簇</span></div>
      <div className="page-head">
        <div>
          <div className="row" style={{ marginBottom: 6 }}><ModeBadge mode={c.data_mode} /><StageBadge stage={c.stage} />{c.session_id && <span className="badge neutral">探索会话</span>}<span className="tiny faint">标签来自 {c.label_source} · 分析 {c.analysis_status}</span></div>
          <h1>{c.label}</h1>
          {c.summary && <div className="sub">{c.summary}</div>}
        </div>
        <Sparkline data={c.series} width={200} height={40} />
      </div>
      <div className="meta" style={{ marginBottom: 16 }}>
        <span><b>{c.signal_count}</b> 条信号</span><span><b>{c.unique_users}</b> 位用户</span><span><b>{c.source_count}</b> 个来源</span><span>速度 <b>×{c.velocity.toFixed(1)}</b></span>
        <span>{zh(PERSONA_NAME, c.persona)} · {titleCase(c.category)}</span><span>首次 {fmtDate(c.first_seen)} · 最近 {fmtDate(c.last_seen)}</span>
        {c.opportunity && <Link to={`/opportunities/${c.opportunity.id}`} className="badge accent">机会：{c.opportunity.title} · {Math.round(c.opportunity.opportunity_score)}</Link>}
      </div>
      {c.analysis_error && <div className="notice" style={{ marginBottom: 12 }}>{c.analysis_error}</div>}
      <div className="card">
        <table className="table">
          <thead><tr><th>信号</th><th>来源</th><th>互动</th><th>相似度</th><th>日期</th></tr></thead>
          <tbody>
            {c.signals.map((s) => (
              <tr key={s.id}>
                <td><a href={s.url} target="_blank" rel="noreferrer" style={{ fontWeight: 500 }}>{s.title}</a><div className="small muted">{s.excerpt}</div></td>
                <td className="small"><ModeBadge mode={s.origin} small /> {s.source_id}{s.author && <div className="tiny muted">{s.author}</div>}</td>
                <td className="small muted">{Object.entries(s.engagement).filter(([, v]) => v).map(([k, v]) => `${v} ${k}`).join(' · ') || '—'}</td>
                <td className="mono">{s.similarity?.toFixed(2)}</td>
                <td className="small muted">{fmtDate(s.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
