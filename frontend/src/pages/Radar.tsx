import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { RadarCluster } from '../lib/api'
import { useFetch } from '../lib/hooks'
import { OPP_STATUS_NAME, PERSONA_NAME, titleCase, zh } from '../lib/format'
import { Empty, ErrorNotice, Loading, ModeBadge, Sparkline, StageBadge } from '../components/ui'

const WINDOWS = ['7d', '30d', '90d'] as const
const WINDOW_NAME: Record<string, string> = { '7d': '7 天', '30d': '30 天', '90d': '90 天' }

export default function Radar() {
  const [win, setWin] = useState<(typeof WINDOWS)[number]>('30d')
  const { data, error, loading } = useFetch<{ clusters: RadarCluster[]; stages: Record<string, number> }>(`/api/radar?window=${win}`)
  return (
    <>
      <div className="page-head">
        <div>
          <h1>痛点雷达</h1>
          <div className="sub">按势头排序的用户痛点簇。速度 = 最近 7 天对比之前 3 周的日均量——绝对数量从不单独决定排序。</div>
        </div>
        <div className="tabs">{WINDOWS.map((w) => <button key={w} className={w === win ? 'active' : ''} onClick={() => setWin(w)}>{WINDOW_NAME[w]}</button>)}</div>
      </div>
      {error && <ErrorNotice error={error} />}
      {loading && !data && <Loading />}
      {data && (
        <>
          <div className="row" style={{ marginBottom: 14 }}>
            {Object.entries(data.stages).map(([s, n]) => <span key={s} className="small muted"><StageBadge stage={s} /> {n}</span>)}
          </div>
          {data.clusters.length === 0 ? (
            <Empty title="这个时间窗内没有痛点簇" hint="运行流水线，或放宽时间窗。" />
          ) : (
            <div className="card">
              <table className="table">
                <thead><tr><th>痛点簇</th><th>阶段</th><th>速度</th><th>趋势（{WINDOW_NAME[win]}）</th><th>信号</th><th>用户</th><th>来源</th><th>机会</th></tr></thead>
                <tbody>
                  {data.clusters.map((c) => (
                    <tr key={c.id}>
                      <td>
                        <Link to={`/clusters/${c.id}`} style={{ fontWeight: 500 }}>{c.label}</Link>
                        <div className="tiny muted row" style={{ gap: 6, marginTop: 2 }}><ModeBadge mode={c.data_mode} small /> {zh(PERSONA_NAME, c.persona)} · {titleCase(c.category)}</div>
                      </td>
                      <td><StageBadge stage={c.stage} /></td>
                      <td className="score">×{c.velocity.toFixed(1)} <span className="tiny muted">({c.acceleration >= 0 ? '+' : ''}{c.acceleration.toFixed(1)})</span></td>
                      <td><Sparkline data={c.series} /></td>
                      <td>{c.signal_count} <span className="tiny muted">（窗口内 {c.window_signals}）</span></td>
                      <td>{c.unique_users}</td>
                      <td>{c.source_count}</td>
                      <td>{c.opportunity_id ? <Link to={`/opportunities/${c.opportunity_id}`} className="badge accent">{Math.round(c.opportunity_score ?? 0)} · {zh(OPP_STATUS_NAME, c.opportunity_status)}</Link> : <span className="tiny muted">{c.analysis_status === 'skipped' ? '未分析（无模型）' : '未过门槛'}</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </>
  )
}
