import { Link, useParams } from 'react-router-dom'
import { useFetch } from '../lib/hooks'
import { fmtDate } from '../lib/format'
import { Badge, ErrorNotice, Loading, ModeBadge } from '../components/ui'

interface Product {
  id: string; name: string; tagline?: string; description?: string; url: string; website?: string; votes: number; comments: number; rating?: number; review_count?: number; launched_at?: string
  pricing?: string; pricing_origin?: string; origin: string; source_id: string; categories: string[]; makers: { name?: string; username?: string }[]; comment_samples: string[]
  insights?: { pros: string[]; cons: string[]; complaints: string[]; review_summary?: string; derived_from: string; sample_size: number; generated_by: string } | null
  clusters: { id: string; label: string; product_count: number; maturity: string }[]
  solves: { id: string; label: string; weight: number }[]
}

export default function ProductPage() {
  const { id } = useParams()
  const { data: p, error, loading } = useFetch<Product>(`/api/products/${id}`)
  if (loading && !p) return <Loading />
  if (error) return <ErrorNotice error={error} />
  if (!p) return null
  return (
    <>
      <div className="page-head">
        <div>
          <div className="row" style={{ marginBottom: 6 }}><ModeBadge mode={p.origin} /><Badge>{p.source_id}</Badge>{p.categories.map((c) => <Badge key={c}>{c}</Badge>)}</div>
          <h1>{p.name}</h1>
          <div className="sub">{p.tagline}</div>
        </div>
        <div className="row"><a className="btn sm" href={p.url} target="_blank" rel="noreferrer">来源页面 ↗</a>{p.website && <a className="btn sm" href={p.website} target="_blank" rel="noreferrer">官网 ↗</a>}</div>
      </div>
      <div className="meta" style={{ marginBottom: 16 }}>
        <span><b>{p.votes}</b> 票</span><span><b>{p.comments}</b> 条评论</span>{p.rating != null && <span>★ <b>{p.rating}</b>（{p.review_count ?? 0} 条评价）</span>}
        <span>发布于 {fmtDate(p.launched_at)}</span>{p.pricing && <span>定价 <b>{p.pricing}</b>{p.pricing_origin === 'inferred' ? '（从评论推断）' : ''}</span>}
      </div>
      <div className="two-col">
        <div className="stack">
          {p.description && <div className="card pad"><p>{p.description}</p></div>}
          {p.insights && (
            <div className="card pad">
              <div className="row between"><h3>洞察</h3><span className="tiny faint">由 {p.insights.sample_size} 条评论推导 · {p.insights.generated_by}</span></div>
              {p.insights.review_summary && <p className="muted small" style={{ marginTop: 6 }}>{p.insights.review_summary}</p>}
              <div className="grid cols-2 small" style={{ marginTop: 10 }}>
                <div><div className="tiny muted">优点</div>{p.insights.pros.map((x) => <div key={x}>+ {x}</div>)}</div>
                <div><div className="tiny muted">缺点 / 抱怨</div>{[...p.insights.cons, ...p.insights.complaints.filter((c) => !p.insights!.cons.includes(c))].map((x) => <div key={x}>− {x}</div>)}</div>
              </div>
            </div>
          )}
          {p.comment_samples.length > 0 && <div className="card pad"><h3 style={{ marginBottom: 8 }}>评论样本</h3><div className="stack" style={{ gap: 6 }}>{p.comment_samples.map((c, i) => <div key={i} className="quote small">{c}</div>)}</div></div>}
        </div>
        <div className="stack">
          <div className="card pad"><h3 style={{ marginBottom: 8 }}>对应的痛点簇</h3>{p.solves.length === 0 ? <div className="small muted">尚未关联到任何已分析的痛点簇。</div> : p.solves.map((s) => <div key={s.id} className="small"><Link to={`/clusters/${s.id}`}>{s.label}</Link> <span className="tiny muted">相似度 {s.weight.toFixed(2)}</span></div>)}</div>
          <div className="card pad"><h3 style={{ marginBottom: 8 }}>解决方案簇</h3>{p.clusters.length === 0 ? <div className="small muted">—</div> : p.clusters.map((c) => <div key={c.id} className="small">{c.label} <span className="tiny muted">· {c.product_count} 个产品 · {c.maturity}</span></div>)}</div>
          {p.makers.length > 0 && <div className="card pad"><h3 style={{ marginBottom: 8 }}>开发者</h3>{p.makers.map((m, i) => <div key={i} className="small">{m.name ?? m.username}</div>)}</div>}
        </div>
      </div>
    </>
  )
}
