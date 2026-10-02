import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, type BuilderBrief as Brief, type OpportunityDetail as Detail } from '../lib/api'
import { useFetch } from '../lib/hooks'
import { DIFFICULTY, DIMENSIONS, DIMENSION_LABEL, OPP_STATUS_NAME, ago, fmtDate, titleCase, zh } from '../lib/format'
import { Badge, Bar, ErrorNotice, Loading, ModeBadge, ScoreRing, Sparkline, StageBadge, StatusBadge } from '../components/ui'

export default function OpportunityDetail() {
  const { id } = useParams()
  const { data: o, error, loading, reload } = useFetch<Detail>(`/api/opportunities/${id}`)
  const { data: brief, reload: reloadBrief } = useFetch<Brief>(o?.brief ? `/api/opportunities/${id}/brief` : null, [o?.brief?.id])
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [tab, setTab] = useState<'evidence' | 'competition' | 'brief'>('evidence')

  async function move(status: string) {
    setBusy(true)
    try {
      await api.post(`/api/opportunities/${id}/status`, { status })
      reload()
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  async function startProduct() {
    setBusy(true)
    setMsg(null)
    try {
      await api.post<Brief>(`/api/opportunities/${id}/brief`)
      setTab('brief')
      reload()
      reloadBrief()
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  if (loading && !o) return <Loading />
  if (error) return <ErrorNotice error={error} />
  if (!o) return null
  const conf = o.scores.confidence?.score ?? o.confidence
  return (
    <>
      <div className="row small muted" style={{ marginBottom: 10 }}><Link to="/opportunities">产品机会</Link><span>/</span><span>{o.title}</span></div>
      <div className="page-head">
        <div style={{ minWidth: 0 }}>
          <div className="row" style={{ marginBottom: 6 }}><ModeBadge mode={o.data_mode} /><StageBadge stage={o.stage} /><StatusBadge status={o.status} /><span className="tiny faint">v{o.version} · 生成自 {o.generated_by}</span></div>
          <h1>{o.title}</h1>
          <div className="sub">{o.core_pain}</div>
        </div>
        <div className="row" style={{ alignItems: 'flex-start', gap: 22 }}>
          <ScoreRing value={o.opportunity_score} label="机会评分" />
          <ScoreRing value={conf} label="证据置信度" />
        </div>
      </div>
      {msg && <div className="notice error" style={{ marginBottom: 14 }}>{msg}</div>}
      <div className="row" style={{ marginBottom: 18 }}>
        {o.allowed_transitions.filter((s) => !['rejected', 'archived'].includes(s)).map((s) => <button key={s} className="btn sm" disabled={busy} onClick={() => move(s)}>→ {zh(OPP_STATUS_NAME, s)}</button>)}
        {o.allowed_transitions.includes('rejected') && <button className="btn sm" disabled={busy} onClick={() => move('rejected')}>否决</button>}
        {o.allowed_transitions.includes('archived') && <button className="btn sm" disabled={busy} onClick={() => move('archived')}>归档</button>}
        <span style={{ flex: 1 }} />
        <button className="btn primary" disabled={busy} onClick={startProduct}>{o.brief ? '重新生成产品简报' : '开始做产品 →'}</button>
      </div>

      <div className="two-col">
        <div className="stack">
          <div className="card pad">
            <dl className="kv">
              <dt>目标用户</dt><dd>{o.target_user}</dd>
              <dt>建议方案</dt><dd>{o.proposed_solution}</dd>
              <dt>切入点</dt><dd>{o.wedge}</dd>
              <dt>为什么是现在</dt><dd>{o.why_now}</dd>
              <dt>变现</dt><dd>{o.monetization}</dd>
              <dt>获客渠道</dt><dd>{o.distribution}</dd>
              <dt>对手弱点</dt><dd>{o.competitor_weakness}</dd>
              <dt>构建难度</dt><dd>{titleCase(o.build_type)} · {DIFFICULTY[o.build_difficulty ?? ''] ?? o.build_difficulty}</dd>
              {o.risks.length > 0 && <><dt>风险</dt><dd><ul style={{ margin: 0, paddingLeft: 18 }}>{o.risks.map((r) => <li key={r}>{r}</li>)}</ul></dd></>}
              <dt>下一步</dt><dd><b>{o.next_action}</b></dd>
            </dl>
          </div>

          <div className="tabs" style={{ alignSelf: 'flex-start' }}>
            <button className={tab === 'evidence' ? 'active' : ''} onClick={() => setTab('evidence')}>痛点证据（{o.pain_signals.length}）</button>
            <button className={tab === 'competition' ? 'active' : ''} onClick={() => setTab('competition')}>竞品（{o.competition?.competitor_count ?? 0}）</button>
            <button className={tab === 'brief' ? 'active' : ''} onClick={() => setTab('brief')}>产品简报{o.brief ? '' : '（未生成）'}</button>
          </div>

          {tab === 'evidence' && (
            <div className="stack">
              {o.pain_signals.map((p) => (
                <div key={p.id} className="card pad">
                  <div className="row between" style={{ marginBottom: 6 }}>
                    <div className="row"><ModeBadge mode={p.origin} small /><span className="small muted">{p.source_id}</span><span className="tiny faint">{fmtDate(p.created_at)}</span>{p.author && <span className="tiny faint">{p.author}</span>}</div>
                    <div className="row tiny muted">
                      {p.severity != null && <span>严重度 <b>{Math.round(p.severity)}</b></span>}
                      {p.frequency != null && <span>频率 <b>{Math.round(p.frequency)}</b></span>}
                      {p.willingness_to_pay != null && <span>付费意愿 <b>{Math.round(p.willingness_to_pay)}</b></span>}
                    </div>
                  </div>
                  <div style={{ fontWeight: 500 }}>{p.problem}</div>
                  {p.evidence_quote && <div className="quote" style={{ marginTop: 8 }}>“{p.evidence_quote}”<div className="src"><a href={p.url} target="_blank" rel="noreferrer">{p.title}</a> · <Link to={`/signals/${p.signal_id}`} className="faint">信号详情</Link></div></div>}
                  <div className="row tiny muted" style={{ marginTop: 8 }}>
                    {p.existing_workaround && <span>绕行方案：{p.existing_workaround}</span>}
                    {p.current_solution && <span>· 当前工具：{p.current_solution}</span>}
                    {p.friction.map((f) => <Badge key={f}>{titleCase(f)}</Badge>)}
                  </div>
                </div>
              ))}
              {o.pain_signals.length === 0 && <div className="empty">还没有结构化痛点信号——该痛点簇尚未分析。</div>}
            </div>
          )}

          {tab === 'competition' && (
            <div className="stack">
              {o.competition ? (
                <>
                  <div className="card pad">
                    <div className="row between" style={{ marginBottom: 8 }}><h3>市场解读</h3><ModeBadge mode={o.competition.data_mode} /></div>
                    <div className="grid cols-4">
                      <Stat label="可比产品" value={o.competition.competitor_count} />
                      <Stat label="Density" value={`${Math.round(o.competition.density)}/100`} />
                      <Stat label="Maturity" value={`${Math.round(o.competition.maturity)}/100`} />
                      <Stat label="Avg rating" value={o.competition.avg_rating ? o.competition.avg_rating.toFixed(1) : '—'} />
                      <Stat label="Review volume" value={o.competition.review_volume} />
                      <Stat label="近 90 天发布" value={o.competition.recent_launches_90d} />
                      <Stat label="定价分布" value={Object.entries(o.competition.pricing_distribution).map(([k, v]) => `${k} ${v}`).join(' · ') || '—'} />
                    </div>
                    {o.competition.common_complaints.length > 0 && <div style={{ marginTop: 12 }}><div className="tiny muted" style={{ marginBottom: 4 }}>竞品间反复出现的抱怨（从评论推导）</div><div className="row">{o.competition.common_complaints.map((c) => <Badge key={c} tone="warn">{c}</Badge>)}</div></div>}
                    {o.competition.common_features.length > 0 && <div style={{ marginTop: 10 }}><div className="tiny muted" style={{ marginBottom: 4 }}>共同优势</div><div className="row">{o.competition.common_features.map((c) => <Badge key={c}>{c}</Badge>)}</div></div>}
                  </div>
                  {o.competition.competitors.map((c) => (
                    <div key={c.product_id} className="card pad">
                      <div className="row between">
                        <div><Link to={`/products/${c.product_id}`} style={{ fontWeight: 600 }}>{c.name}</Link> <span className="muted">{c.tagline}</span></div>
                        <div className="row tiny muted"><ModeBadge mode={c.origin} small /><span>{c.votes} votes</span>{c.rating != null && <span>★ {c.rating}</span>}{c.pricing && <span>{c.pricing}{c.pricing_origin === 'inferred' ? ' (inferred)' : ''}</span>}<span>sim {c.similarity.toFixed(2)}</span></div>
                      </div>
                      {c.insights && (
                        <div className="grid cols-2 small" style={{ marginTop: 8 }}>
                          <div><div className="tiny muted">Pros</div>{c.insights.pros.map((x) => <div key={x}>+ {x}</div>)}</div>
                          <div><div className="tiny muted">Complaints</div>{c.insights.complaints.map((x) => <div key={x}>− {x}</div>)}</div>
                        </div>
                      )}
                      {c.insights?.summary && <div className="small muted" style={{ marginTop: 6 }}>{c.insights.summary} <span className="tiny faint">（来自 {c.insights.sample_size} 条评论）</span></div>}
                    </div>
                  ))}
                  {o.competition.competitor_count === 0 && <div className="notice">产品索引中没有找到可比产品。这<b>不</b>自动等于好事——竞争评分会把缺少市场验证视为风险。</div>}
                </>
              ) : <div className="empty">还没有竞争画像。</div>}
            </div>
          )}

          {tab === 'brief' && (
            brief ? <BriefView b={brief} /> : <div className="empty">点击<b>开始做产品</b>，基于这个机会的证据生成产品简报。{!o.data_mode || o.data_mode === 'live' ? ' 需要配置 ANALYSIS_MODEL。' : ''}</div>
          )}
        </div>

        <div className="stack">
          <div className="card pad">
            <h3 style={{ marginBottom: 8 }}>评分依据</h3>
            {DIMENSIONS.map((d) => {
              const s = o.scores[d]
              if (!s) return null
              return (
                <div key={d} className="dim-row">
                  <div><div style={{ fontWeight: 500 }}>{DIMENSION_LABEL[d]}</div><div className="tiny faint">{s.method === 'unavailable' ? '无模型' : s.method} · 置信 {Math.round(s.confidence * 100)}%</div></div>
                  <div><Bar value={s.score} /><div className="reason">{s.reason}</div></div>
                  <div className="score" style={{ textAlign: 'right' }}>{Math.round(s.score)}</div>
                </div>
              )
            })}
          </div>
          <div className="card pad">
            <h3 style={{ marginBottom: 8 }}>信号趋势（30 天）</h3>
            <Sparkline data={o.trend_series} width={300} height={48} />
            <div className="meta" style={{ marginTop: 8 }}>
              <span>速度 <b>×{o.velocity.toFixed(1)}</b></span><span>加速度 <b>{o.acceleration >= 0 ? '+' : ''}{o.acceleration.toFixed(1)}</b></span>
              <span><b>{o.signal_count}</b> 条信号</span><span><b>{o.unique_users}</b> 位用户</span><span><b>{o.source_count}</b> 个来源</span>
            </div>
            <div className="tiny faint" style={{ marginTop: 6 }}>首次 {fmtDate(o.first_seen)} · 最近 {fmtDate(o.last_seen)} · 痛点簇 <Link to={`/clusters/${o.pain_cluster_id}`}>{o.cluster_label}</Link></div>
          </div>
          <div className="card pad">
            <h3 style={{ marginBottom: 8 }}>证据（{o.evidence.length}）</h3>
            <div className="stack" style={{ gap: 8 }}>
              {o.evidence.slice(0, 12).map((e) => (
                <div key={e.id} className="small">
                  <div className="row tiny muted"><Badge>{e.kind}</Badge><span>{e.source_id}</span><ModeBadge mode={e.origin} small /><span className="faint">{fmtDate(e.occurred_at)}</span></div>
                  <a href={e.url} target="_blank" rel="noreferrer" className="muted">“{e.quote.slice(0, 160)}{e.quote.length > 160 ? '…' : ''}”</a>
                </div>
              ))}
            </div>
          </div>
          <div className="card pad">
            <h3 style={{ marginBottom: 8 }}>状态历史</h3>
            {o.status_log.map((l, i) => <div key={i} className="small muted">{ago(l.created_at)} · {l.from_status ? `${zh(OPP_STATUS_NAME, l.from_status)} → ` : ''}{zh(OPP_STATUS_NAME, l.to_status)}{l.note ? ` — ${l.note}` : ''}</div>)}
          </div>
        </div>
      </div>
    </>
  )
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return <div><div className="tiny muted">{label}</div><div style={{ fontWeight: 600 }}>{value}</div></div>
}

function BriefView({ b }: { b: Brief }) {
  const Section = ({ title, children }: { title: string; children: React.ReactNode }) => (
    <div><div className="tiny muted" style={{ textTransform: 'uppercase', letterSpacing: '.05em', marginBottom: 4 }}>{title}</div><div>{children}</div></div>
  )
  const list = (items: string[]) => <ul style={{ margin: 0, paddingLeft: 18 }}>{items.map((x, i) => <li key={i}>{x}</li>)}</ul>
  return (
    <div className="card pad stack" style={{ gap: 16 }}>
      <div className="row between"><h3>产品简报</h3><span className="tiny faint">生成自 {b.generated_by} · {ago(b.created_at)}</span></div>
      <Section title="问题定义">{b.problem_definition}</Section>
      <Section title="目标用户">{b.target_user}</Section>
      <Section title="待完成任务（JTBD）">{list(b.jtbd)}</Section>
      <Section title="MVP 范围">{b.mvp_scope}</Section>
      <Section title="核心功能"><ul style={{ margin: 0, paddingLeft: 18 }}>{b.core_features.map((f, i) => <li key={i}><b>{f.name}</b>{f.priority ? <span className="tiny muted"> · {f.priority}</span> : null}{f.why ? <span className="muted"> — {f.why}</span> : null}</li>)}</ul></Section>
      <Section title="定价思路">{b.pricing_idea}</Section>
      <Section title="竞品">{b.competitors.length ? <ul style={{ margin: 0, paddingLeft: 18 }}>{b.competitors.map((c, i) => <li key={i}><b>{c.name}</b>{c.weakness ? <span className="muted"> — {c.weakness}</span> : null}</li>)}</ul> : <span className="muted">索引中没有</span>}</Section>
      <Section title="差异化">{b.differentiation}</Section>
      <Section title="技术难度">{b.technical_difficulty}</Section>
      <Section title="推荐技术栈">{list(b.recommended_stack)}</Section>
      <Section title="上市路径">{list(b.go_to_market)}</Section>
      <Section title="验证计划">{list(b.validation_plan)}</Section>
    </div>
  )
}
