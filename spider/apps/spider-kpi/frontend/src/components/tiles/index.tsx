import { CSSProperties, ReactNode, useMemo } from 'react'
import { Link } from 'react-router-dom'

// Classify an href as internal (SPA route) vs external (real link).
// Internal paths start with '/' and don't have a protocol; those should
// render <Link to="..."> so react-router does client-side navigation
// instead of doing a full page reload.
function _isInternal(href: string): boolean {
  return href.startsWith('/') && !href.startsWith('//')
}

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
    if (_isInternal(href)) {
      return (
        <Link to={href} style={{ ...commonStyle, textDecoration: 'none' }}>
          {inner}
        </Link>
      )
    }
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
    if (_isInternal(href)) return <Link to={href} style={{ ...commonStyle, textDecoration: 'none' }}>{inner}</Link>
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
    if (_isInternal(href)) return <Link to={href} style={{ ...commonStyle, textDecoration: 'none' }}>{inner}</Link>
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

// ─── SparklineHero ────────────────────────────────────────────────────
// Big hero card: caption, primary value, delta, large-area sparkline.
// Used on the executive dashboard for revenue, fleet headline charts, etc.

type SparklineHeroProps = {
  title: string
  primaryValue: string
  secondaryValue?: string     // e.g. "$8,430 prior 7d"
  delta?: string
  deltaDir?: 'up' | 'down' | 'flat'
  upIsGood?: boolean
  values: number[]
  /** Optional horizontal reference line at this value (e.g. a benchmark). */
  benchmark?: number
  benchmarkLabel?: string
  state?: TileState           // border + sparkline color
  height?: number
  href?: string
  onClick?: () => void
  subtitle?: string           // small gray explainer
  icon?: string
}

export function SparklineHero({
  title, primaryValue, secondaryValue,
  delta, deltaDir = 'flat', upIsGood = true,
  values, benchmark, benchmarkLabel,
  state = 'info', height = 80,
  href, onClick, subtitle, icon,
}: SparklineHeroProps) {
  const color = STATE_COLOR[state]

  const deltaColor = !delta || deltaDir === 'flat'
    ? 'var(--muted)'
    : (deltaDir === 'up') === upIsGood ? STATE_COLOR.good : STATE_COLOR.bad
  const deltaArrow = deltaDir === 'up' ? '▲' : deltaDir === 'down' ? '▼' : ''

  const width = 440
  const sparkHeight = height
  const { linePath, areaPath, benchmarkY } = useMemo(() => {
    if (!values || values.length === 0) return { linePath: '', areaPath: '', benchmarkY: null as null | number }
    const min = Math.min(...values, benchmark ?? Infinity)
    const max = Math.max(...values, benchmark ?? -Infinity)
    const range = (max - min) || 1
    const step = width / Math.max(values.length - 1, 1)
    const pts = values.map((v, i) => [i * step, sparkHeight - ((v - min) / range) * sparkHeight] as [number, number])
    const line = pts.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ')
    const area = `${line} L ${pts[pts.length - 1][0].toFixed(1)} ${sparkHeight} L 0 ${sparkHeight} Z`
    const benchY = benchmark != null ? sparkHeight - ((benchmark - min) / range) * sparkHeight : null
    return { linePath: line, areaPath: area, benchmarkY: benchY }
  }, [values, benchmark, width, sparkHeight])

  const interactive = !!(onClick || href)
  const commonStyle: CSSProperties = {
    padding: '14px 16px 10px',
    background: STATE_BG[state],
    borderRadius: 10,
    borderLeft: `3px solid ${color}`,
    cursor: interactive ? 'pointer' : 'default',
    textAlign: 'left',
    color: 'inherit',
    font: 'inherit',
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
    transition: 'transform 80ms ease',
    width: '100%',
    border: 'none',
  }

  const inner = (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.4 }}>
            {icon && <span style={{ marginRight: 6 }}>{icon}</span>}{title}
          </div>
          {subtitle && <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 1 }}>{subtitle}</div>}
        </div>
        {delta && (
          <span style={{ fontSize: 12, color: deltaColor, fontWeight: 600 }}>
            {deltaArrow} {delta}
          </span>
        )}
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginTop: 2 }}>
        <span style={{ fontSize: 32, fontWeight: 700, lineHeight: 1, color }}>{primaryValue}</span>
        {secondaryValue && <span style={{ fontSize: 12, color: 'var(--muted)' }}>{secondaryValue}</span>}
      </div>
      {values && values.length > 1 && (
        <svg width="100%" viewBox={`0 0 ${width} ${sparkHeight}`} preserveAspectRatio="none" style={{ marginTop: 8, height: sparkHeight, display: 'block' }} aria-hidden="true">
          {areaPath && <path d={areaPath} fill={color} opacity={0.14} />}
          {benchmarkY != null && (
            <>
              <line x1={0} y1={benchmarkY} x2={width} y2={benchmarkY} stroke="rgba(255,255,255,0.22)" strokeDasharray="3 4" strokeWidth={1} />
              {benchmarkLabel && (
                <text x={width - 4} y={benchmarkY - 3} fontSize="9" fill="rgba(255,255,255,0.45)" textAnchor="end">{benchmarkLabel}</text>
              )}
            </>
          )}
          {linePath && <path d={linePath} stroke={color} strokeWidth={2} fill="none" strokeLinejoin="round" />}
        </svg>
      )}
    </>
  )

  if (href) {
    if (_isInternal(href)) return <Link to={href} style={{ ...commonStyle, textDecoration: 'none' }}>{inner}</Link>
    return <a href={href} style={{ ...commonStyle, textDecoration: 'none' }}>{inner}</a>
  }
  if (onClick) return <button type="button" onClick={onClick} style={commonStyle}>{inner}</button>
  return <div style={commonStyle}>{inner}</div>
}

// ─── AnomalyBar ────────────────────────────────────────────────────────
// Compact horizontal z-score visual. Severity-colored bar that extends
// from a centered baseline (zero) either left (low anomaly) or right
// (high anomaly). Scale clamps at ±6 for readability.

type AnomalyBarProps = {
  metric: string
  direction: 'high' | 'low'
  severity: TileState
  zScore: number
  businessDate: string
  summary?: string
  onClick?: () => void
  href?: string
}

export function AnomalyBar({ metric, direction, severity, zScore, businessDate, summary, onClick, href }: AnomalyBarProps) {
  const color = STATE_COLOR[severity]
  // Center bar at 50%, scale abs(z) / 6 to find offset
  const pct = Math.min(Math.abs(zScore) / 6, 1)
  const barWidth = pct * 48            // up to 48% of track (half-bar max)
  const fromLeft = direction === 'low' ? 50 - barWidth : 50

  const interactive = !!(onClick || href)
  const commonStyle: CSSProperties = {
    padding: '10px 14px',
    background: STATE_BG[severity],
    borderRadius: 8,
    borderLeft: `3px solid ${color}`,
    cursor: interactive ? 'pointer' : 'default',
    textAlign: 'left',
    color: 'inherit',
    font: 'inherit',
    width: '100%',
    border: 'none',
    display: 'block',
  }

  const inner = (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
        <span style={{ fontSize: 12, fontWeight: 600 }}>
          {metric.replace(/_/g, ' ')}{' '}
          <span style={{ fontSize: 10, color, fontWeight: 700, textTransform: 'uppercase', marginLeft: 4 }}>
            {direction}
          </span>
        </span>
        <span style={{ fontSize: 11, color: 'var(--muted)' }}>
          {businessDate} · z={zScore >= 0 ? '+' : ''}{zScore.toFixed(1)}
        </span>
      </div>
      {/* Centered-baseline bar visual */}
      <div style={{ position: 'relative', height: 6, background: 'rgba(255,255,255,0.06)', borderRadius: 3 }}>
        <div
          style={{
            position: 'absolute',
            top: 0,
            bottom: 0,
            left: `${fromLeft}%`,
            width: `${barWidth}%`,
            background: color,
            borderRadius: 3,
          }}
        />
        <div
          style={{
            position: 'absolute',
            top: -2,
            bottom: -2,
            left: '50%',
            width: 1,
            background: 'rgba(255,255,255,0.3)',
          }}
        />
      </div>
      {summary && <p style={{ fontSize: 11, margin: '6px 0 0', color: 'var(--muted)', lineHeight: 1.35 }}>{summary}</p>}
    </>
  )

  if (href) {
    if (_isInternal(href)) return <Link to={href} style={{ ...commonStyle, textDecoration: 'none' }}>{inner}</Link>
    return <a href={href} style={{ ...commonStyle, textDecoration: 'none' }}>{inner}</a>
  }
  if (onClick) return <button type="button" onClick={onClick} style={commonStyle}>{inner}</button>
  return <div style={commonStyle}>{inner}</div>
}

// ─── DailyHeatmap ──────────────────────────────────────────────────────
// GitHub-contributions-style calendar grid. One cell per day, color
// intensity = value. Useful for WISMO (days with tickets) or any
// count-per-day metric. Caller supplies an array of {date, value}.

type DailyCell = { date: string; value: number }

type DailyHeatmapProps = {
  /** Days in chronological order (oldest → newest). */
  days: DailyCell[]
  /** Max bucket value for saturation scaling. Clamped values above this
   *  render at full intensity. Auto-picked if not given. */
  maxValue?: number
  /** Color for non-zero cells. Cell with value 0 uses a muted track color. */
  color?: string
  /** Cell square size in px. */
  cellSize?: number
  /** Render weeks as columns (Sun-top ↓). */
  orientation?: 'weeks-as-cols' | 'linear-row'
  /** Optional tooltip label formatter. */
  labelFormatter?: (cell: DailyCell) => string
}

export function DailyHeatmap({
  days,
  maxValue,
  color = '#ef4444',
  cellSize = 12,
  orientation = 'weeks-as-cols',
  labelFormatter,
}: DailyHeatmapProps) {
  if (!days || days.length === 0) return null
  const max = maxValue ?? Math.max(1, ...days.map(d => d.value))

  const cellFor = (d: DailyCell) => {
    if (d.value <= 0) {
      return { bg: 'rgba(255, 255, 255, 0.05)', intensity: 0 }
    }
    const intensity = Math.min(d.value / max, 1)
    // Step intensity into 4 buckets for clearer visual banding
    const step = intensity >= 0.75 ? 1 : intensity >= 0.5 ? 0.75 : intensity >= 0.25 ? 0.5 : 0.3
    return { bg: color, intensity: step }
  }

  if (orientation === 'linear-row') {
    return (
      <div style={{ display: 'flex', gap: 2, alignItems: 'center' }}>
        {days.map(d => {
          const { bg, intensity } = cellFor(d)
          const title = labelFormatter ? labelFormatter(d) : `${d.date}: ${d.value}`
          return (
            <div
              key={d.date}
              title={title}
              style={{
                width: cellSize,
                height: cellSize,
                background: bg,
                opacity: intensity === 0 ? 1 : intensity,
                borderRadius: 2,
                flexShrink: 0,
              }}
            />
          )
        })}
      </div>
    )
  }

  // weeks-as-cols: build a grid with rows = weekday (Sun 0 … Sat 6)
  // and columns = weeks. Leading blank cells for the first week's
  // non-Sunday start offset.
  const firstWeekday = new Date(days[0].date + 'T00:00:00Z').getUTCDay()
  const padded: (DailyCell | null)[] = Array(firstWeekday).fill(null)
  padded.push(...days)
  while (padded.length % 7 !== 0) padded.push(null)

  const weekCount = padded.length / 7
  const cols: (DailyCell | null)[][] = []
  for (let w = 0; w < weekCount; w++) {
    cols.push(padded.slice(w * 7, w * 7 + 7))
  }

  return (
    <div style={{ display: 'flex', gap: 2 }}>
      {cols.map((weekCells, wi) => (
        <div key={wi} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {weekCells.map((cell, di) => {
            if (!cell) {
              return <div key={di} style={{ width: cellSize, height: cellSize }} />
            }
            const { bg, intensity } = cellFor(cell)
            const title = labelFormatter ? labelFormatter(cell) : `${cell.date}: ${cell.value}`
            return (
              <div
                key={di}
                title={title}
                style={{
                  width: cellSize,
                  height: cellSize,
                  background: bg,
                  opacity: intensity === 0 ? 1 : intensity,
                  borderRadius: 2,
                }}
              />
            )
          })}
        </div>
      ))}
    </div>
  )
}

// ─── DivisionTile ──────────────────────────────────────────────────────
// Larger tile for the division drill grid. Icon + name + status dot +
// 1-2 key numbers + "Open →" affordance.

type DivisionTileProps = {
  name: string
  icon: string
  href: string
  state: TileState
  primary?: string            // big headline number, e.g. "287 devices"
  secondary?: string          // smaller line, e.g. "4 anomalies open"
  /** Whether to render the pulsing status dot. */
  showDot?: boolean
}

export function DivisionTile({ name, icon, href, state, primary, secondary, showDot = true }: DivisionTileProps) {
  const color = STATE_COLOR[state]
  const Wrapper: any = _isInternal(href) ? Link : 'a'
  const wrapperProps = _isInternal(href) ? { to: href } : { href }
  return (
    <Wrapper
      {...wrapperProps}
      style={{
        display: 'flex',
        flexDirection: 'column',
        padding: '14px 16px',
        borderRadius: 10,
        background: STATE_BG[state],
        borderLeft: `3px solid ${color}`,
        textDecoration: 'none',
        color: 'inherit',
        minHeight: 110,
        justifyContent: 'space-between',
        transition: 'transform 80ms ease, background 80ms ease',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
        <span style={{ fontSize: 14, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 18 }}>{icon}</span>
          {name}
        </span>
        {showDot && (
          <span
            style={{
              width: 9,
              height: 9,
              borderRadius: '50%',
              background: color,
              boxShadow: state === 'bad' ? `0 0 8px ${color}` : undefined,
              animation: state === 'bad' ? 'pulse-alert 1.4s ease-in-out infinite' : undefined,
            }}
          />
        )}
      </div>
      {primary && <div style={{ fontSize: 20, fontWeight: 700, color, lineHeight: 1.1 }}>{primary}</div>}
      {secondary && <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>{secondary}</div>}
      <div style={{ marginTop: 8, fontSize: 11, color: 'var(--muted)', display: 'flex', justifyContent: 'flex-end' }}>
        Open →
      </div>
    </Wrapper>
  )
}

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
