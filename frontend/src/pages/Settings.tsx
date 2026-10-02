import type { Settings } from '../lib/api'
import { useFetch } from '../lib/hooks'
import { Badge, ErrorNotice, Loading } from '../components/ui'

export default function SettingsPage() {
  const { data, error, loading } = useFetch<Settings>('/api/settings')
  if (loading && !data) return <Loading />
  if (error) return <ErrorNotice error={error} />
  if (!data) return null
  return (
    <>
      <div className="page-head"><div><h1>设置</h1><div className="sub">当前进程实际使用的配置（只读）。修改 <code>.env</code> 与 <code>config/settings.yml</code> 后重启生效。</div></div></div>
      <div className="grid cols-2">
        <div className="card pad">
          <h3 style={{ marginBottom: 10 }}>模型</h3>
          <dl className="kv">
            {Object.entries(data.models).map(([slot, m]) => <><dt key={slot + 'k'}>{slot}</dt><dd key={slot + 'v'}>{m.enabled ? <><Badge tone="good">已配置</Badge> <span className="mono">{m.model}</span></> : <Badge tone="warn">未配置</Badge>}{m.call_limit_24h ? <span className="tiny muted"> · 上限 {m.call_limit_24h} 次/24h</span> : null}</dd></>)}
            <dt>向量</dt><dd><span className="mono">{data.embedding.provider}</span> · {data.embedding.dim}d {data.embedding.degraded && <Badge tone="warn">本地哈希（降级）</Badge>}</dd>
            <dt>分类器</dt><dd>{data.classifier.provider}</dd>
            <dt>Product Hunt</dt><dd>{data.producthunt_mode} {data.producthunt_token_set ? <Badge tone="good">已设置 token</Badge> : <Badge tone="warn">无 token → 演示数据</Badge>}</dd>
            <dt>GitHub token</dt><dd>{data.github_token_set ? '已设置' : '未设置（匿名 60 次/小时）'}</dd>
            <dt>定时</dt><dd>每天 {String(data.daily_hour).padStart(2, '0')}:00（{data.timezone}）</dd>
            <dt>预算</dt><dd>{data.budget_cny_24h ? `¥${data.budget_cny_24h} / 24h` : '未设上限'}</dd>
            <dt>数据库</dt><dd className="mono">{data.db_path}</dd>
          </dl>
        </div>
        <div className="card pad">
          <h3 style={{ marginBottom: 10 }}>用量（24 小时）</h3>
          <table className="table"><thead><tr><th>槽位</th><th>调用</th><th>费用</th></tr></thead><tbody>
            {Object.entries(data.usage_24h).map(([slot, u]) => <tr key={slot}><td>{slot}</td><td>{u.calls}</td><td>¥{(u.cost ?? 0).toFixed(3)}</td></tr>)}
          </tbody></table>
          <h3 style={{ margin: '16px 0 8px' }}>按任务（7 天）</h3>
          {data.usage_7d_by_task.length === 0 ? <div className="small muted">还没有模型调用。</div> : (
            <table className="table"><thead><tr><th>任务</th><th>模型</th><th>调用</th><th>Tokens</th><th>费用</th><th>失败</th></tr></thead><tbody>
              {data.usage_7d_by_task.map((r, i) => <tr key={i}><td>{r.task}</td><td className="mono">{r.model}</td><td>{r.calls}</td><td>{(r.input_tokens ?? 0) + (r.output_tokens ?? 0)}</td><td>¥{(r.cost ?? 0).toFixed(3)}</td><td>{r.failures}</td></tr>)}
            </tbody></table>
          )}
        </div>
        <div className="card pad">
          <h3 style={{ marginBottom: 10 }}>流水线阈值</h3>
          <dl className="kv">{Object.entries(data.pipeline).map(([k, v]) => <><dt key={k + 'k'} className="mono">{k}</dt><dd key={k + 'v'}>{String(v)}</dd></>)}</dl>
        </div>
        <div className="card pad">
          <h3 style={{ marginBottom: 10 }}>评分权重</h3>
          <dl className="kv">{Object.entries(data.weights).map(([k, v]) => <><dt key={k + 'k'}>{k}</dt><dd key={k + 'v'}>{Math.round(v * 100)}%</dd></>)}</dl>
          <div className="tiny muted" style={{ marginTop: 10 }}>总分 = Σ 权重 × 维度分 × (0.7 + 0.3 × 证据置信度 / 100)</div>
        </div>
      </div>
    </>
  )
}
