import { useState } from 'react'
import type { Opportunity } from '../lib/api'
import { useFetch } from '../lib/hooks'
import { OPP_STATUS_NAME, PERSONA_NAME, titleCase, zh } from '../lib/format'
import { Empty, ErrorNotice, Loading, OpportunityCard } from '../components/ui'

interface Resp { items: Opportunity[]; total: number; facets: Record<string, { value: string; n: number }[]> }

export default function Opportunities() {
  const [status, setStatus] = useState('')
  const [persona, setPersona] = useState('')
  const [category, setCategory] = useState('')
  const [sort, setSort] = useState('opportunity_score')
  const [q, setQ] = useState('')
  const params = new URLSearchParams()
  if (status) params.set('status', status)
  if (persona) params.set('persona', persona)
  if (category) params.set('category', category)
  if (q) params.set('q', q)
  params.set('sort', sort)
  const { data, error, loading } = useFetch<Resp>(`/api/opportunities?${params.toString()}`)
  return (
    <>
      <div className="page-head">
        <div><h1>产品机会</h1><div className="sub">每个痛点簇对应一张机会卡，随证据积累就地更新。</div></div>
      </div>
      <div className="row" style={{ marginBottom: 16 }}>
        <input className="input" style={{ maxWidth: 260 }} placeholder="搜索标题或痛点…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">全部状态</option>
          {(data?.facets.status ?? []).map((f) => <option key={f.value} value={f.value}>{zh(OPP_STATUS_NAME, f.value)} ({f.n})</option>)}
        </select>
        <select className="input" value={persona} onChange={(e) => setPersona(e.target.value)}>
          <option value="">全部人群</option>
          {(data?.facets.persona ?? []).filter((f) => f.value).map((f) => <option key={f.value} value={f.value}>{zh(PERSONA_NAME, f.value)} ({f.n})</option>)}
        </select>
        <select className="input" value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">全部类别</option>
          {(data?.facets.category ?? []).filter((f) => f.value).map((f) => <option key={f.value} value={f.value}>{titleCase(f.value)} ({f.n})</option>)}
        </select>
        <select className="input" value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="opportunity_score">排序：评分</option>
          <option value="growth">排序：增长</option>
          <option value="confidence">排序：置信度</option>
          <option value="last_seen">排序：最近出现</option>
          <option value="first_seen">排序：最新</option>
          <option value="signal_count">排序：信号数</option>
        </select>
        <span className="small muted">{data ? `${data.total} 条` : ''}</span>
      </div>
      {error && <ErrorNotice error={error} />}
      {loading && !data && <Loading />}
      {data && data.items.length === 0 && <Empty title="没有匹配的机会" hint="调整筛选条件，或运行流水线生成更多。" />}
      {data && <div className="grid cols-2">{data.items.map((o) => <OpportunityCard key={o.id} o={o} />)}</div>}
    </>
  )
}
