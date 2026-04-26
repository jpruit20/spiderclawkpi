import { toneForAov, toneForConversion, toneForMer } from '../lib/decisionSupport'
import { KPIIntraday, IntradayStatus, KpiDisplayMode, KpiDisplayRow } from '../lib/types'
import { TrendPill } from './TrendPill'

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

function provenanceLabel(latest?: KpiDisplayRow) {
  if (!latest) return null
  if (latest.is_fallback_day) return `Fallback day · revenue: ${latest.revenue_source || 'n/a'} · sessions: ${latest.sessions_source || 'n/a'}`
  if (latest.is_partial_day) return `Partial day · revenue: ${latest.revenue_source || 'n/a'} · sessions: ${latest.sessions_source || 'n/a'}`
  return `Primary sources · revenue: ${latest.revenue_source || 'shopify'} · sessions: ${latest.sessions_source || 'shopify'}`
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
  const intradayUnavailable = intradayStatus === 'unavailable'
  const provenance = provenanceLabel(latest)

  // Tuple shape: [label, value, unavailable, tone, optional metric key for TrendPill]
  const items: Array<[string, string, boolean, string, string | null]> = latest
    ? [
        ['Revenue', currency(latest.revenue), false, 'neutral', 'revenue'],
        ['Orders', integer(latest.orders), false, 'neutral', 'orders'],
        ['AOV', currency(latest.average_order_value), false, toneForAov(latest.average_order_value), null],
        ['Sessions', integer(latest.sessions), displayMode === 'today_intraday' && intradayUnavailable, 'neutral', null],
        ['Conversion', percent(latest.conversion_rate), displayMode === 'today_intraday' && intradayUnavailable, toneForConversion(latest.conversion_rate), null],
        ['Revenue / Session', currency(latest.revenue_per_session), displayMode === 'today_intraday' && intradayUnavailable, 'neutral', null],
        ['Ad Spend', currency(latest.ad_spend), latest.ad_spend == null, 'neutral', null],
        ['MER', latest.mer == null ? '—' : latest.mer.toFixed(2), latest.mer == null, toneForMer(latest.mer), null],
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
          {provenance ? <small>{provenance}</small> : null}
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
          {items.map(([label, value, unavailable, tone, metricKey]) => (
            <div className={`stat-card ${tone !== 'neutral' ? `status-${tone}` : ''}`} key={label}>
              <div className="stat-label">{label}</div>
              <div className="stat-value" style={{ display: 'flex', alignItems: 'baseline', gap: 6, flexWrap: 'wrap' }}>
                <span>{metricValue(value, unavailable)}</span>
                {metricKey ? <TrendPill metricKey={metricKey} /> : null}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
