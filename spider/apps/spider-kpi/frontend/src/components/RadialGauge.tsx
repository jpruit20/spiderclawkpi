import { useMemo } from 'react'
import { motion } from 'framer-motion'

export type GaugeDirection = 'higher_better' | 'lower_better' | 'target'

export type RadialGaugeProps = {
  label: string
  displayValue: string
  value: number | null
  sparkline: number[]
  direction: GaugeDirection
  target?: number | null
  healthyLow?: number | null
  healthyHigh?: number | null
  changePct?: number | null
  rationale?: string
  category?: string
  unit?: string
  onClick?: () => void
  onHover?: (hovering: boolean) => void
}

// Map metric category to a palette accent. Intentionally understated —
// the gauge's own health color carries most of the visual weight.
const CATEGORY_ACCENTS: Record<string, string> = {
  commerce: '#10b981',
  marketing: '#f59e0b',
  cx: '#ec4899',
  fleet: '#3b82f6',
  engineering: '#8b5cf6',
  ops: '#64748b',
  unknown: '#94a3b8',
}

// Decide overall health color from value vs healthy band / direction.
function healthColor(
  value: number | null,
  direction: GaugeDirection,
  band: [number | null, number | null],
): string {
  if (value == null || Number.isNaN(value)) return '#64748b'
  const [low, high] = band
  if (direction === 'higher_better') {
    if (low != null && value >= low) return '#10b981'
    if (low != null && value >= low * 0.85) return '#f59e0b'
    return '#ef4444'
  }
  if (direction === 'lower_better') {
    if (high != null && value <= high) return '#10b981'
    if (high != null && value <= high * 1.15) return '#f59e0b'
    return '#ef4444'
  }
  // target band
  if (low != null && high != null) {
    if (value >= low && value <= high) return '#10b981'
    const slack = (high - low) * 0.15 || 0.15
    if (value >= low - slack && value <= high + slack) return '#f59e0b'
    return '#ef4444'
  }
  return '#3b82f6'
}

// Bound a value to a [0..1] position along the arc. Uses sparkline
// min/max as a reasonable default when no explicit band is provided.
function normalizedPosition(
  value: number | null,
  spark: number[],
  band: [number | null, number | null],
  target: number | null,
): number {
  if (value == null || Number.isNaN(value)) return 0
  const [low, high] = band
  let min: number
  let max: number
  if (low != null && high != null) {
    min = low * 0.5
    max = high * 1.5
  } else if (target != null) {
    min = 0
    max = target * 1.5
  } else if (spark.length) {
    min = Math.min(...spark, value) * 0.9
    max = Math.max(...spark, value) * 1.1 || 1
  } else {
    min = 0
    max = Math.max(1, value * 2)
  }
  if (max <= min) return 0.5
  const p = (value - min) / (max - min)
  return Math.max(0, Math.min(1, p))
}

export function RadialGauge({
  label, displayValue, value, sparkline, direction,
  target, healthyLow, healthyHigh, changePct,
  category, rationale, unit,
  onClick, onHover,
}: RadialGaugeProps) {
  const band: [number | null, number | null] = [healthyLow ?? null, healthyHigh ?? null]
  const color = healthColor(value, direction, band)
  const accent = CATEGORY_ACCENTS[category || 'unknown'] || '#94a3b8'
  const position = normalizedPosition(value, sparkline, band, target ?? null)

  // 270° arc spanning from -135° to +135° (bottom gap of 90°)
  const ARC_DEGREES = 270
  const START_ANGLE = 135  // starting angle in CSS terms (top-left)
  const needleAngle = START_ANGLE + position * ARC_DEGREES

  // Arc path geometry
  const r = 62
  const cx = 80
  const cy = 80
  const toRad = (d: number) => (d - 90) * (Math.PI / 180)
  const arcStart = { x: cx + r * Math.cos(toRad(START_ANGLE)), y: cy + r * Math.sin(toRad(START_ANGLE)) }
  const arcEnd = { x: cx + r * Math.cos(toRad(START_ANGLE + ARC_DEGREES)), y: cy + r * Math.sin(toRad(START_ANGLE + ARC_DEGREES)) }
  const largeArc = ARC_DEGREES > 180 ? 1 : 0
  const bgPath = `M ${arcStart.x} ${arcStart.y} A ${r} ${r} 0 ${largeArc} 1 ${arcEnd.x} ${arcEnd.y}`

  // Healthy-band arc — highlight segment on the dial
  const healthyArc = useMemo(() => {
    if (healthyLow == null && healthyHigh == null) return null
    const lowPos = normalizedPosition(healthyLow ?? 0, sparkline, band, target ?? null)
    const highPos = normalizedPosition(healthyHigh ?? (target ?? 0) * 1.2, sparkline, band, target ?? null)
    const a = START_ANGLE + lowPos * ARC_DEGREES
    const b = START_ANGLE + highPos * ARC_DEGREES
    const pA = { x: cx + r * Math.cos(toRad(a)), y: cy + r * Math.sin(toRad(a)) }
    const pB = { x: cx + r * Math.cos(toRad(b)), y: cy + r * Math.sin(toRad(b)) }
    const la = b - a > 180 ? 1 : 0
    return `M ${pA.x} ${pA.y} A ${r} ${r} 0 ${la} 1 ${pB.x} ${pB.y}`
  }, [healthyLow, healthyHigh, target, sparkline])

  // Tiny sparkline path across the bottom
  const sparkPath = useMemo(() => {
    if (!sparkline.length) return ''
    const min = Math.min(...sparkline)
    const max = Math.max(...sparkline)
    const range = max - min || 1
    const w = 140
    const h = 24
    const step = w / Math.max(1, sparkline.length - 1)
    return sparkline
      .map((v, i) => {
        const x = i * step + 10
        const y = 155 - ((v - min) / range) * h
        return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
      })
      .join(' ')
  }, [sparkline])

  const trendChar = changePct == null ? '·' : changePct > 0.5 ? '▲' : changePct < -0.5 ? '▼' : '·'
  const trendColor = changePct == null
    ? 'var(--muted)'
    : direction === 'higher_better'
      ? (changePct >= 0 ? '#10b981' : '#ef4444')
      : direction === 'lower_better'
        ? (changePct <= 0 ? '#10b981' : '#ef4444')
        : 'var(--muted)'

  return (
    <motion.button
      type="button"
      onClick={onClick}
      onMouseEnter={() => onHover?.(true)}
      onMouseLeave={() => onHover?.(false)}
      title={rationale}
      whileHover={{ y: -2, boxShadow: `0 8px 24px -12px ${color}66` }}
      transition={{ type: 'spring', stiffness: 260, damping: 22 }}
      style={{
        position: 'relative',
        background: 'linear-gradient(180deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0.01) 100%)',
        border: `1px solid ${color}33`,
        borderRadius: 14,
        padding: '12px 12px 10px',
        width: '100%',
        cursor: onClick ? 'pointer' : 'default',
        textAlign: 'left',
        color: 'var(--fg)',
        overflow: 'hidden',
      }}
    >
      {/* Category accent stripe */}
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0, height: 2,
        background: `linear-gradient(90deg, ${accent}, ${color})`,
      }} />

      <svg viewBox="0 0 160 170" style={{ width: '100%', height: 'auto', display: 'block' }}>
        {/* Background arc */}
        <path d={bgPath} fill="none" stroke="var(--border)" strokeWidth={8} strokeLinecap="round" opacity={0.35} />
        {/* Healthy-band highlight */}
        {healthyArc ? (
          <path d={healthyArc} fill="none" stroke="#10b98155" strokeWidth={8} strokeLinecap="round" />
        ) : null}
        {/* Value arc — animated */}
        <motion.path
          d={bgPath}
          fill="none"
          stroke={color}
          strokeWidth={8}
          strokeLinecap="round"
          pathLength={1}
          initial={{ pathLength: 0 }}
          animate={{ pathLength: position }}
          transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
        />
        {/* Needle */}
        <motion.g
          initial={{ rotate: START_ANGLE }}
          animate={{ rotate: needleAngle }}
          transition={{ type: 'spring', stiffness: 110, damping: 14, mass: 0.8 }}
          style={{ transformOrigin: `${cx}px ${cy}px` }}
        >
          <line x1={cx} y1={cy} x2={cx} y2={cy - 50} stroke={color} strokeWidth={2.5} strokeLinecap="round" />
          <circle cx={cx} cy={cy} r={5} fill={color} />
        </motion.g>
        {/* Center value */}
        <text x={cx} y={cy + 2} textAnchor="middle" fontSize={18} fontWeight={600} fill="var(--fg)">
          {displayValue}
        </text>
        <text x={cx} y={cy + 18} textAnchor="middle" fontSize={9} fill="var(--muted)">
          {unit ?? ''}
        </text>
        {/* Sparkline */}
        {sparkPath ? (
          <motion.path
            d={sparkPath}
            fill="none"
            stroke={color}
            strokeWidth={1.5}
            strokeLinecap="round"
            strokeOpacity={0.55}
            initial={{ pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: 1.0, ease: 'easeOut' }}
          />
        ) : null}
      </svg>

      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 6, marginTop: -4 }}>
        <div style={{
          fontSize: 11,
          color: 'var(--muted)',
          textTransform: 'uppercase',
          letterSpacing: 0.8,
          fontWeight: 500,
        }}>
          {label}
        </div>
        {changePct != null ? (
          <div style={{ fontSize: 11, color: trendColor, fontWeight: 600 }}>
            {trendChar} {Math.abs(changePct).toFixed(0)}%
          </div>
        ) : null}
      </div>
    </motion.button>
  )
}
