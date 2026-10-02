import { Link, useNavigate } from 'react-router-dom'
import { DOC_STATUS_NAME, PLATFORM_NAME, type Platform, type PublishCenter } from '../lib/api'
import { useFetch } from '../lib/hooks'
import { ago, fmtDateTime } from '../lib/format'
import { Badge, Empty, ErrorNotice, Loading, ModeBadge } from '../components/ui'

const PLATFORMS = Object.keys(PLATFORM_NAME) as Platform[]

export default function Publish() {
  const { data, error, loading } = useFetch<PublishCenter>('/api/publish')
  const navigate = useNavigate()
  return (
    <div>
      <div className="page-head">
        <div>
          <h1>发布</h1>
          <div className="sub">每篇母稿在各平台的版本与发布状态。发布仍在各平台后台完成，这里是账本。</div>
        </div>
      </div>
      <ErrorNotice error={error} />
      {loading && !data && <Loading />}
      {data && data.documents.length === 0 && <Empty title="还没有待发或已发布的稿件" hint="在编辑器里把稿件标记为「待发」，它就会出现在这里。" action={<Link className="btn" to="/studio">去创作</Link>} />}
      {data && data.documents.length > 0 && (
        <div className="card fade-in" style={{ marginBottom: 24 }}>
          <div className="table-wrap">
          <table className="table">
            <thead>
              <tr><th>稿件</th><th>状态</th>{PLATFORMS.map((p) => <th key={p} style={{ textAlign: 'center' }}>{PLATFORM_NAME[p]}</th>)}<th>更新</th></tr>
            </thead>
            <tbody>
              {data.documents.map((d) => (
                <tr key={d.id} className="link" onClick={() => navigate(`/studio/${d.id}`)}>
                  <td><div className="row" style={{ gap: 8 }}><ModeBadge mode={d.data_mode} small /><b>{d.title}</b></div></td>
                  <td><Badge tone={d.status === 'published' ? 'good' : 'warn'}>{DOC_STATUS_NAME[d.status]}</Badge></td>
                  {PLATFORMS.map((p) => {
                    const published = d.published_platforms.includes(p)
                    const has = d.variant_platforms.includes(p) || d.target_platform === p
                    return <td key={p} style={{ textAlign: 'center' }} title={published ? '已发布' : has ? '有版本，未发布' : '无版本'}><span className={`dot ${published ? 'good' : has ? 'warn' : ''}`} /></td>
                  })}
                  <td className="small muted">{ago(d.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
          <div className="tiny muted" style={{ padding: '8px 14px' }}><span className="dot good" /> 已发布　<span className="dot warn" /> 有版本未发布　<span className="dot" /> 无版本</div>
        </div>
      )}
      {data && data.publications.length > 0 && (
        <>
          <div className="section-title"><h2>发布记录</h2></div>
          <div className="card table-wrap">
            <table className="table">
              <thead><tr><th>时间</th><th>稿件</th><th>平台</th><th>链接</th><th>备注</th></tr></thead>
              <tbody>
                {data.publications.map((p) => (
                  <tr key={p.id}>
                    <td className="small mono">{fmtDateTime(p.published_at)}</td>
                    <td><Link to={`/studio/${p.document_id}`}>{p.title}</Link></td>
                    <td><Badge tone="good">{PLATFORM_NAME[p.platform]}</Badge></td>
                    <td className="small">{p.external_url ? <a href={p.external_url} target="_blank" rel="noreferrer">{p.external_url}</a> : <span className="faint">—</span>}</td>
                    <td className="small muted">{p.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
