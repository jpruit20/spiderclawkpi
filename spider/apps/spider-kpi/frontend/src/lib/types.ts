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

export interface OverviewResponse {
  latest_kpi?: KPIDaily
  daily_series: KPIDaily[]
  alerts: AlertItem[]
  diagnostics: DiagnosticItem[]
  recommendations: RecommendationItem[]
  source_health: SourceHealthItem[]
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
  status: 'green' | 'yellow' | 'red'
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
