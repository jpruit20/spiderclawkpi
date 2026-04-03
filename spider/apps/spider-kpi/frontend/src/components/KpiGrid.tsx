import { KPIIntraday, IntradayStatus, KpiDisplayMode, KpiDisplayRow } from '../lib/types'

function currency(value?: number | null) {
  if (value == null) return '—'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 2,
  }).format(value)
}

function integer(value?: number | null) {
  if (value == null) return '—'
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(value)
}

function percent(value?: number | null) {
  if (value == null) return '—'
  return `${value.toFixed(2)}%`
}

function modeLabel(mode: KpiDisplayMode) {
  switch (mode) {
    case 'latest_complete_day':
      return 'Latest complete day'
    case 'today_intraday':
      return 'Today intraday'
    case 'selected_range_summary':
    default:
      return 'Selected range summary'
  }
}

function intradayStatusTone(status: IntradayStatus) {
  switch (status) {
    case 'live':
      return 'badge-good'
    case 'partial':
      return 'badge-warn'
    case 'delayed':
      return 'badge-bad'
    default:
      return 'badge-muted'
  }
}

function metricValue(value: string, unavailable: boolean) {
  return unavailable && value !== '—' ? 'partial / unavailable' : value
}

export function KpiGrid({
  latest,
  intraday,
  scopeLabel,
  displayMode,
  intradayStatus,
  intradayMessage,
  noDataMessage,
}: {
  latest?: KpiDisplayRow
  intraday?: KPIIntraday | null
  scopeLabel: string
  displayMode: KpiDisplayMode
  intradayStatus: IntradayStatus
  intradayMessage: string
  noDataMessage?: string
}) {
  const intradayUnavailable = intradayStatus !== 'live'

  const items = latest
    ? [
        ['Revenue', currency(latest.revenue), false],
        ['Orders', integer(latest.orders), false],
        ['AOV', currency(latest.average_order_value), false],
        ['Sessions', integer(latest.sessions), false],
        ['Conversion', percent(latest.conversion_rate), false],
        ['Revenue / Session', currency(latest.revenue_per_session), false],
        ['Ad Spend', currency(latest.ad_spend), latest.ad_spend == null],
        ['MER', latest.mer == null ? '—' : latest.mer.toFixed(2), latest.mer == null],
      ]
    : []

  const intradaySummary = intraday
    ? `${currency(intraday.revenue)} revenue · ${integer(intraday.orders)} orders · ${metricValue(integer(intraday.sessions), intradayUnavailable)} sessions`
    : 'Today intraday data unavailable.'

  return (
    <div className="page-grid">
      <div className="scope-banner">
        <div>
          <strong>Showing: {scopeLabel}</strong>
          <span>{modeLabel(displayMode)}</span>
        </div>
        <div className="intraday-banner">
          <span className={`badge ${intradayStatusTone(intradayStatus)}`}>{intradayStatus}</span>
          <small>
            Today intraday: {intradaySummary}
            <br />
            {intradayMessage}
          </small>
        </div>
      </div>
      {!latest ? (
        <div className="state-message">{noDataMessage || 'No KPI summary returned.'}</div>
      ) : (
        <div className="kpi-grid">
          {items.map(([label, value, unavailable]) => (
            <div className="stat-card" key={String(label)}>
              <div className="stat-label">{label}</div>
              <div className="stat-value">{metricValue(String(value), Boolean(unavailable))}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
