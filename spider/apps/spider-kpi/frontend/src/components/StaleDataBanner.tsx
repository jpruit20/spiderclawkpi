import { SourceHealthItem } from '../lib/types'

function formatAge(minutes?: number) {
  if (minutes == null) return 'unknown age'
  if (minutes < 60) return `${minutes}m old`
  const hours = (minutes / 60).toFixed(minutes % 60 === 0 ? 0 : 1)
  return `${hours}h old`
}

export function StaleDataBanner({ rows }: { rows: SourceHealthItem[] }) {
  const staleRows = rows.filter((row) => ['stale', 'failed', 'running'].includes(row.derived_status))
  if (!staleRows.length) return null

  return (
    <div className="stale-banner">
      <strong>Decision risk: one or more live sources are stale or degraded.</strong>
      <div className="stack-list compact">
        {staleRows.map((row) => (
          <div className="list-item status-warn" key={row.source}>
            <strong>{row.source}</strong>
            <p>{row.status_summary}</p>
            <small>Latest state: {row.latest_run_status} · Freshness: {formatAge(row.stale_minutes)}</small>
          </div>
        ))}
      </div>
    </div>
  )
}
