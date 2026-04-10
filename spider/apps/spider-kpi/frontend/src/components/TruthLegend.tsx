const ITEMS = [
  { state: 'canonical', label: 'canonical — strong truth', color: 'var(--green)' },
  { state: 'proxy', label: 'proxy — useful but incomplete', color: 'var(--blue)' },
  { state: 'estimated', label: 'estimated — modeled / heuristic', color: 'var(--orange)' },
  { state: 'degraded', label: 'degraded — source unhealthy', color: 'var(--red)' },
  { state: 'unavailable', label: 'unavailable — data not present', color: 'var(--muted)' },
] as const

export function TruthLegend() {
  return (
    <div className="venom-legend">
      {ITEMS.map((item) => (
        <span key={item.state} className="venom-legend-item">
          <span className="venom-legend-dot" style={{ background: item.color }} />
          {item.label}
        </span>
      ))}
    </div>
  )
}
