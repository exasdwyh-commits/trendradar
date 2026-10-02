import { useState } from 'react'
import { api, type Job } from '../lib/api'
import { useFetch } from '../lib/hooks'
import { ago, fmtDateTime } from '../lib/format'
import { Badge, Empty, ErrorNotice, Loading } from '../components/ui'

const JOB_NAME: Record<string, string> = { daily: '每日流水线', collect: '采集', seed: '演示数据', brief: '简报刷新', explore: '探索' }
const STATUS_NAME: Record<string, string> = { success: '成功', partial: '部分成功', failed: '失败', running: '运行中' }

export default function Jobs() {
  const { data, error, loading, reload } = useFetch<{ items: Job[]; running: { type?: string | null; started_at?: string | null } }>('/api/jobs')
  const [msg, setMsg] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(null)

  async function run(type: 'daily' | 'collect' | 'seed' | 'brief', mockOnly = false) {
    setMsg(null)
    try {
      await api.post('/api/jobs/run', { type, mock_only: mockOnly })
      setMsg(`${JOB_NAME[type] ?? type}任务已启动。`)
      setTimeout(reload, 3000)
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <>
      <div className="page-head">
        <div><h1>任务</h1><div className="sub">每次流水线运行的分步计数、失败与模型调用。</div></div>
        <div className="row">
          <button className="btn" onClick={() => run('collect')}>仅采集</button>
          <button className="btn" onClick={() => run('seed')}>写入演示数据</button>
          <button className="btn" onClick={() => run('brief')}>刷新简报</button>
          <button className="btn primary" onClick={() => run('daily')}>运行每日流水线</button>
        </div>
      </div>
      {msg && <div className="notice info" style={{ marginBottom: 12 }}>{msg}</div>}
      {data?.running?.type && <div className="notice" style={{ marginBottom: 12 }}><b>{JOB_NAME[data.running.type] ?? data.running.type}</b> 任务正在运行（{ago(data.running.started_at)}开始）。<button className="btn sm" onClick={reload}>刷新</button></div>}
      {error && <ErrorNotice error={error} />}
      {loading && !data && <Loading />}
      {data && data.items.length === 0 && <Empty title="还没有任务记录" hint="运行每日流水线，或写入演示数据。" />}
      {data && data.items.length > 0 && (
        <div className="card">
          <table className="table">
            <thead><tr><th>开始</th><th>类型</th><th>状态</th><th>步骤</th><th>模型调用</th><th>耗时</th></tr></thead>
            <tbody>
              {data.items.map((j) => (
                <JobRow key={j.id} j={j} open={open === j.id} onToggle={() => setOpen(open === j.id ? null : j.id)} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

function JobRow({ j, open, onToggle }: { j: Job; open: boolean; onToggle: () => void }) {
  const dur = j.finished_at ? Math.round((new Date(j.finished_at).getTime() - new Date(j.started_at).getTime()) / 1000) : null
  const tone = j.interrupted ? 'warn' : j.status === 'success' ? 'good' : j.status === 'partial' ? 'warn' : j.status === 'failed' ? 'bad' : 'accent'
  return (
    <>
      <tr className="link" onClick={onToggle}>
        <td>{fmtDateTime(j.started_at)}</td>
        <td><Badge>{JOB_NAME[j.job_type] ?? j.job_type}</Badge></td>
        <td><Badge tone={tone}>{j.interrupted ? '已中断' : STATUS_NAME[j.status] ?? j.status}</Badge></td>
        <td><div className="steps">{j.steps.map((s, i) => <span key={i} className={`step ${s.status}`} title={s.error ?? JSON.stringify(s.counts)}>{s.step}</span>)}</div></td>
        <td>{j.ai_calls}</td>
        <td className="muted small">{dur === null ? '运行中' : `${dur} 秒`}</td>
      </tr>
      {open && (
        <tr><td colSpan={6} style={{ background: 'var(--bg-subtle)' }}>
          {j.error && <div className="notice error" style={{ marginBottom: 8 }}>{j.error}</div>}
          <table className="table"><tbody>
            {j.steps.map((s, i) => <tr key={i}><td style={{ width: 160 }}><b>{s.step}</b><div className="tiny muted">{s.status}</div></td><td><pre className="mono" style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{s.error ? s.error : JSON.stringify(s.counts, null, 1)}</pre></td></tr>)}
          </tbody></table>
        </td></tr>
      )}
    </>
  )
}
