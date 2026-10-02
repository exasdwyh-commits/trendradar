import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type TodayPayload } from '../lib/api'
import { useFetch } from '../lib/hooks'
import { ago } from '../lib/format'
import { Empty, ErrorNotice, Loading, Markdown, OpportunityCard } from '../components/ui'

export default function Today() {
  const { data, error, loading, reload } = useFetch<TodayPayload>('/api/today')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)

  async function runJob(type: 'seed' | 'daily') {
    setBusy(true)
    setMsg(null)
    try {
      await api.post('/api/jobs/run', { type })
      setMsg(type === 'seed' ? '演示数据开始写入，几秒后刷新即可。' : '每日流水线已启动——接真实信源时可能需要几分钟。')
      setTimeout(reload, 4000)
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  if (loading && !data) return <Loading />
  if (error) return <ErrorNotice error={error} />
  if (!data) return null
  const noData = data.data.signals === 0
  return (
    <>
      <div className="page-head">
        <div>
          <h1>今日精选</h1>
          <div className="sub">{data.day} · {data.picks.length ? `${data.picks.length} 个机会过线（评分 ≥ ${data.thresholds.min_score}，置信度 ≥ ${data.thresholds.min_confidence}）` : '今天没有机会达到质量线'}</div>
        </div>
        <div className="row">
          {data.last_job && <span className="tiny muted">上次 {data.last_job.job_type} · {ago(data.last_job.started_at)} · {data.last_job.status}</span>}
          <button className="btn" disabled={busy} onClick={() => runJob('daily')}>运行流水线</button>
        </div>
      </div>
      {msg && <div className="notice info" style={{ marginBottom: 14 }}>{msg}</div>}
      {data.data.mock > 0 && data.data.live === 0 && (
        <div className="notice" style={{ marginBottom: 14 }}>演示模式：以下内容全部由内置演示数据生成，并标注为 <b>演示</b>。在 <code>.env</code> 里配置模型密钥并启用真实信源后运行流水线，即可看到真实信号。</div>
      )}
      {noData ? (
        <Empty title="还没有数据" hint="写入三个演示案例，可在没有任何 API 密钥的情况下看完整的「痛点 → 竞品 → 空白 → 机会」链路；或直接对真实信源运行每日流水线。" action={<div className="row" style={{ justifyContent: 'center' }}><button className="btn primary" disabled={busy} onClick={() => runJob('seed')}>写入演示数据</button><button className="btn" disabled={busy} onClick={() => runJob('daily')}>运行每日流水线</button></div>} />
      ) : data.picks.length === 0 ? (
        <Empty title="今天没有机会过线" hint="宁缺毋滥。下面是仍在雷达上的最佳候选。" />
      ) : (
        <div className="stack">{data.picks.map((o, i) => <OpportunityCard key={o.id} o={o} rank={i + 1} />)}</div>
      )}
      {data.also_on_radar.length > 0 && (
        <>
          <div className="section-title"><h2>也在雷达上</h2><Link to="/opportunities" className="small muted">全部机会 →</Link></div>
          <div className="grid cols-2">{data.also_on_radar.map((o) => <OpportunityCard key={o.id} o={o} />)}</div>
        </>
      )}
      {data.brief_md && (
        <>
          <div className="section-title"><h2>机会日报</h2><span className="tiny faint">{ago(data.brief_at)}</span></div>
          <div className="card pad"><Markdown text={data.brief_md} /></div>
        </>
      )}
    </>
  )
}
