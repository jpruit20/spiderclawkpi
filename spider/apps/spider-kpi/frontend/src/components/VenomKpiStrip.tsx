import { TruthBadge, TruthState } from './TruthBadge'

export interface KpiCardDef {
  label: string
  value: string
  sub: string
  truthState: TruthState
  delta?: { text: string; direction: 'up' | 'down' | 'flat' | 'stable' }
  sparkline?: number[]
}

const DELTA_CLASS: Record<string, string> = {
  up: 'venom-delta-up',
  down: 'venom-delta-down',
  flat: 'venom-delta-flat',
  stable: 'venom-delta-stable',
}

function Sparkline({ data, direction }: { data: number[]; direction?: 'up' | 'down' | 'flat' | 'stable' }) {
  if (!data || data.length < 2) return null

  const width = 80
  const height = 24
  const padding = 2

  const minVal = Math.min(...data)
  const maxVal = Math.max(...data)
  const range = maxVal - minVal || 1

  const points = data.map((val, idx) => {
    const x = padding + (idx / (data.length - 1)) * (width - padding * 2)
    const y = height - padding - ((val - minVal) / range) * (height - padding * 2)
    return `${x},${y}`
  })

  const strokeColor = direction === 'up' ? 'var(--green)' : direction === 'down' ? 'var(--red)' : 'var(--muted)'

  return (
    <svg width={width} height={height} className="venom-sparkline" style={{ display: 'block', marginTop: 8 }}>
      <polyline
        fill="none"
        stroke={strokeColor}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        points={points.join(' ')}
      />
    </svg>
  )
}

export function VenomKpiStrip({ cards, cols }: { cards: KpiCardDef[]; cols?: 3 | 4 }) {
  const className = cols === 3 ? 'venom-kpi-strip venom-kpi-strip-3' : 'venom-kpi-strip'
  return (
    <div className={className}>
      {cards.map((card) => (
        <div key={card.label} className="venom-kpi-card">
          <div className="venom-kpi-label">{card.label}</div>
          <div className="venom-kpi-value">{card.value}</div>
          {card.sparkline && card.sparkline.length >= 2 ? (
            <Sparkline data={card.sparkline} direction={card.delta?.direction} />
          ) : null}
          <div className="venom-kpi-sub">{card.sub}</div>
          <div className="venom-kpi-badges">
            <TruthBadge state={card.truthState} />
            {card.delta ? <span className={`venom-delta ${DELTA_CLASS[card.delta.direction]}`}>{card.delta.text}</span> : null}
          </div>
        </div>
      ))}
    </div>
  )
}
