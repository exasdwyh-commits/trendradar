import { useMemo, useState } from 'react'
import { api, type Source } from '../lib/api'
import { useFetch } from '../lib/hooks'
import { ago } from '../lib/format'
import { Disclosure, ErrorNotice, Loading, ModeBadge, useStored } from '../components/ui'
import { Icon } from '../components/icons'
import { errorMessage, useToast } from '../components/toast'

const KIND_NAME: Record<string, string> = { demand: '需求', supply: '供给', story: '故事' }
const KIND_HINT: Record<string, string> = { demand: '产出用户痛点（HN / Reddit / GitHub）', supply: '构建产品索引（Product Hunt / GitHub）', story: '商业动态，供给简报（RSS / 官网）' }
const KIND_ORDER = ['story', 'demand', 'supply']

export default function Sources() {
  const { data, error, loading, reload } = useFetch<{ items: Source[] }>('/api/sources')
  const { toast } = useToast()
  const [tests, setTests] = useState<Record<string, { ok: boolean; detail: string; mode: string }>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [kind, setKind] = useState('')
  const [onlyEnabled, setOnlyEnabled] = useState(false)
  const [q, setQ] = useState('')
  const [open, setOpen] = useStored<Record<string, boolean>>('ui.sources.groups', { story: true, demand: true, supply: true })

  async function test(id: string) {
    setBusy(id)
    try {
      const r = await api.post<{ ok: boolean; detail: string; mode: string }>(`/api/sources/${id}/test`)
      setTests({ ...tests, [id]: r })
      toast(r.ok ? `${id} 测试通过` : `${id} 测试失败：${r.detail || r.mode}`, r.ok ? 'good' : 'bad')
    } catch (e) {
      toast(errorMessage(e), 'bad')
    } finally {
      setBusy(null)
    }
  }
  async function toggle(s: Source) {
    await api.post(`/api/sources/${s.id}/toggle`, { enabled: !s.enabled })
    reload()
    toast(`${s.name} 已${s.enabled ? '停用' : '启用'}`, 'good')
  }

  const groups = useMemo(() => {
    const items = (data?.items ?? []).filter((s) => (!kind || s.kind === kind) && (!onlyEnabled || s.enabled) && (!q || `${s.name} ${s.id} ${s.adapter} ${s.note ?? ''}`.toLowerCase().includes(q.toLowerCase())))
    return KIND_ORDER.map((k) => ({ kind: k, items: items.filter((s) => s.kind === k) })).filter((g) => g.items.length)
  }, [data, kind, onlyEnabled, q])
  const counts = useMemo(() => {
    const c: Record<string, { total: number; enabled: number }> = {}
    for (const s of data?.items ?? []) { c[s.kind] = c[s.kind] ?? { total: 0, enabled: 0 }; c[s.kind].total++; if (s.enabled) c[s.kind].enabled++ }
    return c
  }, [data])

  return (
    <>
      <div className="page-head"><div><h1>信源</h1><div className="sub">需求信源产出用户痛点，供给信源构建产品索引，故事信源供给简报。「模式」显示实际运行的是真实接口还是内置演示数据。</div></div></div>
      {error && <ErrorNotice error={error} />}
      {loading && !data && <Loading rows={6} />}
      {data && (
        <>
          <div className="row" style={{ marginBottom: 14 }}>
            <div className="tabs">
              <button className={kind === '' ? 'active' : ''} onClick={() => setKind('')}>全部 {data.items.length}</button>
              {KIND_ORDER.filter((k) => counts[k]).map((k) => <button key={k} className={kind === k ? 'active' : ''} onClick={() => setKind(k)}>{KIND_NAME[k]} {counts[k].enabled}/{counts[k].total}</button>)}
            </div>
            <div className="search" style={{ maxWidth: 240, flex: 1 }}><Icon name="search" size={14} /><input className="input sm" placeholder="搜索信源" value={q} onChange={(e) => setQ(e.target.value)} /></div>
            <label className="small muted row nowrap" style={{ gap: 6, cursor: 'pointer' }}><input type="checkbox" className="toggle" checked={onlyEnabled} onChange={(e) => setOnlyEnabled(e.target.checked)} /> 只看启用</label>
          </div>
          {groups.map((g) => {
            const isOpen = open[g.kind] ?? true
            return (
              <section key={g.kind} className="brief-section">
                <Disclosure open={isOpen} onToggle={() => setOpen({ ...open, [g.kind]: !isOpen })} title={`${KIND_NAME[g.kind]}信源`}
                  hint={<>{g.items.filter((s) => s.enabled).length}/{g.items.length} 启用<span className="hide-md" style={{ marginLeft: 10 }}>{KIND_HINT[g.kind]}</span></>}>
                  <div className="card table-wrap">
                    <table className="table">
                      <thead><tr><th>信源</th><th>模式</th><th>启用</th><th>产出</th><th>上次运行</th><th>健康</th><th /></tr></thead>
                      <tbody>
                        {g.items.map((s) => {
                          const t = tests[s.id]
                          return (
                            <tr key={s.id} style={{ opacity: s.enabled ? 1 : .6 }}>
                              <td><div style={{ fontWeight: 500 }}>{s.name}</div><div className="tiny muted mono">{s.id} · {s.adapter}{s.note ? ` · ${s.note}` : ''}</div></td>
                              <td><ModeBadge mode={s.mode} /></td>
                              <td><input type="checkbox" className="toggle" checked={!!s.enabled} onChange={() => toggle(s)} /></td>
                              <td style={{ whiteSpace: 'nowrap' }}>{s.kind === 'supply' ? `${s.products} 个产品` : <>{s.signals} <span className="faint">/ 7 天 {s.signals_7d}</span></>}</td>
                              <td className="small muted" style={{ whiteSpace: 'nowrap' }}>{s.last_attempt_at ? <>{ago(s.last_attempt_at)} <span className="faint">· {s.last_item_count} 条 · {s.latency_ms ?? 0} ms</span></> : '从未'}</td>
                              <td className="small">{s.last_error ? <span className="badge bad" title={s.last_error}>连续失败 {s.consecutive_failures} 次</span> : s.last_success_at ? <span className="badge good">正常</span> : <span className="muted">—</span>}{t && <div className={`tiny ${t.ok ? 'muted' : ''}`} style={{ color: t.ok ? undefined : 'var(--red)' }}>{t.ok ? '测试通过' : '测试失败'} · {t.detail || t.mode}</div>}</td>
                              <td><button className={`btn sm ${busy === s.id ? 'loading' : ''}`} disabled={busy === s.id} onClick={() => test(s.id)}>测试</button></td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                </Disclosure>
              </section>
            )
          })}
          {groups.length === 0 && <div className="empty">没有匹配的信源</div>}
        </>
      )}
      <div className="notice info" style={{ marginTop: 16 }}>信源在 <code>config/sources.yml</code> 中声明。Product Hunt 配置 <code>PRODUCTHUNT_TOKEN</code>（GraphQL v2）后走真实接口，否则回退演示数据；Reddit 需要 <code>REDDIT_ENABLED=true</code> 与 User-Agent；商业信源为 RSS / 官网抓取，无需密钥。</div>
    </>
  )
}
