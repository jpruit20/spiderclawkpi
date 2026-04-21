import { ReactNode } from 'react'
import { HeroGauge, HeroSignature, HeroGaugeData } from './HeroGauges'

/**
 * Division hero shell — the consistent "architectural rhythm" that
 * wraps the top of every primary page.
 *
 * Layout:
 *   ┌───────────────────────────────────────────────────────────┐
 *   │ ▌ title + subtitle                         meta (right)   │  ← header strip
 *   ├───────────────────────────────────────────────────────────┤
 *   │                    │               │                      │
 *   │   PRIMARY GAUGE    │   FLANKING    │      TILE GRID        │
 *   │   (signature)      │   gauges      │      (support KPIs)   │
 *   │                    │               │                      │
 *   └───────────────────────────────────────────────────────────┘
 *     accent-color gradient bleed at bottom edge
 *
 * Every page uses the same shell but varies the `signature` prop on
 * the primary gauge — that's the visual fingerprint a veteran user
 * recognizes before they read the title.
 */

export type HeroTileState = 'good' | 'warn' | 'bad' | 'neutral'

export type HeroFlankingItem = {
  label: string
  value: string
  sublabel?: string
  state?: HeroTileState
  /** Optional: numeric progress 0..1 for a mini progress bar. */
  progress?: number
  /** Optional: Δ vs target, rendered as arrow + tinted label. */
  delta?: { dir: 'up' | 'down' | 'flat'; label: string; good: boolean }
}

export type HeroTileItem = {
  label: string
  value: string
  sublabel?: string
  state?: HeroTileState
  /** Optional click-through for drill-down. */
  onClick?: () => void
}

export type DivisionHeroProps = {
  /** Signature color that tints the accent strip + gradient + primary gauge. */
  accentColor: string
  /** Optional secondary accent for gradient stops. */
  accentColorSoft?: string
  /** Signature shape of the primary gauge — the page's visual fingerprint. */
  signature: HeroSignature
  /** Page title (big, bold). */
  title: string
  /** One-line context about what the page is for. */
  subtitle?: string
  /** Right-aligned header meta — freshness badge, status, etc. */
  rightMeta?: ReactNode
  /** Primary (hero) gauge data. */
  primary: HeroGaugeData
  /** 1–2 flanking gauges in the middle zone. */
  flanking?: HeroFlankingItem[]
  /** 4–8 support tiles in the right zone. */
  tiles?: HeroTileItem[]
  /** Optional extra ReactNode injected after the tiles column (e.g. date picker). */
  tailSlot?: ReactNode
}

const stateColor = (s?: HeroTileState): string => {
  if (s === 'good') return 'var(--green)'
  if (s === 'warn') return 'var(--orange)'
  if (s === 'bad') return 'var(--red)'
  return 'var(--muted)'
}

function HeroFlanking({ items }: { items: HeroFlankingItem[] }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, minWidth: 180 }}>
      {items.map((item, i) => (
        <div
          key={i}
          style={{
            padding: '10px 12px',
            border: '1px solid var(--border)',
            borderRadius: 10,
            background: 'rgba(255,255,255,0.015)',
            display: 'flex',
            flexDirection: 'column',
            gap: 4,
          }}
        >
          <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
            {item.label}
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
            <div style={{ fontSize: 22, fontWeight: 600, color: stateColor(item.state), lineHeight: 1 }}>
              {item.value}
            </div>
            {item.delta ? (
              <span style={{
                fontSize: 11,
                fontWeight: 500,
                color: item.delta.good ? 'var(--green)' : 'var(--red)',
              }}>
                {item.delta.dir === 'up' ? '▲' : item.delta.dir === 'down' ? '▼' : '■'} {item.delta.label}
              </span>
            ) : null}
          </div>
          {item.sublabel ? (
            <div style={{ fontSize: 11, color: 'var(--muted)' }}>{item.sublabel}</div>
          ) : null}
          {item.progress != null ? (
            <div style={{ height: 4, background: 'rgba(255,255,255,0.05)', borderRadius: 2, overflow: 'hidden', marginTop: 4 }}>
              <div style={{
                height: '100%',
                width: `${Math.max(0, Math.min(1, item.progress)) * 100}%`,
                background: stateColor(item.state),
                transition: 'width 500ms ease-out',
              }} />
            </div>
          ) : null}
        </div>
      ))}
    </div>
  )
}

function HeroTiles({ items }: { items: HeroTileItem[] }) {
  const cols = items.length <= 4 ? 2 : 3
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`,
      gap: 8,
      minWidth: 220,
    }}>
      {items.map((item, i) => (
        <div
          key={i}
          onClick={item.onClick}
          style={{
            padding: '8px 10px',
            border: '1px solid var(--border)',
            borderRadius: 8,
            background: 'rgba(255,255,255,0.015)',
            cursor: item.onClick ? 'pointer' : 'default',
            borderLeft: `3px solid ${stateColor(item.state)}`,
            display: 'flex',
            flexDirection: 'column',
            gap: 2,
            minHeight: 54,
            transition: 'transform 150ms ease-out, background 150ms ease-out',
          }}
          onMouseEnter={e => {
            if (item.onClick) {
              ;(e.currentTarget as HTMLDivElement).style.background = 'rgba(255,255,255,0.04)'
            }
          }}
          onMouseLeave={e => {
            ;(e.currentTarget as HTMLDivElement).style.background = 'rgba(255,255,255,0.015)'
          }}
        >
          <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.4 }}>
            {item.label}
          </div>
          <div style={{ fontSize: 16, fontWeight: 600, color: stateColor(item.state), lineHeight: 1.1 }}>
            {item.value}
          </div>
          {item.sublabel ? (
            <div style={{ fontSize: 10, color: 'var(--muted)' }}>{item.sublabel}</div>
          ) : null}
        </div>
      ))}
    </div>
  )
}

export function DivisionHero({
  accentColor,
  accentColorSoft,
  signature,
  title,
  subtitle,
  rightMeta,
  primary,
  flanking = [],
  tiles = [],
  tailSlot,
}: DivisionHeroProps) {
  const soft = accentColorSoft ?? accentColor
  return (
    <section
      className="division-hero"
      style={{
        position: 'relative',
        border: '1px solid var(--border)',
        borderRadius: 14,
        padding: 18,
        background: `
          radial-gradient(ellipse at 0% 0%, ${accentColor}14, transparent 55%),
          radial-gradient(ellipse at 100% 100%, ${soft}0c, transparent 60%),
          var(--panel)
        `,
        boxShadow: `inset 4px 0 0 0 ${accentColor}`,
        overflow: 'hidden',
        marginBottom: 12,
      }}
    >
      {/* Header row */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'flex-start',
        gap: 16,
        flexWrap: 'wrap',
        marginBottom: 14,
      }}>
        <div>
          <div style={{
            fontSize: 10,
            color: accentColor,
            textTransform: 'uppercase',
            letterSpacing: 1.2,
            fontWeight: 600,
            marginBottom: 2,
          }}>
            Division
          </div>
          <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--text)', lineHeight: 1.1 }}>
            {title}
          </div>
          {subtitle ? (
            <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4, maxWidth: 640 }}>
              {subtitle}
            </div>
          ) : null}
        </div>
        {rightMeta ? (
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, flexWrap: 'wrap' }}>
            {rightMeta}
          </div>
        ) : null}
      </div>

      {/* Primary | Flanking | Tiles */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(260px, 1.2fr) minmax(180px, 0.7fr) minmax(220px, 1.1fr)',
        gap: 14,
        alignItems: 'stretch',
      }}>
        <div style={{ minHeight: 180, display: 'flex', alignItems: 'stretch' }}>
          <HeroGauge signature={signature} data={primary} accentColor={accentColor} accentColorSoft={soft} />
        </div>
        <div>
          {flanking.length > 0 ? <HeroFlanking items={flanking} /> : null}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {tiles.length > 0 ? <HeroTiles items={tiles} /> : null}
          {tailSlot}
        </div>
      </div>

      {/* Bottom accent gradient — the signature color bleed. */}
      <div
        aria-hidden
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          bottom: 0,
          height: 2,
          background: `linear-gradient(90deg, ${accentColor} 0%, ${soft} 70%, transparent 100%)`,
          opacity: 0.7,
        }}
      />
    </section>
  )
}
