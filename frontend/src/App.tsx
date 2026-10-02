import { lazy, Suspense, useEffect, useState } from 'react'
import { NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { useFetch, useTheme } from './lib/hooks'
import { Icon, type IconName } from './components/icons'
import { Collapsible, IconButton, Loading, useStored } from './components/ui'
import { ToastProvider } from './components/toast'
import { RouteBoundary } from './components/RouteBoundary'

const Brief = lazy(() => import('./pages/Brief'))
const Workbench = lazy(() => import('./pages/Workbench'))
const Studio = lazy(() => import('./pages/Studio'))
const Editor = lazy(() => import('./pages/Editor'))
const Materials = lazy(() => import('./pages/Materials'))
const Publish = lazy(() => import('./pages/Publish'))
const Today = lazy(() => import('./pages/Today'))
const Radar = lazy(() => import('./pages/Radar'))
const Explore = lazy(() => import('./pages/Explore'))
const Opportunities = lazy(() => import('./pages/Opportunities'))
const OpportunityDetail = lazy(() => import('./pages/OpportunityDetail'))
const Ask = lazy(() => import('./pages/Ask'))
const Sources = lazy(() => import('./pages/Sources'))
const Jobs = lazy(() => import('./pages/Jobs'))
const SettingsPage = lazy(() => import('./pages/Settings'))
const ClusterPage = lazy(() => import('./pages/Cluster'))
const ProductPage = lazy(() => import('./pages/Product'))
const SignalPage = lazy(() => import('./pages/Signal'))

interface Health { ok: boolean; version: string; counts: Record<string, number>; providers: { llm: Record<string, { enabled: boolean }>; embedding: { degraded: boolean } } }

interface NavItem { to: string; label: string; icon: IconName; end?: boolean; count?: number; soft?: boolean }
interface NavGroup { id: string; label: string | null; items: NavItem[] }

export default function App() {
  const { theme, toggle } = useTheme()
  const location = useLocation()
  const { data: health } = useFetch<Health>('/api/health', [location.key])
  const [viewportWidth, setViewportWidth] = useState(() => window.innerWidth)
  useEffect(() => {
    const resize = () => setViewportWidth(window.innerWidth)
    window.addEventListener('resize', resize)
    return () => window.removeEventListener('resize', resize)
  }, [])
  const llmReady = health ? Object.values(health.providers.llm).some((s) => s.enabled) : false
  const editing = /^\/studio\/[^/]+/.test(location.pathname)
  const [collapsedPref, setCollapsedPref] = useStored<boolean | null>('ui.sidebar.collapsed', null)
  const [groups, setGroups] = useStored<Record<string, boolean>>('ui.nav.groups', { tools: false, system: false })
  // default: rail in the editor and on narrow laptops, full sidebar elsewhere; an explicit choice wins
  const autoCollapse = editing || viewportWidth < 1200
  const collapsed = viewportWidth > 960 && (collapsedPref ?? autoCollapse)

  useEffect(() => { document.title = 'TrendRadar 写作台' }, [])

  const c = health?.counts ?? {}
  const nav: NavGroup[] = [
    { id: 'core', label: null, items: [
      { to: '/', label: '工作台', icon: 'panel', end: true },
      { to: '/brief', label: '选题简报', icon: 'inbox', count: c.brief_new },
      { to: '/studio', label: '稿件', icon: 'pen', count: c.documents, soft: true },
      { to: '/materials', label: '素材库', icon: 'library', count: c.materials, soft: true },
      { to: '/publish', label: '发布中心', icon: 'send' },
    ] },
    { id: 'tools', label: '扩展工具', items: [
      { to: '/today', label: '今日精选', icon: 'sparkles' },
      { to: '/radar', label: '痛点雷达', icon: 'radar' },
      { to: '/opportunities', label: '产品机会', icon: 'target', count: c.opportunities, soft: true },
      { to: '/explore', label: '探索', icon: 'compass' },
      { to: '/ask', label: '问答', icon: 'chat' },
    ] },
    { id: 'system', label: '系统', items: [
      { to: '/sources', label: '信源', icon: 'database' },
      { to: '/jobs', label: '任务', icon: 'clock' },
      { to: '/settings', label: '设置', icon: 'settings' },
    ] },
  ]

  return (
    <ToastProvider>
      <div className={`shell ${editing ? 'editing' : ''} ${collapsed ? 'collapsed' : ''}`}>
        <aside className="sidebar">
          <div className="brand"><span className="dot" /><span className="label">TrendRadar 写作台</span></div>
          <div className="sidebar-toggle">
            <IconButton icon={collapsed ? 'chevronRight' : 'chevronLeft'} tip={collapsed ? '展开侧栏' : '收起侧栏'} tipSide="right" onClick={() => setCollapsedPref(!collapsed)} />
          </div>
          <nav className="nav">
            {nav.map((g) => {
              const open = g.label ? (groups[g.id] ?? true) : true
              return (
                <div key={g.id}>
                  {g.label && (
                    <button type="button" className={`nav-group-head ${open ? 'open' : ''}`} onClick={() => setGroups({ ...groups, [g.id]: !open })} title={collapsed ? g.label : undefined}>
                      <Icon name="chevronRight" size={11} className="chev" /><span className="label">{g.label}</span>
                    </button>
                  )}
                  <Collapsible open={open || collapsed}>
                    <div className="nav-items">
                      {g.items.map((it) => (
                        <NavLink key={it.to} to={it.to} end={it.end} aria-label={`${it.label}${it.count ? ` ${it.count}` : ''}`} data-tip={collapsed ? it.label : undefined} data-tip-side="right" data-count={it.count && !it.soft ? it.count : undefined}>
                          <Icon name={it.icon} size={17} />
                          <span className="label">{it.label}</span>
                          {it.count ? <span className={`count ${it.soft ? 'soft' : ''}`}>{it.count}</span> : null}
                        </NavLink>
                      ))}
                    </div>
                  </Collapsible>
                </div>
              )
            })}
          </nav>
          <div className="foot">
            {health && (
              <div className="tiny muted label">
                {llmReady ? <span className="badge live">已配置模型</span> : <span className="badge mock" title="未配置任何模型：简报按规则评分，AI 写作仅对演示素材可用">未配置模型 · 规则模式</span>}
                {health.providers.embedding.degraded && <div style={{ marginTop: 6 }}>本地向量（降级）</div>}
              </div>
            )}
            <div className="row nowrap" style={{ gap: 6 }}>
              <IconButton icon={theme === 'dark' ? 'sun' : 'moon'} tip={theme === 'dark' ? '浅色主题' : '深色主题'} tipSide="right" onClick={toggle} className="bordered" />
              <span className="tiny faint label">v{health?.version ?? '…'}</span>
            </div>
          </div>
        </aside>
        <main className={`main ${editing ? 'wide' : ''}`}>
          <RouteBoundary key={location.pathname}>
            <Suspense fallback={<div role="status" aria-live="polite"><p className="muted">正在加载页面…</p><Loading /></div>}>
              <Routes>
                <Route path="/" element={<Workbench />} />
                <Route path="/brief" element={<Brief />} />
                <Route path="/studio" element={<Studio />} />
                <Route path="/studio/:id" element={<Editor key={location.pathname} />} />
                <Route path="/materials" element={<Materials />} />
                <Route path="/publish" element={<Publish />} />
                <Route path="/today" element={<Today />} />
                <Route path="/radar" element={<Radar />} />
                <Route path="/explore" element={<Explore />} />
                <Route path="/explore/:id" element={<Explore />} />
                <Route path="/opportunities" element={<Opportunities />} />
                <Route path="/opportunities/:id" element={<OpportunityDetail />} />
                <Route path="/clusters/:id" element={<ClusterPage />} />
                <Route path="/products/:id" element={<ProductPage />} />
                <Route path="/signals/:id" element={<SignalPage />} />
                <Route path="/ask" element={<Ask />} />
                <Route path="/sources" element={<Sources />} />
                <Route path="/jobs" element={<Jobs />} />
                <Route path="/settings" element={<SettingsPage />} />
              </Routes>
            </Suspense>
          </RouteBoundary>
        </main>
      </div>
    </ToastProvider>
  )
}
