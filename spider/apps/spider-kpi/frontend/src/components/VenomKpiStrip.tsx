import { TruthBadge, TruthState } from './TruthBadge'

export interface KpiCardDef {
  label: string
  value: string
  sub: string
  truthState: TruthState
  delta?: { text: string; direction: 'up' | 'down' | 'flat' | 'stable' }
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
          <div className="venom-kpi-value">{card.value}</div>
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
