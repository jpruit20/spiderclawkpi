import { CompareMode, ComparePoint, formatDeltaPct } from '../lib/compare'
import { StatePanel } from './StatePanel'

function formatCurrent(point: ComparePoint) {
  if (point.label === 'Revenue') return `$${point.current.toFixed(2)}`
  if (point.label === 'Conversion') return `${point.current.toFixed(2)}%`
  return point.current.toFixed(0)
}

function formatBaseline(point: ComparePoint) {
  if (point.baseline == null) return ''
  if (point.label === 'Revenue') return `$${point.baseline.toFixed(2)}`
  if (point.label === 'Conversion') return `${point.baseline.toFixed(2)}%`
  return point.baseline.toFixed(0)
}

function compareModeLabel(mode: CompareMode) {
  switch (mode) {
    case 'same_day_last_week':
      return 'same day last week'
    case 'prior_period':
      return 'prior period'
    case 'none':
    default:
      return 'no comparison'
  }
}

function tone(point: ComparePoint) {
  if (!point.comparable || point.deltaPct == null) return 'muted'
  if (point.deltaPct >= 10) return 'good'
  if (point.deltaPct <= -10) return 'bad'
  return 'warn'
}

export function CompareSummary({ mode, points }: { mode: CompareMode; points: ComparePoint[] }) {
  if (mode === 'none') {
    return <StatePanel kind="ready" tone="neutral" title="Compare mode off" message="Comparison is disabled. Use compare mode to separate true change from normal day-to-day variance." />
  }

  const comparablePoints = points.filter((point) => point.comparable)
  if (!comparablePoints.length) {
    return <StatePanel kind="partial" tone="warn" title="Comparison window incomplete" message={`Selected window cannot be compared against ${compareModeLabel(mode)} yet.`} />
  }

  return (
    <div className="compare-summary-grid">
      {points.map((point) => (
        <div className={`list-item compare-point status-${tone(point)}`} key={point.label}>
          <div className="item-head">
            <strong>{point.label}</strong>
            <span className="badge badge-neutral">vs {compareModeLabel(mode)}</span>
          </div>
          <div className="compare-values">
            <div>
              <small>Current</small>
              <p>{formatCurrent(point)}</p>
            </div>
            <div>
              <small>Baseline</small>
              <p>{point.baseline != null ? formatBaseline(point) : '—'}</p>
            </div>
            <div>
              <small>Delta</small>
              <p>{point.comparable ? formatDeltaPct(point.deltaPct) : 'n/a'}</p>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
