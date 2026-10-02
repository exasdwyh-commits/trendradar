import { Link, useParams } from 'react-router-dom'
import { useFetch } from '../lib/hooks'
import { PERSONA_NAME, fmtDateTime, titleCase, zh } from '../lib/format'
import { Badge, ErrorNotice, Loading, ModeBadge } from '../components/ui'
import { looksEnglish, TranslationPanel } from '../components/translation'

interface Signal {
  id: string; external_id: string; source_id: string; adapter: string; origin: string; url: string; title: string; content: string; author?: string; created_at?: string; fetched_at: string
  lang?: string; rule_score: number; status: string; engagement: Record<string, number>; metadata: Record<string, unknown>
  classification?: { classifier: string; is_pain: number; relevance: number; persona?: string; category?: string; confidence: number; reason?: string; model?: string } | null
  pain_signal?: { problem: string; context?: string; severity?: number; frequency?: number; willingness_to_pay?: number; existing_workaround?: string; current_solution?: string; friction: string[]; evidence_quote?: string; generated_by: string } | null
  clusters: { id: string; label: string; session_id?: string | null }[]
}

export default function SignalPage() {
  const { id } = useParams()
  const { data: s, error, loading } = useFetch<Signal>(`/api/signals/${id}`)
  if (loading && !s) return <Loading />
  if (error) return <ErrorNotice error={error} />
  if (!s) return null
  return (
    <>
      <div className="page-head">
        <div>
          <div className="row" style={{ marginBottom: 6 }}><ModeBadge mode={s.origin} /><Badge>{s.source_id}</Badge><Badge>{s.status}</Badge><span className="tiny faint">rule score {s.rule_score.toFixed(2)}</span></div>
          <h1 style={{ fontSize: 18 }}>{s.title}</h1>
          <div className="sub small">{s.author && <>{s.author} · </>}{fmtDateTime(s.created_at)} · {Object.entries(s.engagement).filter(([, v]) => v).map(([k, v]) => `${v} ${k}`).join(' · ')}</div>
        </div>
        <a className="btn sm" href={s.url} target="_blank" rel="noreferrer">打开原文 ↗</a>
      </div>
      <div className="two-col">
        <div className="card pad">{looksEnglish(s.title + s.content) ? <TranslationPanel key={s.id} refType="signal" refId={s.id} originalContent={s.content} /> : <p style={{ whiteSpace: 'pre-wrap' }}>{s.content}</p>}</div>
        <div className="stack">
          {s.classification && (
            <div className="card pad">
              <h3 style={{ marginBottom: 8 }}>分类 <span className="tiny faint">来自 {s.classification.classifier}{s.classification.model ? ` · ${s.classification.model}` : ''}</span></h3>
              <dl className="kv"><dt>是否痛点</dt><dd>{s.classification.is_pain ? '是' : '否'} · 相关度 {s.classification.relevance}</dd><dt>人群</dt><dd>{zh(PERSONA_NAME, s.classification.persona)}</dd><dt>类别</dt><dd>{titleCase(s.classification.category)}</dd>{s.classification.reason && <><dt>理由</dt><dd>{s.classification.reason}</dd></>}</dl>
            </div>
          )}
          {s.pain_signal && (
            <div className="card pad">
              <h3 style={{ marginBottom: 8 }}>结构化痛点 <span className="tiny faint">来自 {s.pain_signal.generated_by}</span></h3>
              <dl className="kv">
                <dt>问题</dt><dd>{s.pain_signal.problem}</dd>
                {s.pain_signal.context && <><dt>场景</dt><dd>{s.pain_signal.context}</dd></>}
                <dt>严重度 / 频率 / 付费意愿</dt><dd>{s.pain_signal.severity ?? '—'} / {s.pain_signal.frequency ?? '—'} / {s.pain_signal.willingness_to_pay ?? '—'}</dd>
                {s.pain_signal.existing_workaround && <><dt>现有绕行方案</dt><dd>{s.pain_signal.existing_workaround}</dd></>}
                {s.pain_signal.current_solution && <><dt>当前方案</dt><dd>{s.pain_signal.current_solution}</dd></>}
                <dt>摩擦点</dt><dd>{s.pain_signal.friction.map((f) => <Badge key={f}>{titleCase(f)}</Badge>)}</dd>
                {s.pain_signal.evidence_quote && <><dt>原话</dt><dd className="quote">“{s.pain_signal.evidence_quote}”</dd></>}
              </dl>
            </div>
          )}
          <div className="card pad"><h3 style={{ marginBottom: 8 }}>所属痛点簇</h3>{s.clusters.length === 0 ? <div className="small muted">尚未聚类。</div> : s.clusters.map((c) => <div key={c.id} className="small"><Link to={`/clusters/${c.id}`}>{c.label}</Link>{c.session_id && <span className="tiny faint"> · 探索会话</span>}</div>)}</div>
          {Object.keys(s.metadata).length > 0 && <div className="card pad"><h3 style={{ marginBottom: 8 }}>元数据</h3><pre className="mono small" style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{JSON.stringify(s.metadata, null, 1)}</pre></div>}
        </div>
      </div>
    </>
  )
}
