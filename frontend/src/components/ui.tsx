import { renderMarkdown } from '../lib/markdown'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import type { DataMode, Opportunity } from '../lib/api'
import { DIFFICULTY, DIMENSION_LABEL, OPP_STATUS_NAME, PERSONA_NAME, STAGE_NAME, ago, zh } from '../lib/format'
import { Icon, type IconName } from './icons'

export function ModeBadge({ mode, small }: { mode?: DataMode | string | null; small?: boolean }) {
  const m = (mode ?? 'mock') as string
  const label = m === 'live' ? '实时' : m === 'mixed' ? '混合' : m === 'manual' ? '手动' : '演示'
  const title = m === 'live' ? '来自真实来源' : m === 'mixed' ? '真实与演示数据混合' : m === 'manual' ? '手动添加' : '演示数据（虚构），不是真实信息'
  return <span className={`badge ${m === 'manual' ? 'neutral' : m} ${small ? 'xs' : ''}`} title={title}>{label}</span>
}

export function Badge({ children, tone = 'neutral', small }: { children: React.ReactNode; tone?: 'neutral' | 'accent' | 'good' | 'warn' | 'bad'; small?: boolean }) {
  return <span className={`badge ${tone} ${small ? 'xs' : ''}`}>{children}</span>
}

export function StageBadge({ stage }: { stage?: string | null }) {
  const tone = stage === 'emerging' ? 'good' : stage === 'growing' ? 'accent' : stage === 'fading' ? 'bad' : 'neutral'
  return <Badge tone={tone}>{zh(STAGE_NAME, stage)}</Badge>
}

export function StatusBadge({ status }: { status: string }) {
  const tone = ['validated', 'building'].includes(status) ? 'good' : ['promising', 'researching'].includes(status) ? 'accent' : ['rejected', 'archived'].includes(status) ? 'bad' : 'neutral'
  return <Badge tone={tone}>{zh(OPP_STATUS_NAME, status)}</Badge>
}

export function ScoreRing({ value, label }: { value: number; label?: string }) {
  return (
    <div style={{ textAlign: 'right' }}>
      <div className="score-big">{Math.round(value)}</div>
      {label && <div className="tiny muted">{label}</div>}
    </div>
  )
}

export function Bar({ value }: { value: number }) {
  return <div className="bar"><span style={{ width: `${Math.max(0, Math.min(100, value))}%` }} /></div>
}

export function Sparkline({ data, width = 120, height = 28 }: { data: number[]; width?: number; height?: number }) {
  const max = Math.max(1, ...data)
  const step = data.length > 1 ? width / (data.length - 1) : width
  const points = data.map((v, i) => `${(i * step).toFixed(1)},${(height - (v / max) * (height - 2) - 1).toFixed(1)}`).join(' ')
  return (
    <svg className="spark" width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden>
      <polyline points={points} fill="none" stroke="var(--accent)" strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  )
}

export function Markdown({ text }: { text?: string | null }) {
  if (!text) return null
  const html = renderMarkdown(text)
  const linked = html.replace(/\[opp:([a-z0-9]+)\]/g, (_m, id) => `<a href="/opportunities/${id}">→ 打开</a>`)
  return <div className="md" dangerouslySetInnerHTML={{ __html: linked }} />
}

export function Empty({ title, hint, action }: { title: string; hint?: string; action?: React.ReactNode }) {
  return (
    <div className="empty">
      <div style={{ fontWeight: 600, color: 'var(--fg)' }}>{title}</div>
      {hint && <div className="small" style={{ marginTop: 6 }}>{hint}</div>}
      {action && <div style={{ marginTop: 14 }}>{action}</div>}
    </div>
  )
}

export function Loading({ rows = 3 }: { rows?: number }) {
  return <Skeleton rows={rows} />
}

export function Skeleton({ rows = 3, height = 56 }: { rows?: number; height?: number }) {
  return (
    <div className="stack" style={{ gap: 8 }} aria-busy>
      {Array.from({ length: rows }).map((_, i) => <div key={i} className="skeleton" style={{ height, animationDelay: `${i * 80}ms` }} />)}
    </div>
  )
}

export function Spinner({ size = 14 }: { size?: number }) {
  return <span className="spinner" style={{ width: size, height: size }} aria-hidden />
}

export function ErrorNotice({ error }: { error: unknown }) {
  if (!error) return null
  const message = error instanceof Error ? error.message : String(error)
  return <div className="notice error">{message}</div>
}

/** Animated expand/collapse (grid-rows trick, content stays mounted). */
export function Collapsible({ open, children, className }: { open: boolean; children: React.ReactNode; className?: string }) {
  return (
    <div className={`collapsible ${open ? 'open' : ''} ${className ?? ''}`} aria-hidden={!open}>
      <div className="collapsible-inner">{children}</div>
    </div>
  )
}

/** Header row with a rotating chevron + collapsible body. */
export function Disclosure({ title, hint, right, open, onToggle, children, size = 'md' }: {
  title: React.ReactNode; hint?: React.ReactNode; right?: React.ReactNode; open: boolean; onToggle: () => void; children: React.ReactNode; size?: 'sm' | 'md'
}) {
  return (
    <div className={`disclosure ${size} ${open ? 'open' : ''}`}>
      <div className="disclosure-head">
        <button type="button" className="disclosure-btn" onClick={onToggle} aria-expanded={open}>
          <Icon name="chevronRight" size={14} className="chev" />
          <span className="disclosure-title">{title}</span>
          {hint && <span className="disclosure-hint">{hint}</span>}
        </button>
        {right && <div className="disclosure-right">{right}</div>}
      </div>
      <Collapsible open={open}>{children}</Collapsible>
    </div>
  )
}

export function useStored<T>(key: string, initial: T): [T, (v: T | ((p: T) => T)) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key)
      return raw === null ? initial : (JSON.parse(raw) as T)
    } catch {
      return initial
    }
  })
  useEffect(() => { localStorage.setItem(key, JSON.stringify(value)) }, [key, value])
  return [value, setValue]
}

export interface MenuItem { label: React.ReactNode; icon?: IconName | string; onSelect?: () => void; danger?: boolean; disabled?: boolean; hint?: string; active?: boolean; href?: string }
export type MenuEntry = MenuItem | '-'

/** Dropdown menu: fade/scale in, closes on outside click / Esc, flips up when near the bottom. */
export function Menu({ trigger, items, align = 'right', width, label }: { trigger: React.ReactNode; items: MenuEntry[]; align?: 'left' | 'right'; width?: number; label?: string }) {
  const [open, setOpen] = useState(false)
  const [up, setUp] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    function onDoc(e: MouseEvent) { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    function onKey(e: KeyboardEvent) { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDoc); document.removeEventListener('keydown', onKey) }
  }, [open])
  useLayoutEffect(() => {
    if (!open || !ref.current) return
    const rect = ref.current.getBoundingClientRect()
    setUp(window.innerHeight - rect.bottom < Math.min(320, 40 * items.length + 16))
  }, [open, items.length])
  return (
    <div className="menu-wrap" ref={ref}>
      <span onClick={() => setOpen((o) => !o)} className={`menu-trigger ${open ? 'open' : ''}`} aria-haspopup="menu" aria-expanded={open} aria-label={label}>{trigger}</span>
      {open && (
        <div className={`menu align-${align} ${up ? 'up' : ''}`} role="menu" style={width ? { minWidth: width } : undefined}>
          {items.map((it, i) => it === '-' ? <div key={i} className="menu-sep" /> : (
            <button key={i} type="button" role="menuitem" className={`menu-item ${it.danger ? 'danger' : ''} ${it.active ? 'active' : ''}`} disabled={it.disabled}
              onClick={() => { setOpen(false); if (it.href) openHref(it.href); it.onSelect?.() }}>
              {it.icon ? <Icon name={it.icon} size={14} /> : <span className="menu-icon-gap" />}
              <span className="menu-label">{it.label}</span>
              {it.active && <Icon name="check" size={13} className="menu-check" />}
              {it.hint && <span className="menu-hint">{it.hint}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function openHref(href: string) {
  const a = document.createElement('a')
  a.href = href
  a.target = '_blank'
  a.rel = 'noreferrer'
  document.body.appendChild(a)
  a.click()
  a.remove()
}

/** Compact icon-only button with a CSS tooltip. */
export function IconButton({ icon, tip, onClick, disabled, active, className, size = 15, tipSide = 'top' }: {
  icon: IconName | string; tip: string; onClick?: () => void; disabled?: boolean; active?: boolean; className?: string; size?: number; tipSide?: 'top' | 'bottom' | 'right' | 'left'
}) {
  return (
    <button type="button" className={`iconbtn ${active ? 'active' : ''} ${className ?? ''}`} onClick={onClick} disabled={disabled} data-tip={tip} data-tip-side={tipSide} aria-label={tip}>
      <Icon name={icon} size={size} />
    </button>
  )
}

/** Segmented control with a sliding highlight. */
export function Segmented<T extends string>({ value, options, onChange, small }: { value: T; options: { value: T; label: React.ReactNode; icon?: IconName | string; tip?: string }[]; onChange: (v: T) => void; small?: boolean }) {
  const idx = Math.max(0, options.findIndex((o) => o.value === value))
  return (
    <div className={`seg ${small ? 'sm' : ''}`} style={{ ['--seg-n' as string]: options.length, ['--seg-i' as string]: idx }}>
      <span className="seg-thumb" />
      {options.map((o) => (
        <button key={o.value} type="button" className={o.value === value ? 'active' : ''} onClick={() => onChange(o.value)} title={o.tip}>
          {o.icon && <Icon name={o.icon} size={13} />}{o.label}
        </button>
      ))}
    </div>
  )
}

export function OpportunityCard({ o, rank }: { o: Opportunity; rank?: number }) {
  const dims = ['pain', 'demand', 'competition', 'gap'] as const
  return (
    <Link to={`/opportunities/${o.id}`} className="card link opp-card">
      <div className="opp-head">
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="row" style={{ gap: 8, marginBottom: 4 }}>
            {rank !== undefined && <span className="faint mono">#{rank}</span>}
            <ModeBadge mode={o.data_mode} />
            <StageBadge stage={o.stage} />
            <StatusBadge status={o.status} />
          </div>
          <div className="title">{o.title}</div>
          <div className="pain">{o.core_pain}</div>
        </div>
        <ScoreRing value={o.opportunity_score} label={`置信 ${Math.round(o.confidence)}`} />
      </div>
      <div className="grid cols-4" style={{ gap: 10 }}>
        {dims.map((d) => (
          <div key={d}>
            <div className="row between tiny muted" style={{ marginBottom: 3 }}><span>{DIMENSION_LABEL[d]}</span><span className="score">{Math.round(o.scores?.[d]?.score ?? 0)}</span></div>
            <Bar value={o.scores?.[d]?.score ?? 0} />
          </div>
        ))}
      </div>
      <div className="meta">
        <span><b>{o.signal_count}</b> 条信号</span>
        <span><b>{o.unique_users}</b> 人</span>
        <span><b>{o.source_count}</b> 个来源</span>
        <span>速度 <b>×{(o.velocity ?? 0).toFixed(1)}</b></span>
        {o.competition && <span><b>{o.competition.competitor_count}</b> 个竞品</span>}
        {o.build_difficulty && <span>{DIFFICULTY[o.build_difficulty] ?? o.build_difficulty}</span>}
        <span>{zh(PERSONA_NAME, o.persona)}</span>
        <span className="faint">更新于 {ago(o.updated_at ?? o.last_seen)}</span>
      </div>
    </Link>
  )
}
