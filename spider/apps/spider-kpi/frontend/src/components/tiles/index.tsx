import { CSSProperties, ReactNode, useMemo } from 'react'

/**
 * Car-dashboard-style visual primitives for page heroes.
 *
 *   <TileGrid>       — responsive grid wrapper
 *   <MetricTile>     — big number, optional delta arrow, color state, sparkline
 *   <GaugeTile>      — arc visualization for 0..1 metrics (cook success, CSAT %)
 *   <StatusLight>    — warning-light for binary/severity states
 *   <MiniSparkline>  — tiny inline trend line (embedded in tiles)
 *
 * Design goals:
 *   - Read-in-2-seconds density: number dominates, label is small.
 *   - Color thresholds driven by caller-supplied {good, warn, bad} bands.
 *   - Click-through: `onClick` makes the whole tile a button that typically
 *     expands a CollapsibleSection downstream.
 *   - Dark-theme native: uses CSS vars already set on the page.
 */

// ─── colors ────────────────────────────────────────────────────────────

export type TileState = 'good' | 'neutral' | 'warn' | 'bad' | 'info'

const STATE_COLOR: Record<TileState, string> = {
  good:    '#22c55e',
  neutral: '#9ca3af',
  warn:    '#f59e0b',
  bad:     '#ef4444',
  info:    '#4a7aff',
}

const STATE_BG: Record<TileState, string> = {
  good:    'rgba(34, 197, 94, 0.10)',
  neutral: 'rgba(255,255,255,0.03)',
  warn:    'rgba(245, 158, 11, 0.10)',
  bad:     'rgba(239, 68, 68, 0.12)',
  info:    'rgba(74, 122, 255, 0.10)',
}

// ─── TileGrid ──────────────────────────────────────────────────────────

type TileGridProps = {
  children: ReactNode
  /** Columns at md+ breakpoints. Caller should pass based on content density. */
  cols?: 3 | 4 | 5 | 6
  style?: CSSProperties
}

export function TileGrid({ children, cols = 4, style }: TileGridProps) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: `repeat(auto-fill, minmax(${cols >= 5 ? 160 : 190}px, 1fr))`,
        gap: 10,
        ...style,
      }}
    >
      {children}
    </div>
  )
}

// ─── MiniSparkline ─────────────────────────────────────────────────────

type SparkProps = {
  /** Array of values; only relative shape matters, not absolute range. */
  values: number[]
  width?: number
  height?: number
  color?: string
  /** If true, fills the area under the line for more visual weight. */
  filled?: boolean
}

export function MiniSparkline({ values, width = 140, height = 28, color = 'currentColor', filled = true }: SparkProps) {
  const path = useMemo(() => {
    if (!values || values.length === 0) return { line: '', area: '', dot: null as null | { x: number; y: number } }
    const min = Math.min(...values)
    const max = Math.max(...values)
    const range = (max - min) || 1
    const step = width / Math.max(values.length - 1, 1)
    const points = values.map((v, i) => {
      const x = i * step
      const y = height - ((v - min) / range) * height
      return [x, y] as [number, number]
    })
    const line = points.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ')
    const area = `${line} L ${points[points.length - 1][0].toFixed(1)} ${height} L 0 ${height} Z`
    const dot = points[points.length - 1] ? { x: points[points.length - 1][0], y: points[points.length - 1][1] } : null
    return { line, area, dot }
  }, [values, width, height])

  if (!values || values.length === 0) return null
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{ display: 'block', overflow: 'visible' }} aria-hidden="true">
      {filled && path.area && <path d={path.area} fill={color} opacity={0.18} />}
      {path.line && <path d={path.line} stroke={color} strokeWidth={1.6} fill="none" strokeLinejoin="round" strokeLinecap="round" />}
      {path.dot && <circle cx={path.dot.x} cy={path.dot.y} r={2.5} fill={color} />}
    </svg>
  )
}

// ─── MetricTile ────────────────────────────────────────────────────────

type MetricTileProps = {
  label: string
  /** Primary value. String already formatted (e.g. "68%", "$12.4k", "287"). */
  value: ReactNode
  /** Optional sub-line below the value — "of 450 orders" style. */
  sublabel?: ReactNode
  /** Threshold state driving color. */
  state?: TileState
  /** Delta vs. prior period — signed number, % or count. Caller decides interpretation. */
  delta?: string
  /** Direction of delta — 'up' shows ▲, 'down' shows ▼, 'flat' no arrow. */
  deltaDir?: 'up' | 'down' | 'flat'
  /** Is UP a good thing for this metric? (Revenue up = good; errors up = bad.) */
  upIsGood?: boolean
  /** Optional sparkline. */
  sparkline?: number[]
  /** Click → expand corresponding detail below. */
  onClick?: () => void
  /** Optional URL to navigate to. */
  href?: string
  /** Optional icon to the right of the label (emoji or symbol). */
  icon?: string
}

export function MetricTile({
  label, value, sublabel, state = 'neutral',
  delta, deltaDir = 'flat', upIsGood = true, sparkline,
  onClick, href, icon,
}: MetricTileProps) {
  const color = STATE_COLOR[state]
  const bg = STATE_BG[state]

  const deltaColor = !delta || deltaDir === 'flat'
    ? 'var(--muted)'
    : (deltaDir === 'up') === upIsGood ? STATE_COLOR.good : STATE_COLOR.bad
  const deltaArrow = deltaDir === 'up' ? '▲' : deltaDir === 'down' ? '▼' : ''

  const interactive = !!(onClick || href)
  const commonStyle: CSSProperties = {
    padding: '12px 14px',
    background: bg,
    borderRadius: 8,
    borderLeft: `3px solid ${color}`,
    cursor: interactive ? 'pointer' : 'default',
    textAlign: 'left',
    color: 'inherit',
    font: 'inherit',
    minWidth: 0,
    display: 'flex',
    flexDirection: 'column',
    justifyContent: 'space-between',
    transition: 'transform 80ms ease, background 80ms ease',
    position: 'relative',
    overflow: 'hidden',
  }

  const inner = (
    <>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
        <div style={{ fontSize: 10.5, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.4, lineHeight: 1.2 }}>
          {label}
        </div>
        {icon && <span style={{ fontSize: 14, opacity: 0.7 }}>{icon}</span>}
      </div>
      <div style={{ fontSize: 28, fontWeight: 700, lineHeight: 1.05, color: color === STATE_COLOR.neutral ? 'var(--text)' : color }}>
        {value}
      </div>
      {sublabel && (
        <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4, lineHeight: 1.35 }}>{sublabel}</div>
      )}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 8, minHeight: 18 }}>
        {delta ? (
          <span style={{ fontSize: 11, color: deltaColor, fontWeight: 600 }}>
            {deltaArrow} {delta}
          </span>
        ) : <span />}
        {sparkline && sparkline.length > 1 && (
          <div style={{ color }}>
            <MiniSparkline values={sparkline} width={90} height={22} color={color} />
          </div>
        )}
      </div>
    </>
  )

  if (href) {
    return (
      <a href={href} style={{ ...commonStyle, textDecoration: 'none' }}>
        {inner}
      </a>
    )
  }
  if (onClick) {
    return (
      <button type="button" onClick={onClick} style={{ ...commonStyle, border: 'none', width: '100%' }}>
        {inner}
      </button>
    )
  }
  return <div style={commonStyle}>{inner}</div>
}

// ─── GaugeTile ─────────────────────────────────────────────────────────

type GaugeTileProps = {
  label: string
  /** Fraction 0..1. */
  value: number
  /** Formatted display value — e.g. "68%" or "4.2 / 5". */
  display: string
  sublabel?: ReactNode
  /** Bands: value below `warn` = warn color; below `bad` = bad color; above both = good. */
  bandsAsc?: { bad: number; warn: number }
  /** Flip band logic — used when lower values are bad (e.g. error-rate). */
  invert?: boolean
  onClick?: () => void
  href?: string
}

export function GaugeTile({
  label, value, display, sublabel,
  bandsAsc = { bad: 0.6, warn: 0.8 },
  invert = false,
  onClick, href,
}: GaugeTileProps) {
  // Clamp
  const v = Math.max(0, Math.min(1, value || 0))
  const state: TileState = (() => {
    if (!invert) {
      if (v < bandsAsc.bad) return 'bad'
      if (v < bandsAsc.warn) return 'warn'
      return 'good'
    } else {
      if (v > bandsAsc.warn) return 'bad'
      if (v > bandsAsc.bad) return 'warn'
      return 'good'
    }
  })()
  const color = STATE_COLOR[state]
  const bg = STATE_BG[state]

  // Arc math: 180° sweep from left to right.
  const cx = 60, cy = 54, r = 44
  const startAng = Math.PI           // left (180°)
  const endAng = 2 * Math.PI         // right (360°/0° equivalent)
  const sweep = endAng - startAng
  const fillAng = startAng + sweep * v

  const polar = (ang: number) => [cx + r * Math.cos(ang), cy + r * Math.sin(ang)]

  const arcPath = (fromAng: number, toAng: number) => {
    const [x1, y1] = polar(fromAng)
    const [x2, y2] = polar(toAng)
    const large = toAng - fromAng > Math.PI ? 1 : 0
    return `M ${x1.toFixed(1)} ${y1.toFixed(1)} A ${r} ${r} 0 ${large} 1 ${x2.toFixed(1)} ${y2.toFixed(1)}`
  }

  const commonStyle: CSSProperties = {
    padding: '12px 14px',
    background: bg,
    borderRadius: 8,
    borderLeft: `3px solid ${color}`,
    cursor: onClick || href ? 'pointer' : 'default',
    textAlign: 'left',
    color: 'inherit',
    font: 'inherit',
    minWidth: 0,
    display: 'flex',
    flexDirection: 'column',
    transition: 'transform 80ms ease, background 80ms ease',
  }

  const inner = (
    <>
      <div style={{ fontSize: 10.5, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 2, lineHeight: 1.2 }}>
        {label}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <svg width={120} height={68} viewBox="0 0 120 68" aria-hidden="true" style={{ flexShrink: 0 }}>
          <path d={arcPath(startAng, endAng)} stroke="rgba(255,255,255,0.08)" strokeWidth={8} fill="none" strokeLinecap="round" />
          {v > 0.001 && (
            <path d={arcPath(startAng, fillAng)} stroke={color} strokeWidth={8} fill="none" strokeLinecap="round" />
          )}
        </svg>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 22, fontWeight: 700, lineHeight: 1.05, color }}>{display}</div>
          {sublabel && <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{sublabel}</div>}
        </div>
      </div>
    </>
  )

  if (href) {
    return <a href={href} style={{ ...commonStyle, textDecoration: 'none' }}>{inner}</a>
  }
  if (onClick) {
    return (
      <button type="button" onClick={onClick} style={{ ...commonStyle, border: 'none', width: '100%' }}>
        {inner}
      </button>
    )
  }
  return <div style={commonStyle}>{inner}</div>
}

// ─── StatusLight ───────────────────────────────────────────────────────

type StatusLightProps = {
  label: string
  /** Number to display center-stage (e.g. "2" critical alerts, "0" anomalies). */
  count: number
  /** If count > 0, this is the color state. If count = 0, always 'good'. */
  alertState?: TileState
  sublabel?: ReactNode
  onClick?: () => void
  href?: string
  icon?: string
}

export function StatusLight({ label, count, alertState = 'warn', sublabel, onClick, href, icon }: StatusLightProps) {
  const state: TileState = count === 0 ? 'good' : alertState
  const color = STATE_COLOR[state]
  const bg = STATE_BG[state]

  const commonStyle: CSSProperties = {
    padding: '12px 14px',
    background: bg,
    borderRadius: 8,
    borderLeft: `3px solid ${color}`,
    cursor: onClick || href ? 'pointer' : 'default',
    textAlign: 'left',
    color: 'inherit',
    font: 'inherit',
    display: 'flex',
    flexDirection: 'column',
  }

  const inner = (
    <>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
        <div style={{ fontSize: 10.5, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.4, lineHeight: 1.2 }}>
          {label}
        </div>
        {icon && <span style={{ fontSize: 14, opacity: 0.7 }}>{icon}</span>}
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
        <div style={{ fontSize: 28, fontWeight: 700, lineHeight: 1.05, color }}>{count}</div>
        {count === 0 ? (
          <span style={{ fontSize: 11, color: 'var(--muted)', fontWeight: 500 }}>all clear</span>
        ) : (
          <span
            style={{
              width: 10, height: 10, borderRadius: '50%', background: color,
              boxShadow: `0 0 10px ${color}`,
              animation: state === 'bad' ? 'pulse-alert 1.4s ease-in-out infinite' : undefined,
              display: 'inline-block',
            }}
          />
        )}
      </div>
      {sublabel && <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4, lineHeight: 1.35 }}>{sublabel}</div>}
      <style>{`@keyframes pulse-alert { 0%, 100% { opacity: 1 } 50% { opacity: 0.35 } }`}</style>
    </>
  )

  if (href) {
    return <a href={href} style={{ ...commonStyle, textDecoration: 'none' }}>{inner}</a>
  }
  if (onClick) {
    return (
      <button type="button" onClick={onClick} style={{ ...commonStyle, border: 'none', width: '100%' }}>
        {inner}
      </button>
    )
  }
  return <div style={commonStyle}>{inner}</div>
}

// ─── helper: open a collapsible by id ──────────────────────────────────

/** Call from a tile's onClick to expand a <CollapsibleSection id=id> below.
 *  Dispatches a 'spider-kpi:collapsible' event that the section listens for,
 *  then scrolls the section into view. No page reload. */
export function openSectionById(id: string) {
  try {
    window.dispatchEvent(new CustomEvent('spider-kpi:collapsible', { detail: { id, open: true } }))
    setTimeout(() => {
      const target = document.querySelector(`[data-collapsible-id="${id}"]`)
      if (target instanceof HTMLElement) {
        target.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }
    }, 60)
  } catch {
    // ignore — progressive enhancement
  }
}
