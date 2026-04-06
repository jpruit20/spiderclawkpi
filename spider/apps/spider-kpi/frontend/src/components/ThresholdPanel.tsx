import { thresholdSummary } from '../lib/thresholds'

function formatValue(metric: string, value?: number | null) {
  if (value == null) return '—'
  if (metric === 'average_order_value') return `$${value.toFixed(2)}`
  if (metric === 'conversion_rate') return `${value.toFixed(2)}%`
  if (metric === 'mer') return value.toFixed(2)
  if (metric === 'first_response_time') return `${value.toFixed(2)}h`
  if (metric === 'tickets_per_100_orders') return value.toFixed(2)
  return value.toFixed(0)
}

function toneRank(tone: string) {
  if (tone === 'bad') return 0
  if (tone === 'warn') return 1
  if (tone === 'good') return 2
  return 3
}

function targetLabel(metric: string, value?: number | null) {
  const summary = thresholdSummary(metric, value)
  if (!summary) return null
  if (summary.good == null && summary.warn == null) return null

  const formatTarget = (target?: number) => {
    if (target == null) return 'n/a'
    if (summary.unit === 'currency') return `$${target.toFixed(0)}`
    if (summary.unit === 'percent') return `${target.toFixed(1)}%`
    if (summary.unit === 'hours') return `${target.toFixed(1)}h`
    return target.toFixed(summary.unit === 'ratio' ? 1 : 0)
  }

  return summary.direction === 'higher_is_better'
    ? `Target ≥ ${formatTarget(summary.good)} · warning below ${formatTarget(summary.warn)}`
    : `Target ≤ ${formatTarget(summary.good)} · warning above ${formatTarget(summary.warn)}`
}

export function ThresholdPanel({ metrics }: { metrics: Array<{ metric: string; value?: number | null }> }) {
  const rows = metrics
    .map(({ metric, value }) => ({ summary: thresholdSummary(metric, value), value }))
    .filter((row): row is { summary: NonNullable<ReturnType<typeof thresholdSummary>>; value?: number | null } => Boolean(row.summary))
    .sort((a, b) => toneRank(a.summary.tone) - toneRank(b.summary.tone))

  if (!rows.length) return null

  return (
    <div className="threshold-grid">
      {rows.map(({ summary, value }) => (
        <div className={`list-item status-${summary.tone}`} key={summary.metric}>
          <div className="item-head">
            <strong>{summary.label}</strong>
            <span className={`badge badge-${summary.tone}`}>{summary.tone}</span>
          </div>
          <p>{formatValue(summary.metric, value)}</p>
          <small>{summary.reason}</small>
          <small>{targetLabel(summary.metric, value)}</small>
        </div>
      ))}
    </div>
  )
}
