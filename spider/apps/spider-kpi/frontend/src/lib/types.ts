export interface AuthUserSummary {
  id: string
  email: string
  is_admin: boolean
  ai_divisions?: string[]
  ai_enabled?: boolean
}

export interface AuthStatusResponse {
  authenticated: boolean
  auth_disabled?: boolean
  allowed_domains?: string[]
  user?: AuthUserSummary | null
}

export interface AuthCodeRequestResponse {
  ok: boolean
  detail: string
}

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
  gross_revenue: number
  refunds: number
  total_discounts: number
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
  details_json?: Record<string, unknown>
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
  engaged_latest_devices?: number
  active_devices_last_5m?: number
  active_devices_last_15m?: number
  active_devices_last_60m?: number
  active_devices_last_24h?: number
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
  data_scope?: 'live_stream' | 'historical_daily'
  historical_backfill_loaded?: boolean
  historical_months_loaded?: number
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
  distinct_engaged_devices_observed?: number
  engaged_latest_devices?: number
  active_devices_last_5m?: number
  active_devices_last_15m?: number
  active_devices_last_60m?: number
  active_devices_last_24h?: number
  sessions_derived: number
  recent_activity_window_minutes?: number
  average_session_duration_seconds?: number
  median_session_duration_seconds?: number
  average_events_per_device_in_slice?: number
  median_events_per_device_in_slice?: number
  low_rssi_session_rate: number
  error_vector_presence_rate: number
  target_temp_distribution: Array<{ target_temp: string, count: number }>
}

export interface TelemetryFunnelStep {
  step: string
  sessions: number
  rate: number
}

export interface TelemetryDropoffReason {
  reason: string
  sessions: number
  rate: number
}

export interface TelemetryCurvePoint {
  minute_bucket: number
  p50_temp_delta: number | null
  p90_temp_delta: number | null
  sessions: number
}

export interface TelemetryArchetypeRow {
  archetype: string
  sessions: number
  rate: number
  description: string
}

export interface TelemetryProbeRow {
  probe_count: number
  sessions: number
  rate: number
}

export interface TelemetryConnectivityBucket {
  bucket: string
  sessions: number
  failure_rate: number
  stability_score: number | null
  disconnect_rate?: number | null
}

export interface TelemetryIssueInsight {
  issue: string
  signal: string
  cohort: string
  confidence: 'low' | 'medium' | 'high'
  action: string
}

export interface TelemetryDerivedMetrics {
  stability_score?: number | null
  overshoot_rate?: number | null
  oscillation_rate?: number | null
  timeout_rate?: number | null
  time_to_stabilize_seconds?: number | null
  time_to_stabilize_p50_seconds?: number | null
  time_to_stabilize_p95_seconds?: number | null
  disconnect_proxy_rate?: number | null
  session_success_rate?: number | null
  active_cooks_now?: number | null
  cooks_started_24h?: number | null
  cooks_completed_24h?: number | null
  median_cook_duration_seconds?: number | null
  p95_cook_duration_seconds?: number | null
  median_rssi_now?: number | null
  devices_reporting_last_5m?: number | null
  devices_reporting_last_15m?: number | null
}

export interface TelemetryAnalytics {
  cook_lifecycle_funnel: TelemetryFunnelStep[]
  dropoff_reasons: TelemetryDropoffReason[]
  pit_temperature_curve: TelemetryCurvePoint[]
  session_archetypes: TelemetryArchetypeRow[]
  probe_usage: TelemetryProbeRow[]
  probe_failure_rate?: number | null
  pit_probe_delta_avg?: number | null
  connectivity_buckets: TelemetryConnectivityBucket[]
  issue_insights: TelemetryIssueInsight[]
  derived_metrics?: TelemetryDerivedMetrics
}

export interface TelemetryHistoryDailyRow {
  business_date: string
  active_devices: number
  engaged_devices: number
  total_events: number
  avg_rssi: number | null
  error_events: number
  firmware_distribution: Record<string, number>
  model_distribution: Record<string, number>
  avg_cook_temp: number | null
  peak_hour_distribution: Record<string, number>
  source: string
}

export interface CookStyleDetail {
  count: number
  pct: number
  avg_duration_seconds: number
  median_duration_seconds: number
  avg_stability_score: number | null
  success_rate: number | null
}

export interface CookAnalysis {
  total_sessions: number
  cook_styles: Record<string, number>
  temp_ranges: Record<string, number>
  duration_ranges: Record<string, number>
  style_details: Record<string, CookStyleDetail>
}

export interface ClusterTicketDetail {
  theme: string
  theme_title: string
  total_tickets: number
  unique_customers: number
  customer_ratio: number
  severity_adjustment: 'upgraded' | 'downgraded' | 'unchanged'
  severity_reason: string
  status_breakdown: Record<string, number>
  priority_breakdown: Record<string, number>
  channel_breakdown: Record<string, number>
  sub_topics: { keyword: string; count: number }[]
  top_requesters: { requester_id: string; ticket_count: number }[]
  tickets: {
    ticket_id: string
    subject: string
    status: string
    priority: string
    channel: string
    requester_id: string
    created_at: string | null
    updated_at: string | null
    resolved_at: string | null
    first_response_hours: number | null
    resolution_hours: number | null
    confidence: number
    tags: string[]
  }[]
  owner_team: string
  impact: Record<string, any>
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
  analytics?: TelemetryAnalytics
  history_daily?: TelemetryHistoryDailyRow[]
  cook_analysis?: CookAnalysis
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

export interface SocialMention {
  id: number
  platform: string
  external_id: string
  source_url?: string
  title?: string
  body?: string
  author?: string
  subreddit?: string
  engagement_score: number
  comment_count: number
  sentiment: 'positive' | 'negative' | 'neutral' | 'mixed'
  sentiment_score: number
  classification: string
  brand_mentioned: boolean
  product_mentioned?: string
  competitor_mentioned?: string
  trend_topic?: string
  relevance_score: number
  published_at?: string
}

export interface SocialPulse {
  period_days: number
  total_mentions: number
  brand_mentions: number
  avg_sentiment_score: number
  sentiment_breakdown: Record<string, number>
  by_platform: Record<string, number>
  top_mentions: SocialMention[]
}

export interface ClarityPageMetric {
  url: string
  page_path: string
  page_type: string
  sessions: number
  dead_clicks: number
  dead_click_pct: number
  rage_clicks: number
  rage_click_pct: number
  quick_backs: number
  quick_back_pct: number
  script_errors: number
  script_error_pct: number
  excessive_scroll: number
  friction_score: number
  snapshot_date: string
}

export interface SocialTrendsResponse {
  period_days: number
  total_mentions: number
  trending_topics: { topic: string; mention_count: number; total_engagement: number }[]
  by_classification: Record<string, number>
  by_platform: Record<string, number>
  competitor_mentions: Record<string, number>
  product_mentions: Record<string, number>
}

export interface YouTubeVideoComment {
  author: string
  text: string
  likes: number
  published_at?: string
}

export interface YouTubeVideo {
  video_id: string
  title: string
  author: string
  source_url: string
  views: number
  likes: number
  comments: number
  engagement_rate: number
  sentiment: 'positive' | 'negative' | 'neutral' | 'mixed'
  product_mentioned?: string
  competitor_mentioned?: string
  published_at?: string
  top_comments?: YouTubeVideoComment[]
}

export interface YouTubePerformance {
  period_days: number
  total_videos: number
  total_views: number
  total_likes: number
  total_comments: number
  avg_engagement_rate: number
  sentiment_breakdown: Record<string, number>
  top_videos: YouTubeVideo[]
  comment_highlights: YouTubeVideoComment[]
}

export interface AmazonProduct {
  asin: string
  title: string
  source_url: string
  brand: string
  bsr: number | null
  bsr_category: string | null
  competitive_price: number | null
  listed_price: number | null
  image_url: string | null
  last_updated: string | null
}

export interface AmazonProductHealth {
  total_products: number
  products: AmazonProduct[]
  avg_bsr: number | null
  best_bsr: number | null
  avg_price: number | null
  price_range: { min: number; max: number } | null
}

export interface MarketCompetitor {
  competitor: string
  mentions: number
  share_of_voice: number
  avg_sentiment: number
  total_engagement: number
  sentiment_label: 'positive' | 'negative' | 'neutral'
}

export interface MarketPost {
  title: string
  body: string
  platform: string
  source_url: string
  engagement_score: number
  comment_count: number
  competitor_mentioned?: string
  product_mentioned?: string
  competitor?: string
  sentiment_score?: number
  trend_topic?: string
  published_at?: string
}

export interface TrendMomentum {
  topic: string
  mentions: number
  total_engagement: number
  platforms: string[]
  cross_platform: boolean
  momentum: 'strong' | 'growing' | 'emerging'
}

export interface MarketIntelligence {
  period_days: number
  total_mentions: number
  by_platform: Record<string, number>
  by_classification: Record<string, number>
  competitive_landscape: {
    brand_mentions: number
    brand_engagement: number
    brand_share_of_voice: number
    competitors: MarketCompetitor[]
  }
  purchase_intent: {
    total: number
    posts: MarketPost[]
  }
  product_innovation: {
    total: number
    posts: MarketPost[]
  }
  competitor_pain_points: {
    total: number
    posts: MarketPost[]
  }
  trend_momentum: TrendMomentum[]
  amazon_positioning: {
    price: { our_avg_price: number; competitor_avg_price: number; price_delta_pct: number; position: string } | null
    bsr: { our_best_bsr: number; competitor_best_bsr: number; our_product_count: number; competitor_product_count: number; outranking_competitors: boolean } | null
    our_products: number
    competitor_products: number
  }
}

// DECI Decision Framework
export interface DeciDomain {
  id: number
  name: string
  description?: string
  category: string
  default_driver_id?: number
  default_driver_name?: string
  default_executor_ids: number[]
  default_contributor_ids: number[]
  default_informed_ids: number[]
  escalation_owner_id?: number
  escalation_owner_name?: string
  escalation_threshold_days: number
  active: boolean
  sort_order: number
  decision_count: number
  created_at: string
  updated_at: string
}

export interface DeciDomainStat {
  id: number
  name: string
  category: string
  total_decisions: number
  active_decisions: number
  default_driver_name?: string
  escalation_owner_name?: string
}

export interface DeciEscalationWarning {
  id: string
  title: string
  domain: string
  days_stale: number
  threshold_days: number
  escalation_owner?: string
}

export interface DeciMatrixMember {
  id: number
  name: string
  role?: string
  department?: string
}

export interface DeciMatrixRow {
  domain_id: number
  name: string
  description?: string
  assignments: Record<string, string | null>  // member_id -> D/E/C/I/null
  active_decisions: number
}

export interface DeciMatrixResponse {
  members: DeciMatrixMember[]
  categories: Record<string, DeciMatrixRow[]>
}

export interface DeciTeamMember {
  id: number
  name: string
  email?: string
  role?: string
  department?: string
  active: boolean
}

export type DeciDecisionType = 'KPI' | 'Project' | 'Initiative' | 'Issue'
export type DeciStatus = 'not_started' | 'in_progress' | 'blocked' | 'complete'
export type DeciPriority = 'low' | 'medium' | 'high' | 'critical'
export type DeciRole = 'executor' | 'contributor' | 'informed'

export interface DeciAssignment {
  id: number
  member_id: number
  member_name: string
  role: DeciRole
}

export interface DeciDecisionLog {
  id: number
  decision_text: string
  made_by: string
  notes?: string
  created_at: string
}

export interface DeciKpiLink {
  id: number
  kpi_name: string
  created_at: string
}

export interface DeciDecision {
  id: string
  title: string
  description?: string
  type: DeciDecisionType
  status: DeciStatus
  priority: DeciPriority
  department?: string
  driver_id?: number
  driver_name?: string
  domain_id?: number
  escalation_status: string
  escalated_at?: string
  cross_functional: boolean
  due_date?: string
  resolved_at?: string
  executors: DeciAssignment[]
  contributors: DeciAssignment[]
  informed: DeciAssignment[]
  logs: DeciDecisionLog[]
  kpi_links: DeciKpiLink[]
  created_by?: string
  created_at: string
  updated_at: string
}

export interface DeciBottleneck {
  id: string
  title: string
  type: string
  reason: string
  status: string
  priority: string
  department?: string
  updated_at: string
}

export interface DeciOwnershipEntry {
  member: DeciTeamMember
  driver_count: number
  executor_count: number
  blocked_count: number
}

export interface DeciOverview {
  bottlenecks: {
    no_driver: DeciBottleneck[]
    stale: DeciBottleneck[]
    overloaded_contributors: DeciBottleneck[]
  }
  ownership_map: DeciOwnershipEntry[]
  critical_feed: DeciDecision[]
  velocity: {
    avg_creation_to_decision_hours: number | null
    avg_decision_to_complete_hours: number | null
    total_decisions: number
    completed_decisions: number
  }
  domain_stats: DeciDomainStat[]
  escalation_warnings: DeciEscalationWarning[]
}

export interface GithubIssue {
  id: number
  number: number
  title: string
  state: string
  html_url: string
  labels: string[]
  created_at: string
  updated_at: string
  user: string | null
  assignees: string[]
  priority: string | null
  is_bug: boolean
}

export interface GithubIssuesResponse {
  issues: GithubIssue[]
  total_count: number
  configured: boolean
  repo?: string
  fetched_at?: string
  error?: string
}

export interface AppSideDistributionItem {
  value: string
  count: number
  pct: number
}

export interface AppSideSourceDailyRow {
  business_date: string
  observations: number
  unique_users: number
  unique_devices: number
}

export interface AppSideSourceStats {
  observations: number
  unique_users_window: number
  unique_devices_window: number
  device_observations_without_mac: number
  connected: boolean
  daily: AppSideSourceDailyRow[]
  app_version_top: AppSideDistributionItem[]
  firmware_version_top: AppSideDistributionItem[]
  controller_model_top: AppSideDistributionItem[]
  phone_os_top: AppSideDistributionItem[]
  phone_brand_top: AppSideDistributionItem[]
  phone_model_top: AppSideDistributionItem[]
}

export interface AppSideCombinedStats {
  unique_users_window: number
  unique_devices_window: number
  app_version_top: AppSideDistributionItem[]
  firmware_version_top: AppSideDistributionItem[]
  controller_model_top: AppSideDistributionItem[]
  phone_os_top: AppSideDistributionItem[]
  phone_brand_top: AppSideDistributionItem[]
  phone_model_top: AppSideDistributionItem[]
}

export interface AppSideOverlap {
  users_in_both?: number
  devices_in_both?: number
  users_only_freshdesk?: number
  users_only_app_backend?: number
}

/* Executive morning brief -------------------------------------------------- */

export interface MorningDraft {
  id: string
  title: string
  priority: string
  department: string | null
  origin_signal_type: string | null
  auto_drafted_at: string | null
}

export interface MorningCriticalSignal {
  id: number
  signal_type: string
  source: string
  title: string | null
  summary: string | null
  created_at: string | null
  metadata: {
    channel_id?: string | null
    task_id?: string | null
    url?: string | null
  }
}

export interface MorningStaleTask {
  task_id: string
  name: string | null
  url: string | null
  priority: string | null
  space_name: string | null
  list_name: string | null
  due_date: string | null
  days_overdue: number
  assignees: (string | null)[]
}

export interface MorningRevenuePoint {
  date: string
  revenue: number
}

export interface MorningRevenue {
  trailing_7: number
  prior_7: number
  wow_delta: number
  wow_pct: number | null
  sparkline: MorningRevenuePoint[]
}

export interface MorningTelemetry {
  business_date: string
  /** Live 15-min active-device count (matches PE page) when available;
   *  falls back to yesterday's complete daily rollup count. */
  active_devices: number
  active_devices_live_15m?: number
  active_devices_yesterday?: number
  engaged_devices: number
  total_events: number
  error_events: number
  error_rate: number | null
  cook_success_rate: number | null
  session_count: number | null
}

export interface MorningCompliance {
  taxonomy_configured: boolean
  rate_closed_in_window: number | null
  rate_open_now: number | null
  wow_delta_rate: number | null
  total_closed_in_window: number
}

export interface MorningSlackHot {
  channel_id: string
  user_name: string | null
  reactions: number
  text: string
  ts_dt: string | null
}

export interface WismoTicket {
  ticket_id: string
  subject: string | null
  created_at: string | null
  status: string | null
  priority: string | null
  requester_id: string | null
  confidence: number
  matched_rule: string | null
  url: string | null
}

export interface WismoKpiResponse {
  ok: boolean
  generated_at: string
  window_days: number
  window_start: string
  tickets_in_window: number
  wismo_count: number
  wismo_pct_of_tickets: number
  orders_in_window: number
  rate_per_100_orders: number | null
  trend: Array<{ date: string; wismo: number; orders: number }>
  week_over_week: { last_7: number; prior_7: number; delta_pct: number | null }
  recent_tickets: WismoTicket[]
}

export interface ProbeFailureTicket {
  ticket_id: string
  subject: string | null
  created_at: string | null
  status: string | null
  priority: string | null
  confidence: number
  matched_rule: string | null
  url: string | null
}

export interface ProbeFailureRateResponse {
  ok: boolean
  generated_at: string
  window_days: number
  window_start: string
  tickets_in_window: number
  probe_failure_count: number
  probe_failure_pct_of_tickets: number
  active_devices_in_window: number
  installed_base_venoms: number
  rate_per_1000_active_30d: number | null
  annualized_rate_per_installed_base: number | null
  annualized_failures_projected: number | null
  trend: Array<{ date: string; probe_failures: number }>
  week_over_week: { last_7: number; prior_7: number; delta_pct: number | null }
  recent_tickets: ProbeFailureTicket[]
}


export interface FirmwareCohort {
  firmware_version: string
  sessions: number
  /** Legacy success rate — retained for back-compat; prefer held_target_rate. */
  success_rate: number
  avg_stability: number
  avg_duration_seconds: number
  avg_tts_seconds: number | null
  error_session_rate: number
  total_errors: number
  avg_target_temp: number | null
  first_seen: string | null
  last_seen: string | null
  /** Intent/outcome/PID-quality (new model, added 2026-04-18). Null
   *  while the re-derivation hasn't populated yet. */
  held_target_rate: number | null
  target_seeking_sessions: number
  startup_assist_sessions: number
  reached_not_held_sessions: number
  did_not_reach_sessions: number
  avg_in_control_pct: number | null
  avg_disturbances_per_cook: number | null
  avg_recovery_seconds: number | null
  avg_max_overshoot_f: number | null
}

export interface FirmwareImpactWeek {
  week_start: string
  dominant_firmware: string | null
  in_control_pct: number | null
  held_target_rate: number | null
  avg_disturbances_per_cook: number | null
  avg_recovery_seconds: number | null
  sessions: number
  firmware_share: Record<string, number>
  sparse: boolean
}

export interface FirmwareRelease {
  date: string
  name: string
  url: string | null
}

export interface FirmwareImpactTimelineResponse {
  ok: boolean
  window_weeks: number
  start: string
  end: string
  series: FirmwareImpactWeek[]
  firmware_releases: FirmwareRelease[]
}

export interface CookDurationStats {
  ok: boolean
  source: string
  window_days: number
  total_sessions: number
  avg_duration_seconds: number | null
  median_duration_seconds: number | null
  median_is_estimate?: boolean
  p25_duration_seconds: number | null
  p75_duration_seconds: number | null
  p90_duration_seconds: number | null
  unique_devices: number
  unique_devices_is_partial?: boolean
  unique_devices_source_days?: number
  avg_sessions_per_device: number | null
  median_sessions_per_device: number | null
  sessions_per_device_histogram: Record<string, number> | null
  top_device_sessions: Array<{ device_id_short: string; sessions: number }>
  hint?: string
}

export interface CookOutcomesSummary {
  ok: boolean
  window_days: number
  totals: {
    sessions_scored: number
    held_count: number
    target_seeking_count: number
    held_target_rate: number | null
    avg_in_control_pct: number | null
    avg_disturbances_per_cook: number | null
    avg_recovery_seconds: number | null
  }
  intent_distribution: Array<{ intent: string; count: number }>
  outcome_distribution: Array<{ outcome: string; count: number }>
  daily_intent_series: Array<Record<string, number | string>>
}

export interface FirmwareCohortsResponse {
  ok: boolean
  reason?: string
  hint?: string
  total_sessions: number
  cohorts_returned?: number
  min_sessions_threshold?: number
  cohorts?: FirmwareCohort[]
}

export interface TelemetryAnomaly {
  id: number
  business_date: string
  metric: string
  value: number
  baseline_median: number
  modified_z_score: number
  direction: 'high' | 'low'
  severity: 'info' | 'warn' | 'critical'
  summary: string | null
}

export interface AIInsight {
  id: number
  business_date: string
  title: string
  observation: string
  confidence: number
  urgency: 'high' | 'medium' | 'low'
  evidence: string[]
  suggested_action: string | null
  sources_used: string[]
  status: string
  model?: string | null
  created_at?: string | null
}

export interface MorningBriefResponse {
  generated_at: string
  business_date: string
  headline: {
    drafts_awaiting_review: number
    critical_signals_24h: number
    overdue_urgent_or_high: number
    revenue_wow_pct: number | null
    clickup_wow_delta: number
    insights_count: number
    insights_high_urgency: number
    anomalies_count: number
    anomalies_critical: number
    wismo_last_7: number
    wismo_wow_delta: number
  }
  drafts: MorningDraft[]
  critical_signals: MorningCriticalSignal[]
  stale_tasks: MorningStaleTask[]
  revenue: MorningRevenue
  clickup_velocity: {
    closed_last_7: number
    closed_prior_7: number
    wow_delta: number
  }
  telemetry: MorningTelemetry | null
  compliance: MorningCompliance | null
  slack_hot: MorningSlackHot | null
  insights: AIInsight[]
  anomalies: TelemetryAnomaly[]
  wismo: { last_7: number; prior_7: number; delta: number }
}

export interface InsightsListResponse {
  count: number
  insights: AIInsight[]
}

export interface TelemetryReportFinding {
  title: string
  detail: string
  urgency: 'high' | 'medium' | 'low'
  category: string
}

export interface TelemetryReportRecommendation {
  title: string
  detail: string
  category: string
  effort: 'small' | 'medium' | 'large'
}

export interface TelemetryReportSection {
  title: string
  body_markdown: string
}

export interface TelemetryReport {
  id: number
  report_date: string
  report_type: 'comprehensive' | 'monthly'
  window_start: string
  window_end: string
  title: string
  summary: string
  sections: TelemetryReportSection[]
  benchmarks: Record<string, { value: string; interpretation: string }>
  key_findings: TelemetryReportFinding[]
  recommendations: TelemetryReportRecommendation[]
  sources_used: string[]
  model: string | null
  body_markdown?: string
  created_at: string | null
}

export interface LatestTelemetryReportResponse {
  ok: boolean
  reason?: string
  report?: TelemetryReport
}

/* Slack ------------------------------------------------------------------ */

export interface SlackChannelSummary {
  channel_id: string
  name: string | null
  is_private: boolean
  is_archived: boolean
  is_member: boolean
  num_members: number | null
  topic: string | null
  purpose: string | null
}

export interface SlackChannelsResponse {
  channels: SlackChannelSummary[]
  configured: boolean
}

export interface SlackDailyRow {
  business_date: string
  channel_id: string
  channel_name: string | null
  message_count: number
  unique_users: number
  reaction_count: number
  thread_count: number
  reply_count: number
  file_count: number
  peak_hour: number | null
}

export interface SlackMessageSummary {
  channel_id: string
  ts: string
  ts_dt: string | null
  thread_ts: string | null
  user_id: string | null
  user_name: string | null
  subtype: string | null
  text: string | null
  has_files: boolean
  file_count: number
  reaction_count: number
  reply_count: number
  is_deleted: boolean
}

export interface SlackPulseResponse {
  window: { start: string; end: string; days: number }
  channel: SlackChannelSummary | null
  totals: {
    messages: number
    reactions: number
    files: number
    replies: number
    unique_users_seen: number
  }
  daily: SlackDailyRow[]
  latest_message: SlackMessageSummary | null
  configured: boolean
}

export interface SlackMessagesResponse {
  messages: SlackMessageSummary[]
}

/* ClickUp ---------------------------------------------------------------- */

export interface ClickUpAssignee {
  id: string
  username?: string | null
  email?: string | null
}

export interface ClickUpTask {
  task_id: string
  custom_id?: string | null
  name?: string | null
  status?: string | null
  status_type?: string | null
  priority?: string | null
  space_id?: string | null
  space_name?: string | null
  folder_id?: string | null
  folder_name?: string | null
  list_id?: string | null
  list_name?: string | null
  assignees: ClickUpAssignee[]
  tags: string[]
  url?: string | null
  date_created?: string | null
  date_updated?: string | null
  date_done?: string | null
  due_date?: string | null
  archived: boolean
  is_open: boolean
}

export interface ClickUpTaskListResponse {
  tasks: ClickUpTask[]
  summary: {
    total: number
    open: number
    overdue: number
    by_status: Record<string, number>
    by_priority: Record<string, number>
  }
  configured: boolean
}

export interface ClickUpSpace {
  id: string
  name: string
  private: boolean
}

export interface ClickUpSpacesResponse {
  source: 'live' | 'db'
  spaces: ClickUpSpace[]
}

export interface ClickUpConfigResponse {
  configured: boolean
  team_id: string | null
  base_url: string
}

export interface ClickUpListItem {
  list_id: string
  list_name: string | null
  space_id: string | null
  space_name: string | null
  folder_name: string | null
}

export interface ClickUpListsResponse {
  lists: ClickUpListItem[]
}

export interface DeciDraftRecentLog {
  decision_text: string
  made_by: string
  created_at: string | null
}

export interface DeciDraft {
  id: string
  title: string
  description?: string | null
  status: string
  priority: string
  type: string
  department?: string | null
  origin_signal_type: string | null
  origin_context_key: string | null
  auto_drafted_at: string | null
  recent_logs: DeciDraftRecentLog[]
  [k: string]: unknown
}

export interface DeciDraftsResponse {
  drafts: DeciDraft[]
  count: number
}

export interface ClickUpVelocityDailyRow {
  date: string
  created: number
  completed: number
  open_pit: number
  overdue_pit: number
}

export interface ClickUpVelocityResponse {
  window: { start: string; end: string; days: number }
  space_id: string | null
  throughput: ClickUpVelocityDailyRow[]
  totals: {
    closed_last_7: number
    closed_prior_7: number
    wow_delta: number
    wow_pct: number | null
    open_now: number
    overdue_now: number
  }
  cycle_time: {
    median_seconds: number | null
    median_days: number | null
    p90_seconds: number | null
    p90_days: number | null
    sample_size: number
  }
  top_closers: { user: string; completed: number }[]
}

export interface ClickUpComplianceAssignee {
  user: string
  total: number
  compliant: number
  rate: number | null
}

export interface ClickUpComplianceTaskOffender {
  task_id: string
  name: string | null
  url: string | null
  space_name: string | null
  list_name: string | null
  status: string | null
  missing: string[]
  assignees: (string | null)[]
  date_done: string | null
}

export interface ClickUpComplianceCohort {
  total: number
  compliant: number
  rate: number | null
  by_assignee: ClickUpComplianceAssignee[]
  by_missing_field: Record<string, number>
  non_compliant: ClickUpComplianceTaskOffender[]
}

export interface ClickUpComplianceResponse {
  window: { start: string; end: string; days: number }
  space_id: string | null
  required_fields: { name: string; allowed_values: string[] }[]
  taxonomy_configured: boolean
  taxonomy_field_presence: Record<string, number>
  closed_in_window: ClickUpComplianceCohort
  open_now: ClickUpComplianceCohort
  prior_window: { total: number; rate: number | null }
  wow_delta_rate: number | null
}

export interface ClickUpTimelineEvent {
  event_type: 'due' | 'completed'
  date: string
  business_date: string
  task_id: string
  title: string | null
  url: string | null
  priority: string | null
  status: string | null
  space_name: string | null
  list_name: string | null
}

export interface ClickUpTimelineResponse {
  window: { start: string; end: string; days: number }
  filters: {
    space_id: string | null
    keyword: string | null
    event_types: string[]
    priorities: string[] | null
  }
  events: ClickUpTimelineEvent[]
  count: number
}

export interface ClickUpWebhookStatus {
  registered: boolean
  webhook_id: string | null
  endpoint_url: string | null
  configured_at: string | null
  events: string[]
}

export interface DeciClickUpLink {
  id: string
  title: string
  status: string
  clickup_task_id: string | null
  clickup_status_cached: string | null
  clickup_url: string | null
  clickup_last_synced_at: string | null
}

export interface ClickUpTaskFilter {
  space_id?: string
  list_id?: string
  folder_id?: string
  status_type?: 'open' | 'closed' | 'done'
  priority?: string
  assignee?: string
  due_within_days?: number
  overdue_only?: boolean
  q?: string
  limit?: number
}

export interface AppSideFleetResponse {
  window: { start: string; end: string; days: number }
  sources: {
    freshdesk: AppSideSourceStats
    app_backend: AppSideSourceStats
  }
  combined: AppSideCombinedStats
  overlap: AppSideOverlap
  latest_observed_at: string | null
  notes: {
    freshdesk: string
    app_backend: string
    combined: string
  }
}
