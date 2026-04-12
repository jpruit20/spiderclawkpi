import { TruthBadge, TruthState } from './TruthBadge'

export interface KpiCardDef {
  label: string
  value: string
  sub: string
  truthState: TruthState
  delta?: { text: string; direction: 'up' | 'down' | 'flat' | 'stable' }
  sparkline?: number[]
}

/** Simple SVG sparkline — green if trending up, red if down */
function Sparkline({ data }: { data: number[] }) {
  if (!data || data.length < 2) return null
  const min = Math.min(...data)
  const max = Math.max(...data)
  const range = max - min || 1
  const width = 60
  const height = 20
  const points = data.map((v, i) => {
    const x = (i / (data.length - 1)) * width
    const y = height - ((v - min) / range) * height
    return `${x},${y}`
  }).join(' ')
  const isUp = data[data.length - 1] >= data[0]
  const color = isUp ? 'var(--green)' : 'var(--red)'
  return (
    <svg width={width} height={height} className="venom-sparkline" style={{ marginLeft: 8 }}>
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

const DELTA_CLASS: Record<string, string> = {
  up: 'venom-delta-up',
  down: 'venom-delta-down',
  flat: 'venom-delta-flat',
  stable: 'venom-delta-stable',
}

export function VenomKpiStrip({ cards, cols }: { cards: KpiCardDef[]; cols?: 3 | 4 }) {
  const className = cols === 3 ? 'venom-kpi-strip venom-kpi-strip-3' : 'venom-kpi-strip'
  return (
    <div className={className}>
      {cards.map((card) => (
        <div key={card.label} className="venom-kpi-card">
          <div className="venom-kpi-label">{card.label}</div>
          <div className="venom-kpi-value-row">
            <span className="venom-kpi-value">{card.value}</span>
            {card.sparkline ? <Sparkline data={card.sparkline} /> : null}
          </div>
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
