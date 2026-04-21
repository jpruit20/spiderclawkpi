import { CSSProperties } from 'react'

/**
 * Per-page "signature" gauge shapes. Each page gets a distinct shape
 * that matches the nature of its work — a fleet page shows concentric
 * layers; a triage page pulses; an executive page frames a North Star.
 *
 * The shell around these gauges (<DivisionHero>) is identical per
 * page. Only this signature primitive differentiates.
 *
 * Phase 1 variants: northStar, pulse, concentric.
 * Phase 2 (coming): funnel, throughput, stack, adoption, revenueDial,
 * chevron, radar, wave. The `HeroGauge` switch falls back to a default
 * "big number + delta" rendering for any signature not yet implemented.
 */
export type HeroSignature =
  | 'northStar'       // CommandCenter — MTD vs target target-bar with ahead/behind marker
  | 'pulse'           // Customer Experience — live-triage pulsing severity dot
  | 'concentric'      // Product/Engineering — fleet-layer concentric rings
  | 'funnel'          // Marketing (phase 2)
  | 'throughput'      // Operations (phase 2)
  | 'stack'           // Production/Manufacturing (phase 2)
  | 'adoption'        // FirmwareHub (phase 2)
  | 'revenueDial'     // Revenue Engine (phase 2)
  | 'chevron'         // DECI (phase 2)
  | 'radar'           // Issue Radar (phase 2)
  | 'wave'            // Social Intelligence (phase 2)

export type HeroGaugeData = {
  /** Big label above the value (e.g. "MTD Revenue"). */
  label: string
  /** The hero metric value (e.g. "$125K", "87%", "12 open"). */
  value: string
  /** Below-value context (e.g. "Target $150K", "up 8% WoW"). */
  sublabel?: string
  /** Numeric state: good/warn/bad/neutral (for coloring). */
  state?: 'good' | 'warn' | 'bad' | 'neutral'
  /** Optional progress 0..1 (for northStar fill, concentric inner ring, etc). */
  progress?: number
  /** Optional second progress 0..1 (for concentric mid ring, etc). */
  progressSecondary?: number
  /** Optional third progress 0..1 (for concentric inner ring, etc). */
  progressInner?: number
  /** Layer labels for concentric / multi-progress renderers. */
  layers?: Array<{ label: string; value: string; color?: string }>
  /** Optional free-form detail for signatures that want it. */
  extra?: Record<string, string | number>
}

type RenderProps = {
  data: HeroGaugeData
  accentColor: string
  accentColorSoft: string
}

const stateColor = (s?: HeroGaugeData['state']): string => {
  if (s === 'good') return 'var(--green)'
  if (s === 'warn') return 'var(--orange)'
  if (s === 'bad') return 'var(--red)'
  return 'var(--muted)'
}

const frameStyle: CSSProperties = {
  flex: 1,
  display: 'flex',
  flexDirection: 'column',
  justifyContent: 'space-between',
  padding: 16,
  border: '1px solid var(--border)',
  borderRadius: 12,
  background: 'rgba(0,0,0,0.25)',
  position: 'relative',
  overflow: 'hidden',
  minHeight: 180,
}

/* ─── northStar — CommandCenter ───────────────────────────────────────── */

function NorthStarGauge({ data, accentColor, accentColorSoft }: RenderProps) {
  const pct = Math.max(0, Math.min(1, data.progress ?? 0))
  const target = (data.extra?.targetLabel as string) || 'Target'
  const stateTint = data.state === 'good' ? 'var(--green)' : data.state === 'warn' ? 'var(--orange)' : data.state === 'bad' ? 'var(--red)' : accentColor
  return (
    <div style={frameStyle}>
      <div>
        <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 1 }}>
          North Star
        </div>
        <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 2 }}>{data.label}</div>
      </div>
      <div>
        <div style={{
          fontSize: 40,
          fontWeight: 700,
          color: 'var(--text)',
          letterSpacing: -0.5,
          lineHeight: 1,
        }}>
          {data.value}
        </div>
        {data.sublabel ? (
          <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 6 }}>{data.sublabel}</div>
        ) : null}
      </div>
      {/* Target bar with gradient fill + 100% target marker */}
      <div style={{ marginTop: 14 }}>
        <div style={{
          position: 'relative',
          height: 22,
          background: 'rgba(255,255,255,0.05)',
          borderRadius: 4,
          overflow: 'hidden',
        }}>
          <div style={{
            position: 'absolute',
            left: 0,
            top: 0,
            bottom: 0,
            width: `${Math.min(100, pct * 100)}%`,
            background: `linear-gradient(90deg, ${accentColor}, ${accentColorSoft})`,
            boxShadow: `inset 0 0 12px ${accentColor}88`,
            transition: 'width 700ms ease-out',
          }} />
          {/* Target marker at 100%. */}
          <div style={{
            position: 'absolute',
            left: '100%',
            top: -3,
            bottom: -3,
            borderLeft: '2px dashed var(--muted)',
            transform: 'translateX(-2px)',
          }} />
          {/* Ahead/behind dot — extends past the target if >100%. */}
          {pct > 1 && (
            <div style={{
              position: 'absolute',
              left: `${Math.min(100, pct * 100)}%`,
              top: '50%',
              width: 8,
              height: 8,
              borderRadius: '50%',
              background: 'var(--green)',
              transform: 'translate(-50%, -50%)',
              boxShadow: '0 0 8px var(--green)',
            }} />
          )}
        </div>
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          marginTop: 6,
          fontSize: 10,
          color: 'var(--muted)',
        }}>
          <span>{Math.round(pct * 100)}% of plan</span>
          <span>{target}: 100%</span>
        </div>
        <div style={{
          marginTop: 8,
          display: 'inline-block',
          padding: '3px 10px',
          borderRadius: 4,
          fontSize: 10,
          fontWeight: 600,
          letterSpacing: 0.5,
          textTransform: 'uppercase',
          background: stateTint,
          color: '#0c0e1a',
        }}>
          {pct >= 1 ? 'On / above plan' : pct >= 0.9 ? 'Tracking' : pct >= 0.7 ? 'Slipping' : 'Below plan'}
        </div>
      </div>
    </div>
  )
}

/* ─── pulse — Customer Experience ─────────────────────────────────────── */

function PulseGauge({ data, accentColor, accentColorSoft }: RenderProps) {
  // Severity-driven color: bad = red pulsing; warn = orange; good = green static; neutral = dim.
  const pulseColor = data.state === 'bad'
    ? 'var(--red)'
    : data.state === 'warn'
      ? 'var(--orange)'
      : data.state === 'good'
        ? 'var(--green)'
        : accentColor
  const animated = data.state === 'bad' || data.state === 'warn'
  const label = (data.extra?.context as string) || ''
  return (
    <div style={frameStyle}>
      {/* Inline keyframes so the component is self-contained. */}
      <style>{`
        @keyframes hero-pulse {
          0%   { transform: translate(-50%, -50%) scale(1); opacity: 0.6; }
          70%  { transform: translate(-50%, -50%) scale(2.2); opacity: 0; }
          100% { transform: translate(-50%, -50%) scale(2.2); opacity: 0; }
        }
      `}</style>
      <div>
        <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 1 }}>
          Live queue pulse
        </div>
        <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 2 }}>{data.label}</div>
      </div>
      {/* Big pulsing dot + number */}
      <div style={{
        flex: 1,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 16,
        position: 'relative',
        padding: '10px 0',
      }}>
        <div style={{ position: 'relative', width: 52, height: 52 }}>
          {/* Outer pulse ring */}
          {animated ? (
            <div style={{
              position: 'absolute',
              left: '50%',
              top: '50%',
              width: 44,
              height: 44,
              borderRadius: '50%',
              background: pulseColor,
              animation: 'hero-pulse 1.8s ease-out infinite',
            }} />
          ) : null}
          {/* Core dot */}
          <div style={{
            position: 'absolute',
            left: '50%',
            top: '50%',
            width: 32,
            height: 32,
            borderRadius: '50%',
            background: pulseColor,
            boxShadow: `0 0 20px ${pulseColor}aa`,
            transform: 'translate(-50%, -50%)',
          }} />
        </div>
        <div>
          <div style={{
            fontSize: 44,
            fontWeight: 700,
            color: pulseColor,
            lineHeight: 1,
            letterSpacing: -1,
          }}>
            {data.value}
          </div>
          {data.sublabel ? (
            <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>
              {data.sublabel}
            </div>
          ) : null}
        </div>
      </div>
      {label ? (
        <div style={{
          fontSize: 11,
          color: 'var(--muted)',
          textAlign: 'center',
          borderTop: '1px solid var(--border)',
          paddingTop: 8,
        }}>
          {label}
        </div>
      ) : null}
    </div>
  )
}

/* ─── concentric — Product / Engineering ──────────────────────────────── */

function ConcentricGauge({ data, accentColor, accentColorSoft }: RenderProps) {
  const layers = data.layers || []
  // Three nested arcs. progress = outer, progressSecondary = mid, progressInner = inner.
  // Default if missing: full outer, 0.7 mid, 0.4 inner.
  const p1 = Math.max(0, Math.min(1, data.progress ?? 1))
  const p2 = Math.max(0, Math.min(1, data.progressSecondary ?? 0.7))
  const p3 = Math.max(0, Math.min(1, data.progressInner ?? 0.4))

  const cx = 70
  const cy = 70
  const strokeW = 10
  const rs = [56, 42, 28]
  const arcLen = 270
  const startAngle = 135 // degrees, top-left

  const describeArc = (r: number, percent: number): string => {
    const sweep = arcLen * percent
    const startRad = (startAngle * Math.PI) / 180
    const endRad = ((startAngle + sweep) * Math.PI) / 180
    const x1 = cx + r * Math.cos(startRad)
    const y1 = cy + r * Math.sin(startRad)
    const x2 = cx + r * Math.cos(endRad)
    const y2 = cy + r * Math.sin(endRad)
    const largeArc = sweep > 180 ? 1 : 0
    return `M ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2}`
  }

  const trackPath = (r: number): string => describeArc(r, 1)

  return (
    <div style={frameStyle}>
      <div>
        <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 1 }}>
          Fleet layers
        </div>
        <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 2 }}>{data.label}</div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, flex: 1, paddingTop: 8 }}>
        <svg width={140} height={140} viewBox="0 0 140 140" style={{ flexShrink: 0 }}>
          {/* tracks */}
          {rs.map((r, i) => (
            <path
              key={`t${i}`}
              d={trackPath(r)}
              stroke="rgba(255,255,255,0.05)"
              strokeWidth={strokeW}
              fill="none"
              strokeLinecap="round"
            />
          ))}
          {/* outer — p1 */}
          <path
            d={describeArc(rs[0], p1)}
            stroke={accentColor}
            strokeWidth={strokeW}
            fill="none"
            strokeLinecap="round"
            style={{ transition: 'd 700ms ease-out' }}
          />
          {/* mid — p2 */}
          <path
            d={describeArc(rs[1], p2)}
            stroke={accentColorSoft}
            strokeWidth={strokeW}
            fill="none"
            strokeLinecap="round"
            opacity={0.8}
          />
          {/* inner — p3 */}
          <path
            d={describeArc(rs[2], p3)}
            stroke="var(--green)"
            strokeWidth={strokeW}
            fill="none"
            strokeLinecap="round"
            opacity={0.85}
          />
          {/* center label */}
          <text
            x={cx}
            y={cy - 4}
            textAnchor="middle"
            style={{ fontSize: 18, fontWeight: 700, fill: 'var(--text)' }}
          >
            {data.value}
          </text>
          <text
            x={cx}
            y={cy + 14}
            textAnchor="middle"
            style={{ fontSize: 10, fill: 'var(--muted)' }}
          >
            {data.sublabel || ''}
          </text>
        </svg>
        {/* Layer legend */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 110 }}>
          {layers.map((l, i) => {
            const colors = [accentColor, accentColorSoft, 'var(--green)']
            const c = l.color || colors[i] || accentColor
            return (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div style={{ width: 8, height: 8, borderRadius: '50%', background: c }} />
                <div>
                  <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.4 }}>
                    {l.label}
                  </div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>{l.value}</div>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

/* ─── default fallback (used for any not-yet-implemented signature) ──── */

function DefaultGauge({ data, accentColor }: RenderProps) {
  return (
    <div style={frameStyle}>
      <div>
        <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 1 }}>
          Headline
        </div>
        <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 2 }}>{data.label}</div>
      </div>
      <div>
        <div style={{ fontSize: 44, fontWeight: 700, color: 'var(--text)', lineHeight: 1, letterSpacing: -0.5 }}>
          {data.value}
        </div>
        {data.sublabel ? (
          <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 6 }}>{data.sublabel}</div>
        ) : null}
      </div>
      <div style={{
        marginTop: 10,
        height: 3,
        background: `linear-gradient(90deg, ${accentColor}, transparent)`,
        borderRadius: 2,
      }} />
    </div>
  )
}

export function HeroGauge(props: { signature: HeroSignature } & RenderProps) {
  const { signature, ...rest } = props
  if (signature === 'northStar') return <NorthStarGauge {...rest} />
  if (signature === 'pulse') return <PulseGauge {...rest} />
  if (signature === 'concentric') return <ConcentricGauge {...rest} />
  return <DefaultGauge {...rest} />
}
