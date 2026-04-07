import { SourceHealthItem } from './types'

export const ACTIVE_CONNECTORS = new Set(['shopify', 'triplewhale', 'freshdesk', 'ga4', 'clarity'])
export const SCAFFOLDED = new Set(['discord', 'facebook', 'google_reviews', 'reddit', 'reviews'])

export function isTruthfullyHealthy(row: SourceHealthItem) {
  return row.latest_run_status === 'success' && row.latest_records_processed > 0 && Boolean(row.last_success_at)
}

export function isLiveConnector(row: SourceHealthItem) {
  return ACTIVE_CONNECTORS.has(row.source)
}

export function isScaffolded(row: SourceHealthItem) {
  return SCAFFOLDED.has(row.source)
}
