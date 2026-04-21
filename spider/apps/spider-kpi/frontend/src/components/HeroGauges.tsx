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

/* ─── funnel — Marketing ──────────────────────────────────────────────
 * Trapezoidal conversion funnel. Width tapers by stage progress; top
 * = impressions/sessions, middle = add-to-cart/leads, bottom = orders.
 * progress = top, progressSecondary = middle, progressInner = bottom.
 * Pass stage labels through `layers`. */

function FunnelGauge({ data, accentColor, accentColorSoft }: RenderProps) {
  const layers = data.layers || []
  const p1 = Math.max(0.2, Math.min(1, data.progress ?? 1))
  const p2 = Math.max(0.1, Math.min(p1, data.progressSecondary ?? 0.6))
  const p3 = Math.max(0.05, Math.min(p2, data.progressInner ?? 0.25))
  const rowH = 28
  const width = 200
  const gap = 6
  const rows = [p1, p2, p3]
  return (
    <div style={frameStyle}>
      <div>
        <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 1 }}>
          Conversion funnel
        </div>
        <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 2 }}>{data.label}</div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, flex: 1, paddingTop: 8 }}>
        <svg width={width} height={rowH * 3 + gap * 2 + 4} style={{ flexShrink: 0 }}>
          {rows.map((p, i) => {
            const w = width * p
            const x = (width - w) / 2
            const y = i * (rowH + gap)
            const colors = [accentColor, accentColorSoft, 'var(--green)']
            const fill = colors[i] || accentColor
            return (
              <g key={i}>
                <rect x={x} y={y} width={w} height={rowH} rx={3} fill={fill} opacity={0.88} />
                <text
                  x={width / 2}
                  y={y + rowH / 2 + 4}
                  textAnchor="middle"
                  style={{ fontSize: 11, fontWeight: 600, fill: '#0c0e1a' }}
                >
                  {layers[i]?.value || ''}
                </text>
              </g>
            )
          })}
        </svg>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 90 }}>
          {layers.map((l, i) => {
            const colors = [accentColor, accentColorSoft, 'var(--green)']
            const c = l.color || colors[i] || accentColor
            return (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <div style={{ width: 6, height: 6, borderRadius: 1, background: c }} />
                <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.3 }}>
                  {l.label}
                </div>
              </div>
            )
          })}
        </div>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <div style={{ fontSize: 28, fontWeight: 700, color: stateColor(data.state), lineHeight: 1 }}>
          {data.value}
        </div>
        {data.sublabel ? (
          <div style={{ fontSize: 11, color: 'var(--muted)' }}>{data.sublabel}</div>
        ) : null}
      </div>
    </div>
  )
}

/* ─── throughput — Operations ─────────────────────────────────────────
 * Horizontal flow bar with animated shimmer; "velocity" theme. */

function ThroughputGauge({ data, accentColor, accentColorSoft }: RenderProps) {
  const pct = Math.max(0, Math.min(1, data.progress ?? 0))
  return (
    <div style={frameStyle}>
      <style>{`
        @keyframes hero-flow {
          0%   { transform: translateX(-60%); }
          100% { transform: translateX(160%); }
        }
      `}</style>
      <div>
        <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 1 }}>
          Flow velocity
        </div>
        <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 2 }}>{data.label}</div>
      </div>
      <div>
        <div style={{ fontSize: 40, fontWeight: 700, color: 'var(--text)', lineHeight: 1, letterSpacing: -0.5 }}>
          {data.value}
        </div>
        {data.sublabel ? (
          <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 6 }}>{data.sublabel}</div>
        ) : null}
      </div>
      {/* Flow track with animated shimmer */}
      <div style={{ position: 'relative', marginTop: 8 }}>
        <div style={{
          height: 10,
          background: 'rgba(255,255,255,0.05)',
          borderRadius: 2,
          overflow: 'hidden',
          position: 'relative',
        }}>
          <div style={{
            height: '100%',
            width: `${pct * 100}%`,
            background: `linear-gradient(90deg, ${accentColor}, ${accentColorSoft})`,
            boxShadow: `inset 0 0 8px ${accentColor}88`,
            transition: 'width 700ms ease-out',
          }} />
          <div style={{
            position: 'absolute',
            top: 0, left: 0, bottom: 0,
            width: 60,
            background: `linear-gradient(90deg, transparent, ${accentColor}cc, transparent)`,
            animation: pct > 0 ? 'hero-flow 2.4s linear infinite' : 'none',
            pointerEvents: 'none',
          }} />
        </div>
        <div style={{
          display: 'flex', justifyContent: 'space-between', marginTop: 6,
          fontSize: 10, color: 'var(--muted)',
        }}>
          <span>{Math.round(pct * 100)}% of planned throughput</span>
          {data.layers && data.layers[0] ? <span>{data.layers[0].label}: {data.layers[0].value}</span> : null}
        </div>
      </div>
    </div>
  )
}

/* ─── stack — Production / Manufacturing ──────────────────────────────
 * Vertical stacked bars: built → QC pass → shipped (physical pipeline).
 */

function StackGauge({ data, accentColor, accentColorSoft }: RenderProps) {
  const layers = data.layers || []
  // Heights proportional to each layer's progress; total box height = 120.
  const totalH = 120
  const p1 = Math.max(0.05, Math.min(1, data.progress ?? 0.8))
  const p2 = Math.max(0.05, Math.min(p1, data.progressSecondary ?? 0.6))
  const p3 = Math.max(0.05, Math.min(p2, data.progressInner ?? 0.4))
  const h1 = totalH * p1
  const h2 = totalH * p2
  const h3 = totalH * p3
  return (
    <div style={frameStyle}>
      <div>
        <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 1 }}>
          Build pipeline
        </div>
        <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 2 }}>{data.label}</div>
      </div>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 16, flex: 1, paddingTop: 8 }}>
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 10, height: totalH + 6 }}>
          {[h1, h2, h3].map((h, i) => {
            const colors = [accentColor, accentColorSoft, 'var(--green)']
            return (
              <div key={i} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text)' }}>
                  {layers[i]?.value || ''}
                </div>
                <div style={{
                  width: 22,
                  height: h,
                  background: `linear-gradient(180deg, ${colors[i]}, ${colors[i]}88)`,
                  borderRadius: '3px 3px 0 0',
                  boxShadow: `0 0 8px ${colors[i]}44`,
                  transition: 'height 600ms ease-out',
                }} />
              </div>
            )
          })}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {layers.map((l, i) => (
            <div key={i} style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.3 }}>
              {l.label}
            </div>
          ))}
        </div>
      </div>
      <div>
        <div style={{ fontSize: 28, fontWeight: 700, color: stateColor(data.state), lineHeight: 1 }}>
          {data.value}
        </div>
        {data.sublabel ? (
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>{data.sublabel}</div>
        ) : null}
      </div>
    </div>
  )
}

/* ─── adoption — Firmware Hub ─────────────────────────────────────────
 * Radial arcs by version, newest on outer ring. Stacked donut-ish. */

function AdoptionGauge({ data, accentColor, accentColorSoft }: RenderProps) {
  const layers = data.layers || []
  const cx = 70, cy = 70
  const arcLen = 360
  const strokeW = 8
  const rs = [56, 44, 32, 20]
  // Fractions default to typical adoption curve if not provided.
  const progresses = [
    Math.max(0, Math.min(1, data.progress ?? 0.65)),            // current prod
    Math.max(0, Math.min(1, data.progressSecondary ?? 0.25)),   // previous prod
    Math.max(0, Math.min(1, data.progressInner ?? 0.08)),       // older
    0.02,
  ]
  const colors = [accentColor, accentColorSoft, 'var(--orange)', 'var(--muted)']
  const describeArc = (r: number, percent: number, startAngle = -90): string => {
    const sweep = arcLen * percent
    const startRad = (startAngle * Math.PI) / 180
    const endRad = ((startAngle + sweep) * Math.PI) / 180
    const x1 = cx + r * Math.cos(startRad)
    const y1 = cy + r * Math.sin(startRad)
    const x2 = cx + r * Math.cos(endRad)
    const y2 = cy + r * Math.sin(endRad)
    const largeArc = sweep > 180 ? 1 : 0
    if (percent >= 0.999) {
      // Nearly full circle — render as 2 half-arcs to avoid degenerate path
      return `M ${cx} ${cy - r} A ${r} ${r} 0 1 1 ${cx - 0.01} ${cy - r} Z`
    }
    return `M ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2}`
  }
  return (
    <div style={frameStyle}>
      <div>
        <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 1 }}>
          Firmware adoption
        </div>
        <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 2 }}>{data.label}</div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flex: 1, paddingTop: 6 }}>
        <svg width={140} height={140} viewBox="0 0 140 140" style={{ flexShrink: 0 }}>
          {/* tracks */}
          {rs.map((r, i) => (
            <circle key={`t${i}`} cx={cx} cy={cy} r={r} stroke="rgba(255,255,255,0.05)" strokeWidth={strokeW} fill="none" />
          ))}
          {/* adoption arcs */}
          {rs.map((r, i) => (
            <path
              key={`a${i}`}
              d={describeArc(r, progresses[i])}
              stroke={colors[i]}
              strokeWidth={strokeW}
              fill="none"
              strokeLinecap="round"
              opacity={0.9}
            />
          ))}
          <text x={cx} y={cy - 2} textAnchor="middle" style={{ fontSize: 16, fontWeight: 700, fill: 'var(--text)' }}>
            {data.value}
          </text>
          <text x={cx} y={cy + 14} textAnchor="middle" style={{ fontSize: 9, fill: 'var(--muted)' }}>
            {data.sublabel || ''}
          </text>
        </svg>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 5, minWidth: 100 }}>
          {layers.slice(0, 4).map((l, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <div style={{ width: 8, height: 8, borderRadius: 2, background: l.color || colors[i] }} />
              <div style={{ fontSize: 10, color: 'var(--muted)' }}>{l.label}</div>
              <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text)', marginLeft: 'auto' }}>{l.value}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

/* ─── revenueDial — Revenue Engine ────────────────────────────────────
 * Dual-arc: outer = MTD revenue vs target, inner = margin. */

function RevenueDialGauge({ data, accentColor, accentColorSoft }: RenderProps) {
  const p1 = Math.max(0, Math.min(1.1, data.progress ?? 0))       // MTD vs target
  const p2 = Math.max(0, Math.min(1, data.progressSecondary ?? 0)) // margin
  const cx = 70, cy = 70
  const arcLen = 300
  const startAngle = 120 // bottom-left
  const strokeW = 10
  const rs = [56, 40]
  const describeArc = (r: number, percent: number): string => {
    const sweep = arcLen * Math.min(1, percent)
    const startRad = (startAngle * Math.PI) / 180
    const endRad = ((startAngle + sweep) * Math.PI) / 180
    const x1 = cx + r * Math.cos(startRad)
    const y1 = cy + r * Math.sin(startRad)
    const x2 = cx + r * Math.cos(endRad)
    const y2 = cy + r * Math.sin(endRad)
    const largeArc = sweep > 180 ? 1 : 0
    return `M ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2}`
  }
  const trackPath = (r: number) => describeArc(r, 1)
  const tint = stateColor(data.state)
  return (
    <div style={frameStyle}>
      <div>
        <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 1 }}>
          Revenue scoreboard
        </div>
        <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 2 }}>{data.label}</div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flex: 1, paddingTop: 4 }}>
        <svg width={140} height={140} viewBox="0 0 140 140" style={{ flexShrink: 0 }}>
          {rs.map((r, i) => (
            <path key={`t${i}`} d={trackPath(r)} stroke="rgba(255,255,255,0.05)" strokeWidth={strokeW} fill="none" strokeLinecap="round" />
          ))}
          <path
            d={describeArc(rs[0], p1)}
            stroke={p1 >= 1 ? 'var(--green)' : accentColor}
            strokeWidth={strokeW}
            fill="none"
            strokeLinecap="round"
            style={{ filter: p1 >= 1 ? 'drop-shadow(0 0 4px var(--green))' : 'none' }}
          />
          <path
            d={describeArc(rs[1], p2)}
            stroke={accentColorSoft}
            strokeWidth={strokeW}
            fill="none"
            strokeLinecap="round"
            opacity={0.85}
          />
          <text x={cx} y={cy - 2} textAnchor="middle" style={{ fontSize: 18, fontWeight: 700, fill: tint }}>
            {data.value}
          </text>
          <text x={cx} y={cy + 14} textAnchor="middle" style={{ fontSize: 10, fill: 'var(--muted)' }}>
            {data.sublabel || ''}
          </text>
        </svg>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 100 }}>
          <div>
            <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.4 }}>MTD vs target</div>
            <div style={{ fontSize: 14, fontWeight: 600, color: tint }}>{Math.round(p1 * 100)}%</div>
          </div>
          <div>
            <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.4 }}>Margin</div>
            <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>{Math.round(p2 * 100)}%</div>
          </div>
        </div>
      </div>
    </div>
  )
}

/* ─── chevron — DECI ──────────────────────────────────────────────────
 * Forward chevrons show decision velocity. Number of filled chevrons
 * reflects progress / health. */

function ChevronGauge({ data, accentColor, accentColorSoft }: RenderProps) {
  const pct = Math.max(0, Math.min(1, data.progress ?? 0.5))
  const count = 6
  const filled = Math.round(pct * count)
  return (
    <div style={frameStyle}>
      <div>
        <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 1 }}>
          Decision velocity
        </div>
        <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 2 }}>{data.label}</div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4, flex: 1 }}>
        <svg width={260} height={60} viewBox="0 0 260 60">
          {Array.from({ length: count }).map((_, i) => {
            const x = i * 42
            const active = i < filled
            const c = active ? accentColor : 'rgba(255,255,255,0.08)'
            return (
              <polygon
                key={i}
                points={`${x},0 ${x + 30},30 ${x},60 ${x + 10},30`}
                fill={c}
                style={{
                  filter: active ? `drop-shadow(0 0 4px ${accentColor}88)` : 'none',
                  transition: 'fill 300ms ease-out',
                }}
              />
            )
          })}
        </svg>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <div style={{ fontSize: 32, fontWeight: 700, color: stateColor(data.state), lineHeight: 1 }}>
          {data.value}
        </div>
        {data.sublabel ? (
          <div style={{ fontSize: 11, color: 'var(--muted)' }}>{data.sublabel}</div>
        ) : null}
      </div>
    </div>
  )
}

/* ─── radar — Issue Radar ─────────────────────────────────────────────
 * Polar radar with issue clusters plotted as dots. Sweep line animates. */

function RadarSignatureGauge({ data, accentColor, accentColorSoft }: RenderProps) {
  const cx = 70, cy = 70
  const maxR = 58
  // Dots represent issue clusters — pull from layers, or fallback to synthetic.
  const dots = (data.layers || []).slice(0, 8).map((l, i) => {
    // Position by hash of label + magnitude from value.
    const hash = (l.label || '').split('').reduce((a, c) => a + c.charCodeAt(0), 0)
    const angle = (hash * 47) % 360
    const distPct = Math.max(0.2, Math.min(1, Number((l.value || '').replace(/[^\d.]/g, '')) / 100 || 0.5))
    const r = maxR * distPct
    const rad = (angle * Math.PI) / 180
    return {
      x: cx + r * Math.cos(rad),
      y: cy + r * Math.sin(rad),
      label: l.label,
      color: l.color || accentColor,
      size: 4 + (distPct * 4),
    }
  })
  return (
    <div style={frameStyle}>
      <style>{`
        @keyframes hero-sweep {
          0%   { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
        }
      `}</style>
      <div>
        <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 1 }}>
          Issue radar
        </div>
        <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 2 }}>{data.label}</div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flex: 1, paddingTop: 4 }}>
        <svg width={140} height={140} viewBox="0 0 140 140" style={{ flexShrink: 0 }}>
          {/* concentric rings */}
          {[0.33, 0.66, 1].map((k, i) => (
            <circle key={i} cx={cx} cy={cy} r={maxR * k} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth={1} />
          ))}
          {/* cross-hairs */}
          <line x1={cx - maxR} y1={cy} x2={cx + maxR} y2={cy} stroke="rgba(255,255,255,0.05)" />
          <line x1={cx} y1={cy - maxR} x2={cx} y2={cy + maxR} stroke="rgba(255,255,255,0.05)" />
          {/* sweep line */}
          <g style={{ transformOrigin: `${cx}px ${cy}px`, animation: 'hero-sweep 6s linear infinite' }}>
            <line x1={cx} y1={cy} x2={cx + maxR} y2={cy} stroke={accentColor} strokeWidth={1.5} opacity={0.5} />
            <path
              d={`M ${cx} ${cy} L ${cx + maxR} ${cy} A ${maxR} ${maxR} 0 0 0 ${cx + maxR * Math.cos(-Math.PI / 4)} ${cy + maxR * Math.sin(-Math.PI / 4)} Z`}
              fill={accentColor}
              opacity={0.1}
            />
          </g>
          {/* dots */}
          {dots.map((d, i) => (
            <circle key={i} cx={d.x} cy={d.y} r={d.size} fill={d.color} opacity={0.9}>
              <title>{d.label}</title>
            </circle>
          ))}
        </svg>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 100 }}>
          <div style={{ fontSize: 32, fontWeight: 700, color: stateColor(data.state), lineHeight: 1 }}>
            {data.value}
          </div>
          {data.sublabel ? (
            <div style={{ fontSize: 11, color: 'var(--muted)' }}>{data.sublabel}</div>
          ) : null}
          <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 6 }}>
            {dots.length} cluster{dots.length === 1 ? '' : 's'} tracked
          </div>
        </div>
      </div>
    </div>
  )
}

/* ─── wave — Social Intelligence ──────────────────────────────────────
 * Sentiment wave. Positive sentiment rides above midline, negative below. */

function WaveGauge({ data, accentColorSoft, accentColor }: RenderProps) {
  // Generate wave path from sparkline if provided in extra.sparkline; otherwise synth.
  const raw = (data.extra?.sparkline as unknown as string) || ''
  const series: number[] = raw
    ? raw.split(',').map(s => parseFloat(s)).filter(n => !isNaN(n))
    : Array.from({ length: 20 }, (_, i) => Math.sin(i * 0.6) * 0.5 + (data.progress ?? 0.5))
  const w = 220
  const h = 70
  const max = Math.max(1, ...series.map(Math.abs))
  const step = series.length > 1 ? w / (series.length - 1) : 0
  const path = series.map((v, i) => {
    const x = i * step
    const y = h / 2 - (v / max) * (h / 2 - 4)
    return `${i === 0 ? 'M' : 'L'} ${x} ${y}`
  }).join(' ')
  const lastVal = series[series.length - 1] ?? 0
  return (
    <div style={frameStyle}>
      <div>
        <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 1 }}>
          Sentiment wave
        </div>
        <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 2 }}>{data.label}</div>
      </div>
      <div>
        <div style={{ fontSize: 36, fontWeight: 700, color: stateColor(data.state), lineHeight: 1 }}>
          {data.value}
        </div>
        {data.sublabel ? (
          <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>{data.sublabel}</div>
        ) : null}
      </div>
      <div style={{ marginTop: 8 }}>
        <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
          <defs>
            <linearGradient id="waveGrad" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor={accentColorSoft} />
              <stop offset="100%" stopColor={accentColor} />
            </linearGradient>
          </defs>
          <line x1={0} y1={h / 2} x2={w} y2={h / 2} stroke="rgba(255,255,255,0.08)" strokeDasharray="3 3" />
          <path d={path} stroke="url(#waveGrad)" strokeWidth={2} fill="none" strokeLinecap="round" strokeLinejoin="round" />
          <circle
            cx={(series.length - 1) * step}
            cy={h / 2 - (lastVal / max) * (h / 2 - 4)}
            r={4}
            fill={lastVal >= 0 ? 'var(--green)' : 'var(--red)'}
            style={{ filter: `drop-shadow(0 0 4px ${lastVal >= 0 ? 'var(--green)' : 'var(--red)'})` }}
          />
        </svg>
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
  if (signature === 'funnel') return <FunnelGauge {...rest} />
  if (signature === 'throughput') return <ThroughputGauge {...rest} />
  if (signature === 'stack') return <StackGauge {...rest} />
  if (signature === 'adoption') return <AdoptionGauge {...rest} />
  if (signature === 'revenueDial') return <RevenueDialGauge {...rest} />
  if (signature === 'chevron') return <ChevronGauge {...rest} />
  if (signature === 'radar') return <RadarSignatureGauge {...rest} />
  if (signature === 'wave') return <WaveGauge {...rest} />
  return <DefaultGauge {...rest} />
}
