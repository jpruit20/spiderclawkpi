import { KPIDaily } from './types'

export type RangePreset = 'today' | '7d' | '14d' | '30d' | '90d' | 'custom'

export interface RangeState {
  preset: RangePreset
  startDate: string
  endDate: string
}

type BuildPresetOptions = {
  anchorDate?: string
}

function toIsoDate(value: Date) {
  return value.toISOString().slice(0, 10)
}

export function businessTodayDate() {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date())
}

export function dateInputValue(value?: string) {
  return value || ''
}

export function buildPresetRange(preset: Exclude<RangePreset, 'custom'>, rows: { business_date: string }[], options: BuildPresetOptions = {}): RangeState {
  const sorted = [...rows].sort((a, b) => a.business_date.localeCompare(b.business_date))
  const latest = options.anchorDate || sorted[sorted.length - 1]?.business_date || businessTodayDate()
  if (preset === 'today') {
    return { preset, startDate: latest, endDate: latest }
  }
  const span = preset === '7d' ? 7 : preset === '14d' ? 14 : preset === '30d' ? 30 : 90
  const endIndex = sorted.findIndex((row) => row.business_date === latest)
  const startIndex = Math.max(0, endIndex - span + 1)
  return {
    preset,
    startDate: sorted[startIndex]?.business_date || latest,
    endDate: latest,
  }
}

export function filterRowsByRange<T extends { business_date: string }>(rows: T[], range: RangeState): T[] {
  return [...rows]
    .filter((row) => row.business_date >= range.startDate && row.business_date <= range.endDate)
    .sort((a, b) => a.business_date.localeCompare(b.business_date))
}

export function summarizeRangeLabel(range: RangeState) {
  switch (range.preset) {
    case 'today':
      return `Today (${range.endDate})`
    case '7d':
      return `Last 7 days (${range.startDate} → ${range.endDate})`
    case '14d':
      return `Last 14 days (${range.startDate} → ${range.endDate})`
    case '30d':
      return `Last 30 days (${range.startDate} → ${range.endDate})`
    case '90d':
      return `Last 90 days (${range.startDate} → ${range.endDate})`
    case 'custom':
    default:
      return `Custom (${range.startDate} → ${range.endDate})`
  }
}

export function buildCustomRange(startDate: string, endDate: string): RangeState {
  const normalizedStart = startDate <= endDate ? startDate : endDate
  const normalizedEnd = endDate >= startDate ? endDate : startDate
  return { preset: 'custom', startDate: normalizedStart, endDate: normalizedEnd }
}

export function summarizeKpis(rows: KPIDaily[]): KPIDaily | undefined {
  if (!rows.length) return undefined
  const revenue = rows.reduce((sum, row) => sum + row.revenue, 0)
  const orders = rows.reduce((sum, row) => sum + row.orders, 0)
  const sessions = rows.reduce((sum, row) => sum + row.sessions, 0)
  const adSpend = rows.reduce((sum, row) => sum + row.ad_spend, 0)
  const ticketsCreated = rows.reduce((sum, row) => sum + row.tickets_created, 0)
  const ticketsResolved = rows.reduce((sum, row) => sum + row.tickets_resolved, 0)
  const openBacklog = rows[rows.length - 1]?.open_backlog || 0
  const avg = (key: keyof KPIDaily) => rows.reduce((sum, row) => sum + Number(row[key] || 0), 0) / rows.length
  const revenueSources = Array.from(new Set(rows.map((row) => row.revenue_source).filter(Boolean)))
  const sessionsSources = Array.from(new Set(rows.map((row) => row.sessions_source).filter(Boolean)))
  const ordersSources = Array.from(new Set(rows.map((row) => row.orders_source).filter(Boolean)))
  const hasPartial = rows.some((row) => Boolean(row.is_partial_day))
  const hasFallback = rows.some((row) => Boolean(row.is_fallback_day))
  return {
    business_date: `${rows[0].business_date} → ${rows[rows.length - 1].business_date}`,
    revenue,
    orders,
    average_order_value: orders ? revenue / orders : 0,
    sessions,
    conversion_rate: sessions ? (orders / sessions) * 100 : 0,
    revenue_per_session: sessions ? revenue / sessions : 0,
    add_to_cart_rate: avg('add_to_cart_rate'),
    bounce_rate: avg('bounce_rate'),
    purchases: rows.reduce((sum, row) => sum + row.purchases, 0),
    ad_spend: adSpend,
    mer: adSpend ? revenue / adSpend : 0,
    cost_per_purchase: orders ? adSpend / orders : 0,
    tickets_created: ticketsCreated,
    tickets_resolved: ticketsResolved,
    open_backlog: openBacklog,
    first_response_time: avg('first_response_time'),
    resolution_time: avg('resolution_time'),
    sla_breach_rate: avg('sla_breach_rate'),
    csat: avg('csat'),
    reopen_rate: avg('reopen_rate'),
    tickets_per_100_orders: orders ? (ticketsCreated / orders) * 100 : 0,
    revenue_source: revenueSources.length === 1 ? revenueSources[0] : revenueSources.length ? 'mixed' : null,
    sessions_source: sessionsSources.length === 1 ? sessionsSources[0] : sessionsSources.length ? 'mixed' : null,
    orders_source: ordersSources.length === 1 ? ordersSources[0] : ordersSources.length ? 'mixed' : null,
    is_partial_day: hasPartial,
    is_fallback_day: hasFallback,
  }
}
