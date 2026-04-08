export type KPIStatus = 'green' | 'yellow' | 'red'
export type KPITrend = 'up' | 'flat' | 'down'
export type KPITruthState = 'canonical' | 'proxy' | 'estimated' | 'degraded' | 'blocked' | 'unavailable'

export interface KPIObject {
  key: string
  current_value: number | string | null
  target_value: number | string | null
  delta: {
    absolute: number | null
    percent: number | null
    direction: 'improving' | 'worsening' | 'flat' | 'unknown'
    comparison_basis: 'vs_prior_period' | 'vs_target' | 'vs_same_day_last_week'
  }
  trend: KPITrend
  owner: string
  status: KPIStatus
  truth_state: KPITruthState
  last_updated: string
  sample_size?: number | null
  sample_scope?: string | null
  sample_reliability?: 'low' | 'medium' | 'high' | null
}

export interface ActionObject {
  id: string
  trigger_kpi: string
  trigger_condition: string
  owner: string
  co_owner?: string
  escalation_owner?: string
  required_action: string
  priority: 'critical' | 'high' | 'medium' | 'low'
  status: 'open' | 'in_progress' | 'resolved'
  evidence: string[]
  due_date: string
  snapshot_timestamp: string
  scope?: 'observed_slice' | 'fleet_wide'
  confidence?: 'low' | 'medium' | 'high'
}

export interface BlockedStateOutput {
  decision_blocked: string
  missing_source: string
  still_trustworthy: string[]
  owner: string
  required_action_to_unblock: string
}

export interface KPIDaily {
  business_date: string
  revenue: number
  refunds?: number
  orders: number
  average_order_value: number
  sessions: number
  conversion_rate: number
  revenue_per_session: number
  add_to_cart_rate: number
  bounce_rate: number
  purchases: number
  ad_spend: number
  mer: number
  cost_per_purchase: number
  tickets_created: number
  tickets_resolved: number
  open_backlog: number
  first_response_time: number
  resolution_time: number
  sla_breach_rate: number
  csat: number
  reopen_rate: number
  tickets_per_100_orders: number
  revenue_source?: string | null
  sessions_source?: string | null
  orders_source?: string | null
  is_partial_day?: boolean
  is_fallback_day?: boolean
}

export interface KPIIntraday {
  bucket_start?: string
  revenue: number
  orders: number
  average_order_value: number
  sessions: number
  conversion_rate: number
  ad_spend?: number
  mer?: number
}

export interface AlertItem {
  id: number
  business_date?: string
  source: string
  severity: string
  status: string
  title: string
  message: string
  owner_team?: string
  confidence: number
  metadata_json: Record<string, unknown>
}

export interface RecommendationItem {
  id: number
  business_date?: string
  owner_team: string
  title: string
  recommended_action: string
  root_cause?: string
  severity: string
  confidence: number
  estimated_impact?: string
  metadata_json?: Record<string, unknown>
}

export interface DiagnosticItem {
  id: number
  business_date: string
  diagnostic_type: string
  severity: string
  confidence: number
  owner_team?: string
  title: string
  summary: string
  root_cause?: string
  details_json: Record<string, any>
}

export interface SourceHealthItem {
  source: string
  source_type?: string
  configured: boolean
  enabled: boolean
  sync_mode: string
  last_success_at?: string
  last_failure_at?: string
  last_error?: string
  latest_run_status: string
  latest_run_started_at?: string
  latest_run_finished_at?: string
  latest_records_processed: number
  derived_status: string
  status_summary: string
  stale_minutes?: number
  blocks_connector_health?: boolean
}

export interface IssueClusterItem {
  id: number
  title: string
  severity: string
  confidence: number
  owner_team?: string
  details_json: Record<string, any>
}

export interface IssueSignalItem {
  id: number
  title: string
  summary: string
  severity: string
  confidence: number
  source: string
  metadata_json: Record<string, any>
}

export interface IssueRadarResponse {
  signals: IssueSignalItem[]
  clusters: IssueClusterItem[]
  highest_business_risk: IssueClusterItem[]
  highest_burden: IssueClusterItem[]
  fastest_rising: IssueClusterItem[]
  source_breakdown: { source: string; live: boolean; signals: number; clusters: number }[]
  trend_heatmap: { theme: string; points: { business_date: string; count: number; tickets_per_100_orders?: number | null }[] }[]
  live_sources: string[]
  scaffolded_sources: string[]
  classification_report?: Record<string, unknown>
}

export interface DataQualityItem {
  business_date?: string
  type?: string
  message?: string
  warnings?: string[]
  severity?: 'good' | 'warn' | 'bad'
  [key: string]: unknown
}

export interface DataQualityResponse {
  validation_warnings: DataQualityItem[]
  source_drift: DataQualityItem[]
  missing_data: DataQualityItem[]
}

export interface TelemetryLatestSummary {
  business_date: string
  sessions: number
  connected_users: number
  cook_success_rate: number
  disconnect_rate: number
  temp_stability_score: number
  avg_time_to_stabilization_seconds: number
  manual_override_rate: number
  firmware_health_score: number
  session_reliability_score: number
  error_rate: number
}

export interface TelemetryHealthRow {
  key: string
  sessions: number
  disconnect_rate: number
  manual_override_rate: number
  failure_rate: number
  health_score: number
  severity: string
}

export interface TelemetryPatternRow {
  pattern: string
  count: number
}

export interface TelemetryErrorCodeRow {
  code: string
  count: number
}

export interface TelemetryCollectionMetadata {
  source?: string
  region?: string
  table?: string
  sample_source?: string
  records_loaded?: number
  sessions_derived?: number
  days_materialized?: number
  max_records?: number
  devices_observed?: number
  distinct_devices_observed?: number
  distinct_engaged_devices_observed?: number
  oldest_sample_timestamp_seen?: string | null
  newest_sample_timestamp_seen?: string | null
  samples_retained?: number
  excluded_records?: number
  excluded_breakdown?: Record<string, number>
  invalid_records?: number
  duplicate_samples?: number
  sessions_merged_away?: number
  short_sessions_filtered?: number
  pages_scanned?: number | null
  scan_truncated?: boolean
  raw_rows_scanned?: number
  recent_rows_after_cutoff?: number
  max_record_cap_hit?: boolean
  session_gap_timeout_minutes?: number
  coverage_summary?: string
}

export interface TelemetryConfidence {
  global_completeness: string
  session_derivation: string
  disconnect_detection: string
  cook_success: string
  manual_override: string
  reason: string
}

export interface TelemetrySliceSnapshot {
  distinct_devices_observed: number
  distinct_engaged_devices_observed: number
  sessions_derived: number
  average_session_duration_seconds: number
  median_session_duration_seconds: number
  low_rssi_session_rate: number
  error_vector_presence_rate: number
  target_temp_distribution: Array<{ target_temp: string, count: number }>
}

export interface TelemetrySummary {
  latest?: TelemetryLatestSummary | null
  daily: Array<Record<string, any>>
  firmware_health: TelemetryHealthRow[]
  grill_type_health: TelemetryHealthRow[]
  top_error_codes: TelemetryErrorCodeRow[]
  top_issue_patterns: TelemetryPatternRow[]
  slice_snapshot?: TelemetrySliceSnapshot
  collection_metadata?: TelemetryCollectionMetadata
  confidence?: TelemetryConfidence
}

export interface OverviewResponse {
  latest_kpi?: KPIDaily
  daily_series: KPIDaily[]
  alerts: AlertItem[]
  diagnostics: DiagnosticItem[]
  recommendations: RecommendationItem[]
  source_health: SourceHealthItem[]
  telemetry?: TelemetrySummary | null
}

export type KpiDisplayRow = {
  business_date: string
} & {
  [K in Exclude<keyof KPIDaily, 'business_date'>]: KPIDaily[K] | null
}

export interface FreshdeskAgentDailyItem {
  business_date: string
  agent_id: string
  agent_name?: string
  tickets_resolved: number
  first_response_hours: number
  resolution_hours: number
}

export interface FreshdeskTicketItem {
  ticket_id: string
  subject?: string
  status?: string
  priority?: string
  channel?: string
  group_name?: string
  requester_id?: string
  agent_id?: string
  created_at_source?: string
  updated_at_source?: string
  resolved_at_source?: string
  first_response_hours?: number
  resolution_hours?: number
  csat_score?: number
  tags_json?: string[]
  category?: string
  raw_payload?: Record<string, any>
}

export interface SupportOverviewResponse {
  rows: KPIDaily[]
}

export interface CXActionItem {
  id: string
  trigger_kpi: string
  trigger_condition: string
  dedup_key: string
  owner: string
  co_owner?: string | null
  escalation_owner?: string | null
  title: string
  required_action: string
  priority: 'low' | 'medium' | 'high' | 'critical'
  status: 'open' | 'in_progress' | 'resolved'
  evidence: any[]
  opened_at: string
  updated_at: string
  resolved_at?: string | null
  auto_close_rule: Record<string, any>
  snapshot_timestamp: string
}

export interface CXMetricItem {
  key: string
  label: string
  owner: string
  current: number
  target: number
  delta: number
  trend7d: number
  trend30d: number
  status: KPIStatus
  confidence?: 'normal' | 'low'
  trigger_condition?: string | null
  critical_immediate?: boolean
  consecutive_bad_days?: number
  consecutive_green_days?: number
  snapshot_timestamp: string
}

export interface CXInsightItem {
  text: string
  evidence: string[]
  snapshot_timestamp: string
}

export interface CXTeamLoadItem {
  name: string
  tickets_closed_per_day: number
  active_queue_size: number
  throughput_ratio: number
  avg_close_time: number
  reopen_rate: number
  share_pct: number
  snapshot_timestamp: string
}

export interface CXSnapshotResponse {
  snapshot_timestamp?: string | null
  header_metrics: CXMetricItem[]
  grid_metrics: CXMetricItem[]
  actions: CXActionItem[]
  today_focus: CXActionItem[]
  team_load: CXTeamLoadItem[]
  insights: CXInsightItem[]
}

export type KpiDisplayMode = 'latest_complete_day' | 'today_intraday' | 'selected_range_summary'
export type IntradayStatus = 'live' | 'partial' | 'delayed' | 'unavailable'
export type RangeOption = 7 | 14 | 30 | 90
