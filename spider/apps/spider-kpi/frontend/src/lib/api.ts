import type {
  AppSideFleetResponse,
  AuthCodeRequestResponse,
  ClickUpConfigResponse,
  ClickUpListsResponse,
  ClickUpSpacesResponse,
  ClickUpTaskFilter,
  ClickUpTaskListResponse,
  ClickUpComplianceResponse,
  ClickUpTimelineResponse,
  ClickUpVelocityResponse,
  ClickUpWebhookStatus,
  DeciClickUpLink,
  DeciDraft,
  CookDurationStats,
  CookOutcomesSummary,
  DeciDraftsResponse,
  EmailPulseResponse,
  FirmwareCohortsResponse,
  FirmwareImpactTimelineResponse,
  InsightsListResponse,
  LatestTelemetryReportResponse,
  MorningBriefResponse,
  WismoKpiResponse,
  ProbeFailureRateResponse,
  MarketingChannelMixResponse,
  MarketingChannelTrendsResponse,
  MarketingPacingResponse,
  MarketingMerHealthResponse,
  MarketingPeriodCompareResponse,
  SlackChannelsResponse,
  SlackMessagesResponse,
  SlackPulseResponse,
  AuthStatusResponse,
  ClarityPageMetric,
  ClusterTicketDetail,
  CXActionItem,
  CXSnapshotResponse,
  DataQualityResponse,
  DeciDecision,
  DeciDomain,
  DeciMatrixResponse,
  DeciOverview,
  DeciTeamMember,
  DiagnosticItem,
  FreshdeskAgentDailyItem,
  FreshdeskTicketItem,
  GithubIssuesResponse,
  IssueRadarResponse,
  KPIIntraday,
  KPIDaily,
  LoreMetricsResponse,
  MetricContextResponse,
  OverviewResponse,
  SeasonalBaselineResponse,
  SocialMention,
  SocialPulse,
  SocialTrendsResponse,
  ProductComplaintsResponse,
  WeeklyGaugeResponse,
  CookTimelineResponse,
  YouTubePerformance,
  AmazonProductHealth,
  MarketIntelligence,
  TelemetrySummary,
  RecommendationItem,
  SourceHealthItem,
  SupportOverviewResponse,
  LoreEvent,
  LoreEventImpactResponse,
  LoreEventsResponse,
  LoreEventCreate,
  LoreEventUpdate,
  LoreEventStats,
} from './types'

const DEFAULT_API_BASE = ''

function resolveApiBase() {
  const configured = (import.meta.env.VITE_API_BASE || DEFAULT_API_BASE).trim().replace(/\/$/, '')

  if (typeof window !== 'undefined') {
    const { hostname, origin } = window.location
    if (hostname === 'kpi.spidergrills.com') {
      return ''
    }
    if (configured && configured === origin) {
      return ''
    }
  }

  return configured
}

const API_BASE = resolveApiBase()

type RequestOptions = {
  signal?: AbortSignal
  timeoutMs?: number
  retries?: number
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
}

export class ApiError extends Error {
  status?: number
  path?: string

  constructor(message: string, status?: number, path?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.path = path
  }
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { signal, timeoutMs = 15000, retries = 1, method = 'GET', body } = options

  for (let attempt = 0; attempt <= retries; attempt += 1) {
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), timeoutMs)
    const abortListener = () => controller.abort()
    signal?.addEventListener('abort', abortListener)
    const startedAt = performance.now()
    console.info('[kpi-ui] api_request_start', { path, attempt, method })

    try {
      const init: RequestInit = {
        cache: 'no-store',
        signal: controller.signal,
        credentials: 'include',
        method,
      }
      if (body !== undefined) {
        init.headers = { 'Content-Type': 'application/json' }
        init.body = JSON.stringify(body)
      }
      const response = await fetch(`${API_BASE}${path}`, init)
      if (!response.ok) {
        const detail = await response.text().catch(() => '')
        throw new ApiError(`API error ${response.status} for ${path}${detail ? `: ${detail}` : ''}`, response.status, path)
      }
      const text = await response.text()
      try {
        const parsed = text ? JSON.parse(text) as T : (null as T)
        console.info('[kpi-ui] api_request_success', { path, attempt, durationMs: Math.round(performance.now() - startedAt) })
        return parsed
      } catch {
        throw new ApiError(`Invalid JSON returned for ${path}`, response.status, path)
      }
    } catch (error) {
      const apiError = error instanceof ApiError
        ? error
        : signal?.aborted
          ? new ApiError(`Request was aborted for ${path}`, undefined, path)
          : controller.signal.aborted
            ? new ApiError(`Request timed out for ${path}`, undefined, path)
            : new ApiError(`Network error for ${path}`, undefined, path)
      console.error('[kpi-ui] api_request_fail', { path, attempt, message: apiError.message, status: apiError.status })
      if (attempt < retries && !signal?.aborted) {
        window.clearTimeout(timeout)
        signal?.removeEventListener('abort', abortListener)
        continue
      }
      throw apiError
    } finally {
      window.clearTimeout(timeout)
      signal?.removeEventListener('abort', abortListener)
    }
  }

  throw new ApiError(`Exhausted retries for ${path}`, undefined, path)
}

export function getApiBase() {
  return API_BASE || 'same-origin /api'
}

export const api = {
  authStatus: (signal?: AbortSignal) => request<AuthStatusResponse>('/api/auth/status', { signal, retries: 0 }),
  signup: async (email: string, password: string) => {
    const response = await fetch(`${API_BASE}/api/auth/signup`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
    if (!response.ok) {
      const detail = await response.text().catch(() => '')
      throw new ApiError(`API error ${response.status} for /api/auth/signup${detail ? `: ${detail}` : ''}`, response.status, '/api/auth/signup')
    }
    return response.json() as Promise<AuthCodeRequestResponse>
  },
  login: async (email: string, password: string) => {
    const response = await fetch(`${API_BASE}/api/auth/login`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
    if (!response.ok) {
      const detail = await response.text().catch(() => '')
      throw new ApiError(`API error ${response.status} for /api/auth/login${detail ? `: ${detail}` : ''}`, response.status, '/api/auth/login')
    }
    return response.json() as Promise<AuthStatusResponse>
  },
  resendVerification: async (email: string) => {
    const response = await fetch(`${API_BASE}/api/auth/resend-verification`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    })
    if (!response.ok) {
      const detail = await response.text().catch(() => '')
      throw new ApiError(`API error ${response.status} for /api/auth/resend-verification${detail ? `: ${detail}` : ''}`, response.status, '/api/auth/resend-verification')
    }
    return response.json() as Promise<AuthCodeRequestResponse>
  },
  logout: async () => {
    const response = await fetch(`${API_BASE}/api/auth/logout`, {
      method: 'POST',
      credentials: 'include',
    })
    if (!response.ok) {
      throw new ApiError(`API error ${response.status} for /api/auth/logout`, response.status, '/api/auth/logout')
    }
    return response.json() as Promise<AuthStatusResponse>
  },
  overview: (signal?: AbortSignal) => request<OverviewResponse>('/api/overview', { signal }),
  dailyKpis: (signal?: AbortSignal) => request<KPIDaily[]>('/api/kpis/daily', { signal }),
  currentKpi: async (signal?: AbortSignal) => {
    const payload = await request<{ latest: KPIIntraday | null }>('/api/kpis/intraday', { signal })
    return payload.latest
  },
  intradaySeries: (signal?: AbortSignal) => request<{ rows: Array<{ bucket_start: string; business_date: string; hour_label: string; revenue: number; sessions: number; orders: number }> }>('/api/kpis/intraday-series', { signal }),
  diagnostics: (signal?: AbortSignal) => request<DiagnosticItem[]>('/api/diagnostics', { signal }),
  alerts: (signal?: AbortSignal) => request('/api/alerts', { signal }),
  recommendations: (signal?: AbortSignal) => request<RecommendationItem[]>('/api/recommendations', { signal }),
  sourceHealth: (signal?: AbortSignal) => request<SourceHealthItem[]>('/api/source-health', { signal }),
  telemetrySummary: (days?: number, signal?: AbortSignal, start?: string, end?: string) => {
    const params = new URLSearchParams()
    if (days) params.set('days', String(days))
    if (start) params.set('start', start)
    if (end) params.set('end', end)
    const qs = params.toString()
    return request<TelemetrySummary>(`/api/telemetry/summary${qs ? `?${qs}` : ''}`, { signal, timeoutMs: 45000 })
  },
  cookAnalysis: (start: string, end: string, signal?: AbortSignal) => request<Record<string, any>>(`/api/telemetry/cook-analysis?start=${start}&end=${end}`, { signal, timeoutMs: 30000 }),
  supportOverview: (signal?: AbortSignal) => request<SupportOverviewResponse>('/api/support/overview', { signal }),
  supportAgents: (signal?: AbortSignal) => request<FreshdeskAgentDailyItem[]>('/api/support/agents', { signal }),
  supportTickets: (signal?: AbortSignal) => request<FreshdeskTicketItem[]>('/api/support/tickets', { signal }),
  issues: (signal?: AbortSignal) => request<IssueRadarResponse>('/api/issues', { signal }),
  clusterDetail: (theme: string, signal?: AbortSignal) => request<ClusterTicketDetail>(`/api/issues/clusters/${encodeURIComponent(theme)}/detail`, { signal }),
  cxSnapshot: (signal?: AbortSignal) => request<CXSnapshotResponse>('/api/cx/snapshot', { signal }),
  shopifyOrderAging: (trendDays = 14, signal?: AbortSignal) =>
    request<OrderAgingResponse>(`/api/shopify/order-aging?trend_days=${trendDays}`, { signal }),
  fleetSize: (signal?: AbortSignal) =>
    request<FleetSizeResponse>('/api/fleet/size', { signal }),
  fleetLifetime: (signal?: AbortSignal) =>
    request<FleetLifetimeResponse>('/api/fleet/lifetime', { signal }),
  charcoalDeviceSessions: (mac: string, days = 730, signal?: AbortSignal) =>
    request<CharcoalDeviceSessionsResponse>(
      `/api/charcoal/device/${encodeURIComponent(mac)}/sessions?days=${days}`,
      { signal },
    ),
  charcoalFleetAggregate: (params: {
    start?: string; end?: string;
    grill_type?: string; firmware_version?: string; product_family?: string;
  }, signal?: AbortSignal) => {
    const qs = new URLSearchParams()
    if (params.start) qs.set('start', params.start)
    if (params.end) qs.set('end', params.end)
    if (params.grill_type) qs.set('grill_type', params.grill_type)
    if (params.firmware_version) qs.set('firmware_version', params.firmware_version)
    if (params.product_family) qs.set('product_family', params.product_family)
    return request<CharcoalFleetAggregateResponse>(
      `/api/charcoal/fleet/aggregate${qs.toString() ? `?${qs}` : ''}`,
      { signal },
    )
  },
  charcoalFleetFilters: (signal?: AbortSignal) =>
    request<CharcoalFleetFilters>('/api/charcoal/fleet/distinct-filters', { signal }),
  charcoalJITList: (status: string | undefined, signal?: AbortSignal) => {
    const qs = status ? `?status=${encodeURIComponent(status)}` : ''
    return request<CharcoalJITListResponse>(`/api/charcoal/jit/subscriptions${qs}`, { signal })
  },
  charcoalJITSubscribe: (payload: {
    mac: string
    user_key?: string
    fuel_preference: 'lump' | 'briquette'
    bag_size_lb: number
    lead_time_days: number
    safety_stock_days: number
    shipping_zip?: string
    notes?: string
    partner_product_id?: number
    margin_pct?: number
  }) =>
    request<{ ok: boolean; action: 'created' | 'updated'; subscription: CharcoalJITSubscription }>(
      '/api/charcoal/jit/subscribe',
      { method: 'POST', body: payload },
    ),
  charcoalJITPatch: (id: number, patch: Partial<{
    fuel_preference: 'lump' | 'briquette'
    bag_size_lb: number
    lead_time_days: number
    safety_stock_days: number
    shipping_zip: string
    status: 'active' | 'paused' | 'cancelled'
    notes: string
    partner_product_id: number | null
    margin_pct: number
  }>) =>
    request<{ ok: boolean; subscription: CharcoalJITSubscription }>(
      `/api/charcoal/jit/subscriptions/${id}`,
      { method: 'PATCH', body: patch },
    ),
  charcoalJITCancel: (id: number) =>
    request<{ ok: boolean; subscription: CharcoalJITSubscription }>(
      `/api/charcoal/jit/subscriptions/${id}`,
      { method: 'DELETE' },
    ),
  charcoalJITForecastOne: (id: number) =>
    request<{ ok: boolean; forecast: Record<string, unknown>; subscription: CharcoalJITSubscription }>(
      `/api/charcoal/jit/subscriptions/${id}/forecast`,
      { method: 'POST', body: {} },
    ),
  charcoalJITForecastAll: () =>
    request<{ computed_at: string; considered: number; forecasted_ok: number; skipped_no_device_id: number; no_sessions: number; zero_burn: number; shipping_address_backfilled: number }>(
      '/api/charcoal/jit/forecast-all',
      { method: 'POST', body: {}, timeoutMs: 120000 },
    ),
  charcoalPartnerProducts: (availableOnly = true, signal?: AbortSignal) =>
    request<CharcoalPartnerProductsResponse>(
      `/api/charcoal/partners/products?available_only=${availableOnly}`,
      { signal },
    ),
  charcoalPartnerRefresh: () =>
    request<{ computed_at: string; partners_refreshed: number; results: unknown[] }>(
      '/api/charcoal/partners/refresh',
      { method: 'POST', body: {}, timeoutMs: 120000 },
    ),
  charcoalModelingCohort: (payload: CharcoalCohortModelInput, signal?: AbortSignal) =>
    request<CharcoalCohortModelResponse>(
      '/api/charcoal/modeling/cohort',
      { method: 'POST', body: payload, signal, timeoutMs: 60000 },
    ),
  // ── Beta rollout: invitation engine ─────────────────────────────
  charcoalInvitationsPreview: (
    payload: CharcoalJITInvitationSelectionInput,
    signal?: AbortSignal,
  ) =>
    request<CharcoalJITInvitationPreviewResponse>(
      '/api/charcoal/jit/invitations/preview',
      { method: 'POST', body: payload, signal, timeoutMs: 60000 },
    ),
  charcoalInvitationsSendBatch: (
    payload: CharcoalJITInvitationBatchInput,
  ) =>
    request<CharcoalJITInvitationBatchResponse>(
      '/api/charcoal/jit/invitations/batches',
      { method: 'POST', body: payload, timeoutMs: 60000 },
    ),
  charcoalInvitationsListBatches: (signal?: AbortSignal) =>
    request<CharcoalJITInvitationBatchListResponse>(
      '/api/charcoal/jit/invitations/batches',
      { signal },
    ),
  charcoalInvitationsGetBatch: (batchId: string, signal?: AbortSignal) =>
    request<CharcoalJITInvitationBatchDetailResponse>(
      `/api/charcoal/jit/invitations/batches/${encodeURIComponent(batchId)}`,
      { signal },
    ),
  charcoalInvitationsRevoke: (id: number, reason?: string) =>
    request<{ ok: boolean; invitation: CharcoalJITInvitation }>(
      `/api/charcoal/jit/invitations/${id}/revoke`,
      { method: 'POST', body: { reason: reason ?? null } },
    ),
  charcoalInvitationsExpireStale: () =>
    request<{ ok: boolean; expired: number; computed_at: string }>(
      '/api/charcoal/jit/invitations/expire-stale',
      { method: 'POST', body: {} },
    ),
  shopifySyncUnfulfilled: () =>
    request<{ ok: boolean; records_processed: number; records_inserted?: number; records_updated?: number; duration_ms?: number }>(
      '/api/shopify/sync-unfulfilled',
      { method: 'POST', body: {}, timeoutMs: 180000 },
    ),
  weeklyGauges: (signal?: AbortSignal) =>
    request<WeeklyGaugeResponse>('/api/command-center/weekly-gauges', { signal }),
  regenerateWeeklyGauges: () =>
    request<{ ok: boolean; week_start: string; generated: number; duration_ms?: number; overall_theme?: string }>(
      '/api/command-center/weekly-gauges/regenerate',
      { method: 'POST', timeoutMs: 180000, retries: 0 },
    ),
  complaintsByProduct: (params: { q: string; aliases?: string; days?: number; sample?: number }, signal?: AbortSignal) => {
    const qs = new URLSearchParams()
    qs.set('q', params.q)
    if (params.aliases) qs.set('aliases', params.aliases)
    if (params.days != null) qs.set('days', String(params.days))
    if (params.sample != null) qs.set('sample', String(params.sample))
    return request<ProductComplaintsResponse>(`/api/complaints/by-product?${qs.toString()}`, { signal, timeoutMs: 30000 })
  },
  cxActions: (status?: string, signal?: AbortSignal) => request<CXActionItem[]>(`/api/cx/actions${status ? `?status=${encodeURIComponent(status)}` : ''}`, { signal }),
  updateCxAction: (id: string, status: 'open' | 'in_progress' | 'resolved') => fetch(`${API_BASE}/api/cx/actions/${id}/update`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  }).then(async (response) => {
    if (!response.ok) throw new ApiError(`API error ${response.status} for /api/cx/actions/${id}/update`, response.status, `/api/cx/actions/${id}/update`)
    return response.json() as Promise<CXActionItem>
  }),
  dataQuality: (signal?: AbortSignal) => request<DataQualityResponse>('/api/data-quality', { signal }),
  socialMentions: (params?: { platform?: string, classification?: string, days?: number }, signal?: AbortSignal) =>
    request<SocialMention[]>(`/api/social/mentions${params ? '?' + new URLSearchParams(Object.entries(params).filter(([,v]) => v != null).map(([k,v]) => [k, String(v)])).toString() : ''}`, { signal }),
  socialPulse: (days?: number, signal?: AbortSignal) =>
    request<SocialPulse>(`/api/social/pulse${days ? `?days=${days}` : ''}`, { signal }),
  socialTrends: (days?: number, signal?: AbortSignal) =>
    request<SocialTrendsResponse>(`/api/social/trends${days ? `?days=${days}` : ''}`, { signal }),
  youtubePerformance: (days?: number, signal?: AbortSignal) =>
    request<YouTubePerformance>(`/api/social/youtube-performance${days ? `?days=${days}` : ''}`, { signal }),
  amazonProducts: (signal?: AbortSignal) =>
    request<AmazonProductHealth>('/api/social/amazon-products', { signal }),
  marketIntelligence: (days?: number, signal?: AbortSignal) =>
    request<MarketIntelligence>(`/api/social/market-intelligence${days ? `?days=${days}` : ''}`, { signal }),
  // DECI Decision Framework
  deciTeam: (signal?: AbortSignal) =>
    request<DeciTeamMember[]>('/api/deci/team', { signal }),
  deciCreateTeamMember: (body: { name: string; email?: string; role?: string; department?: string }) =>
    fetch(`${API_BASE}/api/deci/team`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(r => r.json() as Promise<DeciTeamMember>),
  deciDecisions: (params?: { department?: string; status?: string; priority?: string; driver_id?: number }, signal?: AbortSignal) =>
    request<DeciDecision[]>(`/api/deci/decisions${params ? '?' + new URLSearchParams(Object.entries(params).filter(([,v]) => v != null).map(([k,v]) => [k, String(v)])).toString() : ''}`, { signal }),
  deciDecision: (id: string, signal?: AbortSignal) =>
    request<DeciDecision>(`/api/deci/decisions/${id}`, { signal }),
  deciCreateDecision: (body: Record<string, unknown>) =>
    fetch(`${API_BASE}/api/deci/decisions`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(r => r.json() as Promise<DeciDecision>),
  deciUpdateDecision: (id: string, body: Record<string, unknown>) =>
    fetch(`${API_BASE}/api/deci/decisions/${id}`, {
      method: 'PUT', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(r => r.json() as Promise<DeciDecision>),
  deciAddLog: (id: string, body: { decision_text: string; made_by: string; notes?: string }) =>
    fetch(`${API_BASE}/api/deci/decisions/${id}/log`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(r => r.json()),
  deciAddKpiLink: (id: string, body: { kpi_name: string }) =>
    fetch(`${API_BASE}/api/deci/decisions/${id}/kpi-links`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(r => r.json()),
  deciDeleteKpiLink: (decisionId: string, linkId: number) =>
    fetch(`${API_BASE}/api/deci/decisions/${decisionId}/kpi-links/${linkId}`, {
      method: 'DELETE', credentials: 'include',
    }).then(r => r.json()),
  deciOverview: (signal?: AbortSignal) =>
    request<DeciOverview>('/api/deci/overview', { signal }),
  deciDrafts: (signal?: AbortSignal) =>
    request<DeciDraftsResponse>('/api/deci/drafts', { signal }),
  deciPromoteDraft: (id: string) =>
    fetch(`${API_BASE}/api/deci/drafts/${id}/promote`, {
      method: 'POST', credentials: 'include',
    }).then(r => r.json() as Promise<DeciDraft>),
  deciDismissDraft: (id: string) =>
    fetch(`${API_BASE}/api/deci/drafts/${id}/dismiss`, {
      method: 'POST', credentials: 'include',
    }).then(r => r.json() as Promise<{ ok: boolean; id: string; status: string }>),
  // DECI Domains
  deciDomains: (signal?: AbortSignal) =>
    request<DeciDomain[]>('/api/deci/domains', { signal }),
  deciCreateDomain: (body: Record<string, unknown>) =>
    fetch(`${API_BASE}/api/deci/domains`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(r => r.json() as Promise<DeciDomain>),
  deciUpdateDomain: (id: number, body: Record<string, unknown>) =>
    fetch(`${API_BASE}/api/deci/domains/${id}`, {
      method: 'PUT', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(r => r.json() as Promise<DeciDomain>),
  deciDeleteDecision: (id: string) =>
    fetch(`${API_BASE}/api/deci/decisions/${id}`, {
      method: 'DELETE', credentials: 'include',
    }),
  deciDeleteDomain: (id: number) =>
    fetch(`${API_BASE}/api/deci/domains/${id}`, {
      method: 'DELETE', credentials: 'include',
    }).then(r => r.json() as Promise<{ ok: boolean; deleted_id: number; decisions_unlinked: number }>),
  deciSeedDomains: () =>
    fetch(`${API_BASE}/api/deci/domains/seed`, {
      method: 'POST', credentials: 'include',
    }).then(r => r.json() as Promise<{ seeded: number; domains: string[] }>),
  deciMatrix: (signal?: AbortSignal) =>
    request<DeciMatrixResponse>('/api/deci/matrix', { signal }),
  deciBootstrap: () =>
    fetch(`${API_BASE}/api/deci/bootstrap`, {
      method: 'POST', credentials: 'include',
    }).then(r => r.json() as Promise<{ team_created: number; domains_created: number; domains_updated: number }>),
  clarityFriction: (signal?: AbortSignal) => request<ClarityPageMetric[]>('/api/clarity/friction', { signal }),
  clarityPageHealth: (signal?: AbortSignal) => request<ClarityPageMetric[]>('/api/clarity/page-health', { signal }),
  engineeringIssues: (signal?: AbortSignal) => request<GithubIssuesResponse>('/api/engineering/issues', { signal }),
  // ClickUp --------------------------------------------------------------
  clickupConfig: (signal?: AbortSignal) =>
    request<ClickUpConfigResponse>('/api/clickup/config', { signal }),
  clickupSpaces: (signal?: AbortSignal) =>
    request<ClickUpSpacesResponse>('/api/clickup/spaces', { signal }),
  clickupLists: (space_id?: string, signal?: AbortSignal) =>
    request<ClickUpListsResponse>(`/api/clickup/lists${space_id ? `?space_id=${encodeURIComponent(space_id)}` : ''}`, { signal }),
  clickupTasks: (filter?: ClickUpTaskFilter, signal?: AbortSignal) => {
    const params = new URLSearchParams()
    if (filter) {
      for (const [k, v] of Object.entries(filter)) {
        if (v === undefined || v === null || v === '') continue
        params.set(k, String(v))
      }
    }
    const qs = params.toString()
    return request<ClickUpTaskListResponse>(`/api/clickup/tasks${qs ? `?${qs}` : ''}`, { signal })
  },
  clickupDeciSync: (decisionId: string, body: { list_id: string; name?: string; description?: string; priority?: number }) =>
    fetch(`${API_BASE}/api/clickup/deci/${decisionId}/sync`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(async r => {
      if (!r.ok) throw new ApiError(`API error ${r.status} for /api/clickup/deci/${decisionId}/sync`, r.status, `/api/clickup/deci/${decisionId}/sync`)
      return r.json() as Promise<DeciClickUpLink>
    }),
  clickupDeciLink: (decisionId: string, task_id: string) =>
    fetch(`${API_BASE}/api/clickup/deci/${decisionId}/link`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task_id }),
    }).then(r => r.json() as Promise<DeciClickUpLink>),
  clickupDeciRefresh: (decisionId: string) =>
    fetch(`${API_BASE}/api/clickup/deci/${decisionId}/refresh`, {
      method: 'POST', credentials: 'include',
    }).then(r => r.json() as Promise<DeciClickUpLink>),
  clickupDeciUnlink: (decisionId: string) =>
    fetch(`${API_BASE}/api/clickup/deci/${decisionId}/unlink`, {
      method: 'POST', credentials: 'include',
    }).then(r => r.json() as Promise<DeciClickUpLink>),
  clickupSyncNow: (full?: boolean) =>
    fetch(`${API_BASE}/api/clickup/sync-now${full ? '?full=true' : ''}`, {
      method: 'POST', credentials: 'include',
    }).then(r => r.json()),
  clickupTimeline: (
    opts?: {
      space_id?: string
      keyword?: string
      event_types?: string
      priorities?: string
      division?: string
      customer_impact?: string
      category?: string
      days?: number
      limit?: number
    },
    signal?: AbortSignal,
  ) => {
    const p = new URLSearchParams()
    if (opts) {
      for (const [k, v] of Object.entries(opts)) {
        if (v != null && v !== '') p.set(k, String(v))
      }
    }
    const qs = p.toString()
    return request<ClickUpTimelineResponse>(`/api/clickup/timeline${qs ? `?${qs}` : ''}`, { signal })
  },
  clickupCompliance: (space_id?: string, days?: number, signal?: AbortSignal) => {
    const p = new URLSearchParams()
    if (space_id) p.set('space_id', space_id)
    if (days) p.set('days', String(days))
    const qs = p.toString()
    return request<ClickUpComplianceResponse>(`/api/clickup/compliance${qs ? `?${qs}` : ''}`, { signal })
  },
  clickupVelocity: (space_id?: string, days?: number, signal?: AbortSignal) => {
    const p = new URLSearchParams()
    if (space_id) p.set('space_id', space_id)
    if (days) p.set('days', String(days))
    const qs = p.toString()
    return request<ClickUpVelocityResponse>(`/api/clickup/velocity${qs ? `?${qs}` : ''}`, { signal })
  },
  clickupWebhookStatus: (signal?: AbortSignal) =>
    request<ClickUpWebhookStatus>('/api/clickup/webhook/status', { signal }),
  clickupWebhookRegister: (endpoint_url: string) =>
    fetch(`${API_BASE}/api/clickup/webhook/register`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ endpoint_url }),
    }).then(r => r.json()),
  clickupWebhookUnregister: () =>
    fetch(`${API_BASE}/api/clickup/webhook/unregister`, {
      method: 'POST', credentials: 'include',
    }).then(r => r.json()),
  // Executive ------------------------------------------------------------
  morningBrief: (signal?: AbortSignal) =>
    request<MorningBriefResponse>('/api/executive/morning', { signal }),
  executiveInsights: (opts?: { limit?: number; include_dismissed?: boolean }, signal?: AbortSignal) => {
    const p = new URLSearchParams()
    if (opts?.limit) p.set('limit', String(opts.limit))
    if (opts?.include_dismissed) p.set('include_dismissed', 'true')
    const qs = p.toString()
    return request<InsightsListResponse>(`/api/executive/insights${qs ? `?${qs}` : ''}`, { signal })
  },
  latestTelemetryReport: (type: 'comprehensive' | 'monthly' = 'comprehensive', signal?: AbortSignal) =>
    request<LatestTelemetryReportResponse>(`/api/executive/telemetry-reports/latest?type=${type}`, { signal }),
  firmwareCohorts: (min_sessions: number = 20, signal?: AbortSignal) =>
    request<FirmwareCohortsResponse>(`/api/executive/firmware-cohorts?min_sessions=${min_sessions}`, { signal }),
  firmwareImpactTimeline: (weeks: number = 26, signal?: AbortSignal) =>
    request<FirmwareImpactTimelineResponse>(`/api/executive/firmware-impact-timeline?weeks=${weeks}`, { signal }),
  cookOutcomesSummary: (days: number = 90, signal?: AbortSignal) =>
    request<CookOutcomesSummary>(`/api/executive/cook-outcomes-summary?days=${days}`, { signal }),
  cookDurationStats: (days: number = 30, signal?: AbortSignal) =>
    request<CookDurationStats>(`/api/executive/cook-duration-stats?days=${days}`, { signal }),
  wismoKpi: (days: number = 30, signal?: AbortSignal) =>
    request<WismoKpiResponse>(`/api/executive/wismo-kpi?days=${days}`, { signal }),
  probeFailureRate: (days: number = 90, signal?: AbortSignal) =>
    request<ProbeFailureRateResponse>(`/api/executive/probe-failure-rate?days=${days}`, { signal }),

  // Marketing -----------------------------------------------------------
  marketingChannelMix: (
    opts: { start?: string; end?: string; days?: number; compare_prior?: boolean } = {},
    signal?: AbortSignal,
  ) => {
    const p = new URLSearchParams()
    if (opts.start) p.set('start', opts.start)
    if (opts.end) p.set('end', opts.end)
    if (opts.days != null) p.set('days', String(opts.days))
    if (opts.compare_prior === false) p.set('compare_prior', 'false')
    const qs = p.toString()
    return request<MarketingChannelMixResponse>(`/api/marketing/channel-mix${qs ? `?${qs}` : ''}`, { signal })
  },
  emailPulse: (
    opts: { start?: string; end?: string; days?: number; compare_prior?: boolean } = {},
    signal?: AbortSignal,
  ) => {
    const p = new URLSearchParams()
    if (opts.start) p.set('start', opts.start)
    if (opts.end) p.set('end', opts.end)
    if (opts.days != null) p.set('days', String(opts.days))
    if (opts.compare_prior === false) p.set('compare_prior', 'false')
    const qs = p.toString()
    return request<EmailPulseResponse>(`/api/email/pulse${qs ? `?${qs}` : ''}`, { signal })
  },

  marketingPeriodCompare: (
    opts: { start?: string; end?: string; days?: number; mode?: 'prior_period' | 'same_day_last_week' | 'yoy' } = {},
    signal?: AbortSignal,
  ) => {
    const p = new URLSearchParams()
    if (opts.start) p.set('start', opts.start)
    if (opts.end) p.set('end', opts.end)
    if (opts.days != null) p.set('days', String(opts.days))
    if (opts.mode) p.set('mode', opts.mode)
    const qs = p.toString()
    return request<MarketingPeriodCompareResponse>(`/api/marketing/period-compare${qs ? `?${qs}` : ''}`, { signal })
  },

  marketingChannelTrends: (
    opts: { days?: number; min_spend_total?: number } = {},
    signal?: AbortSignal,
  ) => {
    const p = new URLSearchParams()
    if (opts.days != null) p.set('days', String(opts.days))
    if (opts.min_spend_total != null) p.set('min_spend_total', String(opts.min_spend_total))
    const qs = p.toString()
    return request<MarketingChannelTrendsResponse>(`/api/marketing/channel-trends${qs ? `?${qs}` : ''}`, { signal })
  },

  marketingPacing: (signal?: AbortSignal) =>
    request<MarketingPacingResponse>(`/api/marketing/pacing`, { signal }),

  marketingMerHealth: (
    opts: { days?: number } = {},
    signal?: AbortSignal,
  ) => {
    const p = new URLSearchParams()
    if (opts.days != null) p.set('days', String(opts.days))
    const qs = p.toString()
    return request<MarketingMerHealthResponse>(`/api/marketing/mer-health${qs ? `?${qs}` : ''}`, { signal })
  },

  dismissInsight: (id: number, reason?: string) =>
    fetch(`${API_BASE}/api/executive/insights/${id}/dismiss${reason ? `?reason=${encodeURIComponent(reason)}` : ''}`, {
      method: 'POST', credentials: 'include',
    }).then(r => r.json()),

  // Slack ----------------------------------------------------------------
  slackChannels: (signal?: AbortSignal) =>
    request<SlackChannelsResponse>('/api/slack/channels', { signal }),
  slackPulse: (channel_id?: string, days?: number, signal?: AbortSignal) => {
    const p = new URLSearchParams()
    if (channel_id) p.set('channel_id', channel_id)
    if (days) p.set('days', String(days))
    const qs = p.toString()
    return request<SlackPulseResponse>(`/api/slack/pulse${qs ? `?${qs}` : ''}`, { signal })
  },
  slackMessages: (opts?: { channel_id?: string; thread_ts?: string; q?: string; since_days?: number; limit?: number }, signal?: AbortSignal) => {
    const p = new URLSearchParams()
    if (opts) for (const [k, v] of Object.entries(opts)) { if (v != null && v !== '') p.set(k, String(v)) }
    const qs = p.toString()
    return request<SlackMessagesResponse>(`/api/slack/messages${qs ? `?${qs}` : ''}`, { signal })
  },
  slackFileProxyUrl: (file_id: string) => `${API_BASE}/api/slack/files/${encodeURIComponent(file_id)}`,
  slackSyncNow: (full?: boolean) =>
    fetch(`${API_BASE}/api/slack/sync-now${full ? '?full=true' : ''}`, {
      method: 'POST', credentials: 'include',
    }).then(r => r.json()),
  appSideFleet: (days?: number, signal?: AbortSignal, start?: string, end?: string) => {
    const params = new URLSearchParams()
    if (days) params.set('days', String(days))
    if (start) params.set('start', start)
    if (end) params.set('end', end)
    const qs = params.toString()
    return request<AppSideFleetResponse>(`/api/telemetry/app-side${qs ? `?${qs}` : ''}`, { signal, timeoutMs: 30000 })
  },

  // Company Lore: seasonality ------------------------------------------
  loreMetrics: (signal?: AbortSignal) =>
    request<LoreMetricsResponse>('/api/lore/metrics', { signal }),
  loreSeasonalBaseline: (metric: string, start: string, end: string, signal?: AbortSignal) => {
    const p = new URLSearchParams({ metric, start, end })
    return request<SeasonalBaselineResponse>(`/api/lore/seasonal-baseline?${p.toString()}`, { signal })
  },
  loreMetricContext: (metric: string, on_date: string, value?: number, signal?: AbortSignal) => {
    const p = new URLSearchParams({ metric, on_date })
    if (value != null) p.set('value', String(value))
    return request<MetricContextResponse>(`/api/lore/metric-context?${p.toString()}`, { signal })
  },

  // Company Lore: event timeline --------------------------------------
  loreEvents: (
    opts: {
      start?: string; end?: string; division?: string;
      event_type?: string; confidence?: string;
      q?: string; limit?: number;
    } = {},
    signal?: AbortSignal,
  ) => {
    const p = new URLSearchParams()
    if (opts.start) p.set('start', opts.start)
    if (opts.end) p.set('end', opts.end)
    if (opts.division) p.set('division', opts.division)
    if (opts.event_type) p.set('event_type', opts.event_type)
    if (opts.confidence) p.set('confidence', opts.confidence)
    if (opts.q) p.set('q', opts.q)
    if (opts.limit != null) p.set('limit', String(opts.limit))
    const qs = p.toString()
    return request<LoreEventsResponse>(`/api/lore/events${qs ? `?${qs}` : ''}`, { signal })
  },
  loreEventGet: (id: number, signal?: AbortSignal) =>
    request<LoreEvent>(`/api/lore/events/${id}`, { signal }),
  loreEventCreate: (body: LoreEventCreate, signal?: AbortSignal) =>
    request<LoreEvent>('/api/lore/events', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    }),
  loreEventUpdate: (id: number, body: LoreEventUpdate, signal?: AbortSignal) =>
    request<LoreEvent>(`/api/lore/events/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    }),
  loreEventDelete: (id: number, signal?: AbortSignal) =>
    request<void>(`/api/lore/events/${id}`, { method: 'DELETE', signal }),
  loreEventStats: (opts: { start?: string; end?: string } = {}, signal?: AbortSignal) => {
    const p = new URLSearchParams()
    if (opts.start) p.set('start', opts.start)
    if (opts.end) p.set('end', opts.end)
    const qs = p.toString()
    return request<LoreEventStats>(`/api/lore/events/stats/summary${qs ? `?${qs}` : ''}`, { signal })
  },
  loreEventImpact: (
    id: number,
    opts: { before_days?: number; after_days?: number } = {},
    signal?: AbortSignal,
  ) => {
    const p = new URLSearchParams()
    if (opts.before_days != null) p.set('before_days', String(opts.before_days))
    if (opts.after_days != null) p.set('after_days', String(opts.after_days))
    const qs = p.toString()
    return request<LoreEventImpactResponse>(`/api/lore/events/${id}/impact${qs ? `?${qs}` : ''}`, { signal })
  },
  loreEventBulkUpdate: (
    body: { ids: number[]; confidence?: string; event_type?: string; division?: string | null },
    signal?: AbortSignal,
  ) =>
    request<{ updated: number; ids: number[] }>('/api/lore/events/bulk-update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    }),
  loreEventBulkDelete: (ids: number[], signal?: AbortSignal) =>
    request<{ deleted: number }>('/api/lore/events/bulk-delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
      signal,
    }),

  // ── Firmware Beta + Gamma Waves program ──────────────────────────
  betaIssueTags: (signal?: AbortSignal) =>
    request<{ tags: Array<{ id: number; slug: string; label: string; description: string | null; archived: boolean }> }>(
      '/api/beta/tags', { signal },
    ),
  betaIssueTagCreate: (body: { slug: string; label: string; description?: string }) =>
    request<{ id: number; slug: string; label: string; description: string | null; archived: boolean }>('/api/beta/tags', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  betaIssueTagUpdate: (id: number, body: { label?: string; description?: string; archived?: boolean }) =>
    request<{ id: number; slug: string; label: string; description: string | null; archived: boolean }>(`/api/beta/tags/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  betaReleases: (signal?: AbortSignal) =>
    request<{ releases: BetaReleaseSummary[] }>('/api/beta/releases', { signal }),
  betaReleaseCreate: (body: { version: string; title?: string; notes?: string; addresses_issues: string[]; beta_cohort_target_size?: number }) =>
    request<BetaReleaseSummary>('/api/beta/releases', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  betaReleaseUpdate: (id: number, body: Partial<{ title: string; notes: string; addresses_issues: string[]; status: string; beta_cohort_target_size: number }>) =>
    request<BetaReleaseSummary>(`/api/beta/releases/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  betaCandidates: (releaseId: number, limit = 150, signal?: AbortSignal) =>
    request<{ release_id: number; version: string; addresses_issues: string[]; candidates: Array<{ device_id: string; user_id: string | null; score: number; sessions_30d: number; tenure_days: number; matched_tags: string[] }> }>(
      `/api/beta/releases/${releaseId}/candidates?limit=${limit}`, { signal },
    ),
  betaInvite: (releaseId: number, cohortSize?: number) =>
    request<{ ok: boolean; invited_count: number; already_invited: number; candidates_found: number; cohort_target: number }>(
      `/api/beta/releases/${releaseId}/invite`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cohort_size: cohortSize }) },
    ),
  betaCohort: (releaseId: number, signal?: AbortSignal) =>
    request<{ release_id: number; version: string; members: Array<{ device_id: string; user_id: string | null; state: string; candidate_score: number | null; matched_tags: string[]; sessions_30d: number | null; tenure_days: number | null; invited_at: string | null; opted_in_at: string | null; opt_in_source: string | null; ota_pushed_at: string | null; evaluated_at: string | null; verdict: BetaVerdictEvidence }> }>(
      `/api/beta/releases/${releaseId}/cohort`, { signal },
    ),
  betaEvaluate: (releaseId: number, force = false) =>
    request<{ ok: boolean; release_id?: number; version?: string; tally?: Record<string, number>; release_health?: string; judgable_devices?: number }>(
      `/api/beta/releases/${releaseId}/evaluate?force=${force}`,
      { method: 'POST' },
    ),
  betaMarkOtaPushed: (releaseId: number, body: { device_ids?: string[]; mark_all_opted_in?: boolean }) =>
    request<{ ok: boolean; flipped: number }>(
      `/api/beta/releases/${releaseId}/mark-ota-pushed`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
    ),
  betaEvaluateAll: () =>
    request<{ ok: boolean; releases_evaluated: number }>('/api/beta/evaluate-all', { method: 'POST' }),
  betaSummary: (signal?: AbortSignal) =>
    request<BetaProgramSummary>('/api/beta/summary', { signal }),
  betaAlphaCohort: (signal?: AbortSignal) =>
    request<AlphaCohortResponse>('/api/beta/alpha-cohort', { signal }),
  betaAlphaBulkImport: (payload: {
    entries: Array<{ mac: string; user_id?: string; firmware_version_override?: string }>
    dry_run: boolean
    release_notes?: string
  }) =>
    request<AlphaBulkImportResult>('/api/beta/alpha-cohort/bulk-import', {
      method: 'POST',
      body: payload,
      timeoutMs: 120000,
    }),
  betaAlphaFirmwareTimeline: (mac: string, signal?: AbortSignal) =>
    request<AlphaFirmwareTimeline>(`/api/beta/alpha-cohort/${encodeURIComponent(mac)}/firmware-timeline`, { signal }),
  betaAlphaAnalytics: (signal?: AbortSignal) =>
    request<AlphaCohortAnalytics>('/api/beta/alpha-cohort/analytics', { signal }),
  betaAlphaTrend: (signal?: AbortSignal) =>
    request<AlphaCohortTrend>('/api/beta/alpha-cohort/trend', { signal }),
  betaAlphaErrorPatterns: (signal?: AbortSignal) =>
    request<AlphaCohortErrorPatterns>('/api/beta/alpha-cohort/error-patterns', { signal }),
  betaAlphaInsight: (signal?: AbortSignal) =>
    request<AlphaCohortInsight>('/api/beta/alpha-cohort/insight', { signal }),
  betaAlphaInsightRegenerate: () =>
    request<AlphaCohortInsight>('/api/beta/alpha-cohort/insight/regenerate', {
      method: 'POST',
      body: {},
      timeoutMs: 240000,
    }),
  betaGammaStatus: (signal?: AbortSignal) =>
    request<GammaStatusResponse>('/api/beta/gamma-status', { signal }),
  ecrs: (includeClosed = false, signal?: AbortSignal) =>
    request<{ ecrs: EcrItem[]; count: number; fields_expected: string[] }>(
      `/api/ecrs?include_closed=${includeClosed}`, { signal },
    ),
  firmwareOverview: (signal?: AbortSignal) =>
    request<FirmwareOverview>('/api/firmware/overview', { signal }),
  firmwareOverviewMetrics: (
    params: { start?: string; end?: string; firmware_version?: string; include_testers?: boolean },
    signal?: AbortSignal,
  ) => {
    const q = new URLSearchParams()
    if (params.start) q.set('start', params.start)
    if (params.end) q.set('end', params.end)
    if (params.firmware_version) q.set('firmware_version', params.firmware_version)
    if (params.include_testers) q.set('include_testers', 'true')
    const qs = q.toString()
    return request<FirmwareOverviewMetrics>(
      `/api/firmware/overview/metrics${qs ? `?${qs}` : ''}`,
      { signal },
    )
  },
  firmwareCookBehaviorBaselines: (firmware_version?: string, signal?: AbortSignal) => {
    const qs = firmware_version ? `?firmware_version=${encodeURIComponent(firmware_version)}` : ''
    return request<CookBehaviorBaselinesResponse>(`/api/firmware/cook-behavior/baselines${qs}`, { signal })
  },
  firmwareCookBehaviorBacktest: (signal?: AbortSignal) =>
    request<CookBehaviorBacktestResponse>('/api/firmware/cook-behavior/backtest', { signal }),
  firmwareCookBehaviorRebuild: () =>
    request<{ backtest: unknown; rebuild: unknown }>('/api/firmware/cook-behavior/rebuild', { method: 'POST', timeoutMs: 120000, retries: 0 }),
  firmwareCookBehaviorTicket: (ticket_id: string, signal?: AbortSignal) =>
    request<CookBehaviorTicketResponse>(`/api/firmware/cook-behavior/ticket/${encodeURIComponent(ticket_id)}`, { signal }),
  firmwareFleetControlHealth: (
    params?: { sort?: string; sort_dir?: 'asc' | 'desc'; state?: string; product?: string; page?: number; per_page?: number },
    signal?: AbortSignal,
  ) => {
    const qs = new URLSearchParams()
    if (params?.sort) qs.set('sort', params.sort)
    if (params?.sort_dir) qs.set('sort_dir', params.sort_dir)
    if (params?.state) qs.set('state', params.state)
    if (params?.product) qs.set('product', params.product)
    if (params?.page != null) qs.set('page', String(params.page))
    if (params?.per_page != null) qs.set('per_page', String(params.per_page))
    const s = qs.toString()
    return request<FirmwareFleetControlHealth>(
      `/api/firmware/fleet/control-health${s ? `?${s}` : ''}`,
      { signal },
    )
  },
  firmwareDeviceControlSignals: (mac: string, signal?: AbortSignal) =>
    request<FirmwareDeviceControlSignals>(
      `/api/firmware/device/${encodeURIComponent(mac)}/control-signals`, { signal },
    ),
  firmwareDeviceCookTimeline: (mac: string, lookbackHours: number = 24, signal?: AbortSignal) =>
    request<CookTimelineResponse>(
      `/api/firmware/device/${encodeURIComponent(mac)}/cook-timeline?lookback_hours=${lookbackHours}`,
      { signal, timeoutMs: 30000 },
    ),
  firmwareDeviceIdResolveMac: (deviceId: string, signal?: AbortSignal) =>
    request<{ device_id: string; mac: string | null }>(
      `/api/firmware/device-id/${encodeURIComponent(deviceId)}/resolve-mac`,
      { signal },
    ),
  firmwareReleaseHistory: (signal?: AbortSignal) =>
    request<{ releases: Array<Record<string, unknown>>; bugs: Array<Record<string, unknown>>; error?: string }>(
      '/api/firmware/release-history', { signal },
    ),
  diagnosticsEvents: (params: { days?: number; event_type?: string; severity?: string; includeResolved?: boolean }, signal?: AbortSignal) => {
    const qs = new URLSearchParams()
    if (params.days != null) qs.set('days', String(params.days))
    if (params.event_type) qs.set('event_type', params.event_type)
    if (params.severity) qs.set('severity', params.severity)
    if (params.includeResolved != null) qs.set('include_resolved', String(params.includeResolved))
    return request<{
      window_days: number; total_in_window: number; total_open: number;
      by_type: Record<string, number>; by_severity: Record<string, number>;
      events: Array<{
        id: number; event_type: string; severity: string;
        mac: string | null; device_id: string | null; user_id: string | null;
        firmware_version: string | null; app_version: string | null; platform: string | null;
        title: string | null; details: Record<string, unknown>;
        created_at: string | null; resolved_at: string | null;
        resolved_by: string | null; resolution_note: string | null;
      }>;
    }>(`/api/diagnostics/events?${qs.toString()}`, { signal })
  },
  diagnosticsResolve: (id: number, note?: string, resolvedBy?: string) =>
    request<{ id: number; resolved_at: string; resolved_by: string | null }>(
      `/api/diagnostics/event/${id}/resolve`,
      { method: 'POST', body: { note, resolved_by: resolvedBy }, retries: 0 },
    ),
  firmwareDeviceLookup: (query: string, signal?: AbortSignal) =>
    request<FirmwareLookupResult>(`/api/firmware/device/lookup?query=${encodeURIComponent(query)}`, { signal }),
  firmwareDeviceSummary: (mac: string, signal?: AbortSignal) =>
    request<FirmwareDeviceSummary>(`/api/firmware/device/${encodeURIComponent(mac)}/summary`, { signal }),
  firmwareDeviceShadow: (mac: string, signal?: AbortSignal) =>
    request<FirmwareDeviceShadow>(`/api/firmware/device/${encodeURIComponent(mac)}/shadow`, { signal }),
  firmwareDeviceActiveCook: (mac: string, signal?: AbortSignal) =>
    request<FirmwareDeviceActiveCook>(`/api/firmware/device/${encodeURIComponent(mac)}/active-cook`, { signal }),
  firmwareDeviceSessions: (mac: string, limit = 20, signal?: AbortSignal) =>
    request<{ mac: string; count: number; sessions: FirmwareSession[] }>(
      `/api/firmware/device/${encodeURIComponent(mac)}/sessions?limit=${limit}`, { signal },
    ),
  firmwareDeviceRecents: (signal?: AbortSignal) =>
    request<{ recents: FirmwareDeviceRecent[] }>('/api/firmware/device/recents', { signal }),
  firmwareDeviceRecentUpsert: (mac: string) =>
    request<FirmwareDeviceRecent>('/api/firmware/device/recents/upsert', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mac }),
    }),
  firmwareDeviceRecentNickname: (mac: string, nickname: string | null) =>
    request<FirmwareDeviceRecent>(`/api/firmware/device/recents/${encodeURIComponent(mac)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nickname }),
    }),
  firmwareDeviceRecentDelete: (mac: string) =>
    request<{ ok: boolean; mac: string }>(`/api/firmware/device/recents/${encodeURIComponent(mac)}`, {
      method: 'DELETE',
    }),
  firmwareDeployPreview: (body: FirmwareDeployPreviewBody) =>
    request<FirmwareDeployPreviewResponse>('/api/firmware/deploy/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  firmwareDeployExecute: (body: FirmwareDeployExecuteBody) =>
    request<FirmwareDeployExecuteResponse>('/api/firmware/deploy/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  firmwareDeployAbort: (aws_job_id: string, reason: string) =>
    request<{ ok: boolean; aws: Record<string, unknown> }>('/api/firmware/deploy/abort', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ aws_job_id, reason }),
    }),
  firmwareDeployStatus: (aws_job_id: string, signal?: AbortSignal) =>
    request<FirmwareDeployStatusResponse>(
      `/api/firmware/deploy/status/${encodeURIComponent(aws_job_id)}`, { signal },
    ),
  firmwareDeployLog: (params: { release_id?: number; aws_job_id?: string; cohort?: string; limit?: number; offset?: number } = {}, signal?: AbortSignal) => {
    const qs = new URLSearchParams()
    if (params.release_id != null) qs.set('release_id', String(params.release_id))
    if (params.aws_job_id) qs.set('aws_job_id', params.aws_job_id)
    if (params.cohort) qs.set('cohort', params.cohort)
    if (params.limit != null) qs.set('limit', String(params.limit))
    if (params.offset != null) qs.set('offset', String(params.offset))
    const q = qs.toString()
    return request<FirmwareDeployLogResponse>(
      `/api/firmware/deploy/log${q ? `?${q}` : ''}`, { signal },
    )
  },
  firmwareReleaseApprove: (release_id: number, body: { cohort: 'alpha' | 'beta' | 'gamma'; approve: boolean; notes?: string }) =>
    request<FirmwareReleaseApprovalResponse>(
      `/api/firmware/deploy/releases/${release_id}/approve`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
    ),
  // ── AI feedback + self-grade ──────────────────────────────────────────
  aiFeedbackPost: (body: { artifact_type: AIFeedbackArtifactType; artifact_id: string; reaction: AIFeedbackReaction; note?: string }) =>
    request<{ ok: boolean; id: number; reaction: AIFeedbackReaction }>(
      '/api/ai/feedback',
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
    ),
  aiFeedbackMine: (artifact_type?: AIFeedbackArtifactType, signal?: AbortSignal) => {
    const qs = artifact_type ? `?artifact_type=${encodeURIComponent(artifact_type)}` : ''
    return request<AIFeedbackMineResponse>(`/api/ai/feedback/mine${qs}`, { signal })
  },
  aiFeedbackSummary: (window_days = 30, signal?: AbortSignal) =>
    request<AIFeedbackSummaryResponse>(`/api/ai/feedback/summary?window_days=${window_days}`, { signal }),
  aiSelfGradeList: (limit = 12, signal?: AbortSignal) =>
    request<{ grades: AISelfGradeRow[] }>(`/api/ai/self-grade?limit=${limit}`, { signal }),
  aiSelfGradeRun: () =>
    request<{ ok: boolean; id?: number; has_prompt_delta?: boolean }>(
      '/api/ai/self-grade/run',
      { method: 'POST' },
    ),
  aiSelfGradeApprove: (grade_id: number) =>
    request<AISelfGradeRow>(
      `/api/ai/self-grade/${grade_id}/approve`,
      { method: 'POST' },
    ),
  aiSelfGradeReject: (grade_id: number) =>
    request<AISelfGradeRow>(
      `/api/ai/self-grade/${grade_id}/reject`,
      { method: 'POST' },
    ),

  // ── Klaviyo (app→dashboard intermediary) ────────────────────────
  klaviyoAppEngagement: (days: number = 30, signal?: AbortSignal) =>
    request<KlaviyoAppEngagement>(`/api/klaviyo/app-engagement?days=${days}`, { signal }),
  klaviyoAppProfileSummary: (signal?: AbortSignal) =>
    request<KlaviyoAppProfileSummary>(`/api/klaviyo/app-profile-summary`, { signal }),
  klaviyoProductOwnership: (signal?: AbortSignal) =>
    request<KlaviyoProductOwnership>(`/api/klaviyo/product-ownership-breakdown`, { signal }),
  klaviyoCustomerLookup: (
    opts: { email?: string; external_id?: string; limit_events?: number },
    signal?: AbortSignal,
  ) => {
    const q = new URLSearchParams()
    if (opts.email) q.set('email', opts.email)
    if (opts.external_id) q.set('external_id', opts.external_id)
    if (opts.limit_events) q.set('limit_events', String(opts.limit_events))
    return request<KlaviyoCustomerLookup>(`/api/klaviyo/customer-lookup?${q.toString()}`, { signal })
  },
  klaviyoSyncStatus: (signal?: AbortSignal) =>
    request<KlaviyoSyncStatus>(`/api/klaviyo/sync-status`, { signal }),
  klaviyoMarketingOverview: (days: number = 30, signal?: AbortSignal) =>
    request<KlaviyoMarketingOverview>(`/api/klaviyo/marketing-overview?days=${days}`, { signal }),
  klaviyoInstallToFirstCook: (signal?: AbortSignal) =>
    request<KlaviyoInstallFunnel>(`/api/klaviyo/install-to-first-cook`, { signal }),
  klaviyoEngagementByOwnership: (signal?: AbortSignal) =>
    request<KlaviyoEngagementByOwnership>(`/api/klaviyo/engagement-by-ownership`, { signal }),
  klaviyoRecentEvents: (limit: number = 50, signal?: AbortSignal) =>
    request<KlaviyoRecentEvents>(`/api/klaviyo/recent-events?limit=${limit}`, { signal }),
  klaviyoCampaignsRecent: (limit: number = 20, signal?: AbortSignal) =>
    request<KlaviyoCampaignsRecent>(`/api/klaviyo/campaigns-recent?limit=${limit}`, { signal }),
  klaviyoFlowsStatus: (signal?: AbortSignal) =>
    request<KlaviyoFlowsStatus>(`/api/klaviyo/flows-status`, { signal }),
  klaviyoListsAndSegments: (signal?: AbortSignal) =>
    request<KlaviyoListsAndSegments>(`/api/klaviyo/lists-and-segments`, { signal }),
  klaviyoAudienceSegmentation: (signal?: AbortSignal) =>
    request<KlaviyoAudienceSegmentation>(`/api/klaviyo/audience-segmentation`, { signal }),
  // SharePoint
  sharepointSites: (signal?: AbortSignal) =>
    request<SharepointSitesResponse>(`/api/sharepoint/sites`, { signal }),
  sharepointRecentChanges: (
    opts: { days?: number; division?: string; spider_product?: string; limit?: number },
    signal?: AbortSignal,
  ) => {
    const q = new URLSearchParams()
    if (opts.days) q.set('days', String(opts.days))
    if (opts.division) q.set('division', opts.division)
    if (opts.spider_product) q.set('spider_product', opts.spider_product)
    if (opts.limit) q.set('limit', String(opts.limit))
    return request<SharepointRecentChanges>(`/api/sharepoint/recent-changes?${q.toString()}`, { signal })
  },
  sharepointByProduct: (signal?: AbortSignal) =>
    request<SharepointByProduct>(`/api/sharepoint/by-product`, { signal }),
  // SharePoint intelligence layer
  sharepointActiveArchive: (
    opts: { division?: string; spider_product?: string },
    signal?: AbortSignal,
  ) => {
    const q = new URLSearchParams()
    if (opts.division) q.set('division', opts.division)
    if (opts.spider_product) q.set('spider_product', opts.spider_product)
    return request<SharepointActiveArchive>(`/api/sharepoint/intelligence/active-archive?${q.toString()}`, { signal })
  },
  sharepointCogs: (
    opts: { spider_product: string; division?: string },
    signal?: AbortSignal,
  ) => {
    const q = new URLSearchParams()
    q.set('spider_product', opts.spider_product)
    if (opts.division) q.set('division', opts.division)
    return request<SharepointCogsResponse>(`/api/sharepoint/intelligence/cogs?${q.toString()}`, { signal })
  },
  sharepointVendors: (spider_product: string | undefined, signal?: AbortSignal) => {
    const q = new URLSearchParams()
    if (spider_product) q.set('spider_product', spider_product)
    return request<SharepointVendorDirectory>(`/api/sharepoint/intelligence/vendors?${q.toString()}`, { signal })
  },
  sharepointRevisions: (spider_product: string, semantic_type: string = 'bom', signal?: AbortSignal) =>
    request<SharepointRevisions>(
      `/api/sharepoint/intelligence/revisions?spider_product=${encodeURIComponent(spider_product)}&semantic_type=${encodeURIComponent(semantic_type)}`,
      { signal },
    ),
  sharepointExtractionStatus: (signal?: AbortSignal) =>
    request<SharepointExtractionStatus>(`/api/sharepoint/extraction-status`, { signal }),
  sharepointCanonicalSources: (data_type: string | undefined, signal?: AbortSignal) => {
    const q = new URLSearchParams()
    if (data_type) q.set('data_type', data_type)
    return request<SharepointCanonicalSourcesResponse>(`/api/sharepoint/canonical-sources?${q.toString()}`, { signal })
  },
  sharepointSetCanonical: (
    payload: { data_type: string; spider_product?: string | null; dashboard_division?: string | null; document_id: number | null; note?: string | null },
    signal?: AbortSignal,
  ) =>
    request<SharepointSetCanonicalResponse>(`/api/sharepoint/canonical-sources`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal,
    }),
  // SharePoint deep analysis (Phase 2)
  sharepointProductNarrative: (spider_product: string, signal?: AbortSignal) =>
    request<SharepointProductNarrative>(
      `/api/sharepoint/intelligence/product-narrative?spider_product=${encodeURIComponent(spider_product)}`,
      { signal },
    ),
  sharepointFileAnalyses: (
    opts: { spider_product?: string; division?: string; semantic_type?: string },
    signal?: AbortSignal,
  ) => {
    const q = new URLSearchParams()
    if (opts.spider_product) q.set('spider_product', opts.spider_product)
    if (opts.division) q.set('division', opts.division)
    if (opts.semantic_type) q.set('semantic_type', opts.semantic_type)
    return request<SharepointFileAnalysesResponse>(
      `/api/sharepoint/intelligence/file-analyses?${q.toString()}`,
      { signal },
    )
  },
  sharepointAnalysisStatus: (signal?: AbortSignal) =>
    request<SharepointAnalysisStatusResponse>(`/api/sharepoint/intelligence/analysis-status`, { signal }),
  // Financials — single source of truth for COGS / gross profit
  financialsCogsTable: (signal?: AbortSignal) =>
    request<FinancialsCogsTable>(`/api/financials/cogs-table`, { signal }),
  financialsGrossProfit: (
    opts: { days?: number; start?: string; end?: string },
    signal?: AbortSignal,
  ) => {
    const q = new URLSearchParams()
    if (opts.days) q.set('days', String(opts.days))
    if (opts.start) q.set('start', opts.start)
    if (opts.end) q.set('end', opts.end)
    const qs = q.toString()
    return request<FinancialsGrossProfit>(`/api/financials/gross-profit${qs ? `?${qs}` : ''}`, { signal })
  },
  // KPI targets — seasonal operator-set targets per metric
  kpiTargetsList: (
    opts: { metric_key?: string; division?: string | null; include_global?: boolean } = {},
    signal?: AbortSignal,
  ) => {
    const q = new URLSearchParams()
    if (opts.metric_key) q.set('metric_key', opts.metric_key)
    if (opts.division != null) q.set('division', opts.division)
    if (opts.include_global != null) q.set('include_global', String(opts.include_global))
    const qs = q.toString()
    return request<{ targets: KpiTargetRow[] }>(`/api/kpi-targets${qs ? `?${qs}` : ''}`, { signal })
  },
  kpiTargetsPermissions: (signal?: AbortSignal) =>
    request<{
      user_email: string | null
      is_platform_owner: boolean
      editable_divisions: Array<{ code: string | null; label: string }>
      division_owners: Array<{ division: string; label: string; owner_email: string }>
    }>(`/api/kpi-targets/permissions`, { signal }),
  kpiTargetsActive: (signal?: AbortSignal) =>
    request<{ active: Record<string, KpiTargetRow> }>(`/api/kpi-targets/active`, { signal }),
  kpiTargetUpsert: (payload: KpiTargetUpsertPayload, signal?: AbortSignal) =>
    request<KpiTargetRow>(`/api/kpi-targets`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal,
    }),
  kpiTargetDelete: (id: number, signal?: AbortSignal) =>
    request<{ ok: boolean; deleted_id: number }>(`/api/kpi-targets/${id}`, { method: 'DELETE', signal }),
  klaviyoBetaCustomers: (limit: number = 500, signal?: AbortSignal) =>
    request<KlaviyoBetaCustomers>(`/api/klaviyo/beta-customers?limit=${limit}`, { signal }),
  // Shipping intelligence
  shippingCarrierMix: (days: number = 90, signal?: AbortSignal) =>
    request<ShippingCarrierMix>(`/api/shipping/carrier-mix?days=${days}`, { signal }),
  shippingGeographic: (days: number = 365, signal?: AbortSignal) =>
    request<ShippingGeographic>(`/api/shipping/geographic-distribution?days=${days}`, { signal }),
  shippingCostTrend: (days: number = 90, bucket: 'week' | 'day' = 'week', signal?: AbortSignal) =>
    request<ShippingCostTrend>(`/api/shipping/cost-trend?days=${days}&bucket=${bucket}`, { signal }),
  shipping3plRoi: (days: number = 365, signal?: AbortSignal) =>
    request<Shipping3plRoi>(`/api/shipping/3pl-roi?days=${days}`, { signal }),
  shippingCxCorrelation: (days: number = 30, signal?: AbortSignal) =>
    request<ShippingCxCorrelation>(`/api/shipping/cx-correlation?days=${days}`, { signal }),
  klaviyoFriendbuyAttribution: (days: number = 30, signal?: AbortSignal) =>
    request<KlaviyoFriendbuyAttribution>(`/api/klaviyo/friendbuy-attribution?days=${days}`, { signal }),
  klaviyoCustomerJourney: (
    opts: { email?: string; external_id?: string; limit?: number },
    signal?: AbortSignal,
  ) => {
    const q = new URLSearchParams()
    if (opts.email) q.set('email', opts.email)
    if (opts.external_id) q.set('external_id', opts.external_id)
    if (opts.limit) q.set('limit', String(opts.limit))
    return request<KlaviyoCustomerJourney>(`/api/klaviyo/customer-journey?${q.toString()}`, { signal })
  },
}

export interface KlaviyoFriendbuyAttribution {
  generated_at: string
  window_days: number
  total_profiles: number
  profiles_with_friendbuy_tag: number
  tag_rate_pct: number
  new_in_window: number
  new_friendbuy_in_window: number
  friendbuy_share_of_new_pct: number
  top_campaigns: Array<{ campaign: string; profiles: number }>
}

export interface KlaviyoCustomerJourney {
  found?: boolean
  email?: string
  external_id?: string
  error?: string
  profile?: {
    klaviyo_id: string
    email: string | null
    external_id: string | null
    first_name: string | null
    last_name: string | null
    device_types: string[]
    device_firmware_versions: string[]
    product_ownership: string | null
    phone_os: string | null
    app_version: string | null
    klaviyo_created_at: string | null
  }
  event_count?: number
  events?: Array<{ metric: string; when: string; properties: Record<string, unknown> }>
  by_month?: Array<{ month: string; counts: Record<string, number> }>
}

export interface KlaviyoBetaCustomers {
  generated_at: string
  list_id: string | null
  error?: string
  total_members?: number
  members: Array<{
    klaviyo_id: string
    email: string | null
    external_id: string | null
    first_name: string | null
    last_name: string | null
    device_types: string[]
    device_firmware_versions: string[]
    product_ownership: string | null
    phone_os: string | null
    app_version: string | null
    last_event_date: string | null
  }>
  firmware_distribution?: Array<{ label: string; count: number; pct: number }>
  device_type_distribution?: Array<{ label: string; count: number; pct: number }>
  phone_os_distribution?: Array<{ label: string; count: number; pct: number }>
}

export interface KlaviyoCampaignsRecent {
  generated_at: string
  missing_scope?: string
  note?: string
  campaigns: Array<{
    id: string
    name: string | null
    status: string | null
    scheduled_at: string | null
    send_time: string | null
    created_at: string | null
    updated_at: string | null
  }>
}

export interface KlaviyoFlowsStatus {
  generated_at: string
  missing_scope?: string
  note?: string
  by_status: Record<string, number>
  flows: Array<{
    id: string
    name: string | null
    status: string | null
    trigger_type: string | null
    created: string | null
    updated: string | null
  }>
}

export interface KlaviyoListsAndSegments {
  generated_at: string
  lists: Array<{
    id: string
    name: string | null
    opt_in_process: string | null
    member_count: number | null
    created: string | null
    updated: string | null
  }>
  segments: Array<{
    id: string
    name: string | null
    is_active: boolean | null
    is_processing: boolean | null
    member_count: number | null
    created: string | null
    updated: string | null
  }>
}

export interface KlaviyoInstallFunnel {
  generated_at: string
  installed: number
  converted_to_first_cook: number
  conversion_pct: number
  median_days_to_first_cook: number | null
  histogram: Array<{ bucket: string; count: number }>
}

export interface KlaviyoEngagementByOwnership {
  generated_at: string
  by_ownership: Array<{
    ownership: string
    profiles: number
    dau: number
    mau: number
    stickiness_pct: number
  }>
}

export interface KlaviyoRecentEvents {
  generated_at: string
  events: Array<{
    event_id: string
    metric: string
    when: string | null
    email: string | null
    external_id: string | null
    product_ownership: string | null
    device_types: string[]
    phone_os: string | null
  }>
}

export interface KlaviyoMarketingOverview {
  generated_at: string
  window_days: number
  total_profiles: number
  app_profiles: number
  app_install_rate_pct: number
  signups: Array<{ date: string; count: number }>
  first_cooks: Array<{ date: string; events: number; unique_profiles: number }>
  orders: Array<{ date: string; events: number; unique_profiles: number }>
  product_ownership: Array<{ ownership: string; count: number; pct: number }>
}

export interface KlaviyoAppEngagement {
  generated_at: string
  window_days: number
  dau: number
  mau: number
  stickiness_pct: number
  latest_event_at: string | null
  daily_unique_openers: Array<{ date: string; unique_profiles: number; events: number }>
}

export interface KlaviyoAppProfileSummary {
  generated_at: string
  app_profiles: number
  active_30d: number
  phone_os: Array<{ label: string; count: number; pct: number }>
  phone_brand: Array<{ label: string; count: number; pct: number }>
  app_version: Array<{ label: string; count: number; pct: number }>
  device_types: Array<{ label: string; count: number; pct: number }>
}

export interface KlaviyoProductOwnership {
  generated_at: string
  tagged_ownership: {
    total_profiles: number
    breakdown: Array<{ ownership: string; count: number; pct: number }>
  }
  from_orders: Array<{ family: string; unique_profiles: number }>
}

export interface KlaviyoCustomerLookup {
  found: boolean
  email?: string
  external_id?: string
  profile?: {
    klaviyo_id: string
    external_id: string | null
    email: string | null
    first_name: string | null
    last_name: string | null
    device_types: string[]
    device_firmware_versions: string[]
    product_ownership: string | null
    phone_os: string | null
    phone_model: string | null
    phone_os_version: string | null
    phone_brand: string | null
    app_version: string | null
    expected_next_order_date: string | null
    klaviyo_created_at: string | null
    klaviyo_updated_at: string | null
    last_event_at: string | null
  }
  recent_events?: Array<{
    metric: string
    when: string
    properties: Record<string, unknown>
  }>
}

export interface KlaviyoAudienceSegmentation {
  generated_at: string
  total_audience: number
  owners: {
    by_order: number
    by_klaviyo_tag: number
    by_device_types: number
    total: number
    pct_of_audience: number
  }
  app_users: {
    lifetime: number
    active_30d: number
    pct_of_owners: number
    pct_of_audience: number
  }
  connected_devices: { lifetime: number; last_24mo: number }
  device_to_app_user_ratio: number | null
  non_owner_audience: number
  non_owner_pct: number
}

export interface SharepointSitesResponse {
  generated_at: string
  sites: Array<{
    tenant_id: string
    tenant_display_name: string | null
    site_path: string
    display_name: string | null
    spider_product: string | null
    default_division: string | null
    web_url: string | null
    enabled: boolean
    last_synced_at: string | null
    last_sync_error: string | null
  }>
}

export interface SharepointRecentChanges {
  generated_at: string
  window_days: number
  filters: { division: string | null; spider_product: string | null }
  documents: Array<{
    name: string
    path: string
    spider_product: string | null
    dashboard_division: string | null
    top_level_folder: string | null
    modified_at: string | null
    modified_by_email: string | null
    size_bytes: number | null
    mime_type: string | null
    web_url: string | null
  }>
  list_items: Array<{
    title: string | null
    list_name: string | null
    spider_product: string | null
    dashboard_division: string | null
    modified_at: string | null
    modified_by_email: string | null
    web_url: string | null
    fields_preview: Record<string, unknown>
  }>
}

export interface SharepointByProduct {
  generated_at: string
  by_product: Array<{
    spider_product: string | null
    docs: number
    list_items: number
    last_modified: string | null
  }>
}

// SharePoint intelligence layer

export interface SharepointDocSummary {
  id: number
  name: string
  path: string
  web_url: string | null
  spider_product: string | null
  dashboard_division: string | null
  top_level_folder: string | null
  modified_at: string | null
  modified_by_email: string | null
  semantic_type: string | null
  archive_status: string | null
  sku_code: string | null
  revision_letter: string | null
  doc_date: string | null
  assembly_name: string | null
}

export interface SharepointActiveArchive {
  generated_at: string
  filters: { division: string | null; spider_product: string | null }
  by_status: Record<string, number>
  by_semantic_type: Array<{ semantic_type: string; active: number; archived: number; total: number }>
}

export interface SharepointBomLineOut {
  line_no: number | null
  part_number: string | null
  description: string | null
  vendor_name: string | null
  qty: number | null
  unit: string | null
  unit_cost_usd: number | null
  total_cost_usd: number | null
  currency_raw: string | null
}

export interface SharepointCogsResponse {
  generated_at: string
  spider_product: string
  dashboard_division: string | null
  source_file: SharepointDocSummary | null
  source_pin_state: {
    auto_chosen: boolean
    override_user: string | null
    override_at: string | null
    override_note: string | null
  }
  rollup: {
    total_cost_usd: number
    line_count: number
    vendor_count: number
    vendors: Array<{ vendor: string; cost: number; lines: number }>
  }
  lines: SharepointBomLineOut[]
}

export interface SharepointVendorDirectory {
  generated_at: string
  spider_product: string | null
  vendors: Array<{ vendor: string; line_count: number; doc_count: number; total_cost_usd: number }>
}

export interface SharepointRevisions {
  generated_at: string
  spider_product: string
  semantic_type: string
  by_assembly: Array<{ assembly_name: string; revisions: SharepointDocSummary[] }>
}

export interface SharepointExtractionStatus {
  generated_at: string
  active_bom_docs: number
  extracted_successfully: number
  extraction_failures: number
  bom_lines_total: number
  last_extraction_at: string | null
}

export interface SharepointCanonicalSourceRow {
  id: number
  data_type: string
  spider_product: string | null
  dashboard_division: string | null
  auto_chosen: boolean
  override_user: string | null
  override_at: string | null
  override_note: string | null
  source_file: SharepointDocSummary | null
}

export interface SharepointCanonicalSourcesResponse {
  generated_at: string
  supported_data_types: string[]
  rows: SharepointCanonicalSourceRow[]
}

export interface SharepointSetCanonicalResponse {
  status: string
  scope: { data_type: string; spider_product: string | null; dashboard_division: string | null }
  auto_chosen: boolean
  override_user: string | null
  override_at: string | null
  source_file: SharepointDocSummary | null
}

export interface SharepointHeadlineMetric {
  label: string
  value: string
  unit: string | null
  tone: 'good' | 'warn' | 'bad' | 'neutral' | string
  source_document_id: number | null
}

export interface SharepointCogsBreakdownItem {
  category: string
  cost_usd: number
  source_document_id: number | null
  notes: string | null
}

export interface SharepointTimelineEvent {
  date: string
  label: string
  document_id: number | null
  kind: string
}

export interface SharepointProductNarrative {
  generated_at: string
  spider_product: string
  available: boolean
  reason?: string
  narrative_md?: string
  headline_metrics?: SharepointHeadlineMetric[]
  timeline?: SharepointTimelineEvent[]
  cogs_summary?: {
    canonical_total_usd: number | null
    canonical_line_count: number | null
    canonical_document_id: number | null
    confidence: string
    notes: string | null
    breakdown?: SharepointCogsBreakdownItem[]
    coated_total_usd?: number | null
    uncoated_total_usd?: number | null
    currency_notes?: string | null
  }
  design_status?: {
    latest_revision: string | null
    latest_revision_document_id: number | null
    active_workstreams: string[]
    notable_iterations: string[]
  }
  vendor_summary?: {
    top_vendors: Array<{ name: string; mentions: number; documents_seen: number; role: string | null; estimated_spend_usd?: number | null }>
    total_unique: number
  }
  data_quality_issues?: Array<{
    severity: string
    issue: string
    affected_document_ids: number[]
    suggested_fix: string | null
  }>
  citations?: Array<{ claim: string; document_id: number }>
  citation_docs?: Record<string, SharepointDocSummary>
  files_analyzed?: number
  model_used?: string
  synthesized_at?: string | null
}

export interface SharepointFileAnalysisRow {
  document: SharepointDocSummary
  purpose: string | null
  key_facts: Array<{
    kind: string
    summary: string
    detail: string | null
    source_location: string | null
  }>
  related_part_numbers: string[]
  related_vendors: string[]
  cost_data: {
    total_cost_usd: number | null
    line_count: number | null
    currency_observed: string | null
    cost_completeness: string
    notes: string | null
  }
  design_data: {
    revision_label: string | null
    assemblies_named: string[]
    materials_named: string[]
    dimensions_summary: string | null
  }
  decisions: string[]
  data_quality_flags: string[]
  analyzed_at: string | null
}

export interface SharepointFileAnalysesResponse {
  generated_at: string
  filters: { spider_product: string | null; division: string | null; semantic_type: string | null }
  files: SharepointFileAnalysisRow[]
}

export interface ShippingWindow { start: string | null; end: string; days: number | null }

export interface ShippingCarrierMix {
  window: ShippingWindow
  totals: { shipments: number; total_cost_usd: number; avg_cost_per_shipment: number }
  carriers: Array<{ carrier: string; shipments: number; total_cost_usd: number; avg_cost_usd: number; avg_weight_oz: number; share_pct: number }>
}

export interface ShippingGeographic {
  window: ShippingWindow
  totals: { domestic_shipments: number; international_shipments: number; states_seen: number }
  by_state: Array<{ state: string; country: string; shipments: number; total_cost_usd: number; avg_cost_usd: number }>
}

export interface ShippingCostTrend {
  window: ShippingWindow & { bucket: string }
  series: Array<{ bucket: string; shipments: number; cost_usd: number; avg_cost_usd: number }>
}

export interface Shipping3plRoi {
  window: ShippingWindow
  current_warehouse: { city: string; state: string; lat: number; lon: number }
  totals: { shipments_in_window: number; actual_cost_usd: number }
  candidates: Array<{
    name: string; state: string; estimated_annual_savings_usd: number; in_window_savings_usd: number
    shipments_better_served: number; savings_pct: number
  }>
  method_note: string
}

export interface ShippingCxCorrelation {
  window: ShippingWindow
  totals: {
    tickets_in_window: number
    wismo_tickets: number
    wismo_ratio_pct: number
    wismo_matched_to_shipment: number
    wismo_unshipped_at_ticket_time: number
    median_ship_to_wismo_hours: number | null
    late_tracking_signal_count: number
  }
  by_carrier: Array<{ carrier: string; wismo_tickets: number }>
  wismo_tickets: Array<{
    ticket_id: string; subject: string; created_at: string | null; resolved_at: string | null
    first_response_hours: number | null; resolution_hours: number | null
    extracted_order_number: string | null
    matched_shipment: { ship_date: string | null; carrier: string | null; tracking_number: string | null; shipment_cost: number } | null
    shipped: boolean
  }>
}

export interface KpiTargetRow {
  id: number
  metric_key: string
  target_value: number
  direction: 'min' | 'max' | string
  effective_start: string | null
  effective_end: string | null
  season_label: string | null
  notes: string | null
  division: string | null
  owner_email: string | null
  created_by: string | null
  created_at: string | null
  updated_at: string | null
}

export interface KpiTargetUpsertPayload {
  id?: number | null
  metric_key: string
  target_value: number
  direction: 'min' | 'max'
  effective_start?: string | null
  effective_end?: string | null
  season_label?: string | null
  notes?: string | null
  division?: string | null
}

export interface FinancialsCogsTableRow {
  product: string
  cogs_usd: number
  confidence: string
  source_doc_id: number | null
  source_doc_name: string | null
  source_web_url: string | null
  notes: string | null
  synthesized_at: string | null
}

export interface FinancialsCogsTable {
  products: FinancialsCogsTableRow[]
}

export interface FinancialsGrossProfit {
  generated_at: string
  window: { start: string | null; end: string | null; days: number | null }
  totals: {
    revenue_usd: number
    revenue_classified_usd: number
    revenue_unclassified_usd: number
    units_sold: number
    applied_cogs_usd: number
    applied_cogs_classified_usd?: number
    applied_cogs_accessory_estimate_usd?: number
    applied_shipping_usd?: number
    gross_profit_usd: number
    gross_margin_pct: number | null
    discounts_applied_usd?: number
    ad_spend_usd?: number
    contribution_margin_usd?: number
    contribution_margin_pct?: number | null
    refunds_in_kpi_daily_usd?: number
  }
  accessory_assumption?: { ratio: number; note: string }
  shipping?: {
    total_cost_usd: number
    shipment_count: number
    voided_count: number
    by_store: Record<string, number>
    note: string
  }
  excluded?: { cancelled_orders: number; refunded_orders: number; refunded_revenue_usd: number; partially_refunded_orders: number }
  by_product: Array<{
    product: string
    units_sold: number
    revenue_usd: number
    unit_cogs_usd: number | null
    applied_cogs_usd: number
    applied_shipping_usd?: number
    gross_profit_usd: number
    gross_margin_pct: number | null
    cogs_confidence: string | null
    cogs_source_doc_id: number | null
    cogs_source_doc_name: string | null
    cogs_source_web_url: string | null
  }>
  data_quality_flags: Array<{ severity: string; product: string; issue: string }>
  coverage: { orders_with_line_items: number; orders_total: number; note: string }
}

export interface SharepointAnalysisStatusResponse {
  generated_at: string
  files_with_content: number
  files_with_analysis: number
  products_with_synthesis: number
  last_content_extracted_at: string | null
  last_analysis_at: string | null
  last_synthesis_at: string | null
}

export interface KlaviyoSyncStatus {
  generated_at: string
  profiles_total: number
  events_total: number
  events_by_metric: Record<string, number>
  latest_profile_updated_at: string | null
  latest_event_at: string | null
  profile_lag_minutes: number | null
  event_lag_minutes: number | null
}

export type AIFeedbackArtifactType = 'ai_insight' | 'deci_draft' | 'issue_signal' | 'firmware_verdict'
export type AIFeedbackReaction = 'acted_on' | 'already_knew' | 'wrong' | 'ignore'

export interface AIFeedbackMineRow {
  artifact_type: AIFeedbackArtifactType
  artifact_id: string
  reaction: AIFeedbackReaction
  note: string | null
  updated_at: string | null
}
export interface AIFeedbackMineResponse {
  reactions: AIFeedbackMineRow[]
}
export interface AIFeedbackSummaryResponse {
  window_days: number
  by_type: Record<string, {
    counts: Record<string, number>
    total: number
    precision_score: number
  }>
}
export interface AISelfGradeRow {
  id: number
  run_at: string | null
  window_days: number
  model: string
  artifacts_scored: number
  feedback_count: number
  precision_by_source: Record<string, {
    grade: string
    precision_note: string
    specific_wins: string[]
    specific_misses: string[]
  }> | null
  rejection_themes: Array<{ theme: string; frequency: number; example: string }> | null
  overall_summary: string | null
  prompt_delta: string | null
  approved_at: string | null
  approved_by: string | null
  applied_at: string | null
  duration_ms: number | null
}

export interface FirmwareStreamEvent {
  sample_timestamp: string | null
  stream_event_name: string | null
  engaged: boolean
  firmware_version: string | null
  grill_type: string | null
  target_temp: number | null
  current_temp: number | null
  heating: boolean | null
  intensity: number | null
  rssi: number | null
  error_codes: (string | number)[]
}

export interface FirmwareAppSideSummary {
  count: number
  latest_observed_at?: string | null
  self_reported_firmware_version?: string | null
  controller_model?: string | null
  app_version?: string | null
  phone_os?: string | null
  phone_os_version?: string | null
  phone_brand?: string | null
  phone_model?: string | null
  user_keys?: string[]
  sources?: string[]
}

export interface FirmwareCohortRef {
  release_id: number
  release_version: string
  release_title: string | null
  state: string
  invited_at: string | null
  opted_in_at: string | null
  ota_pushed_at: string | null
  verdict: string | null
}

export interface FirmwareSession {
  source_event_id: string
  session_id: string | null
  grill_type: string | null
  firmware_version: string | null
  target_temp: number | null
  session_start: string | null
  session_end: string | null
  session_duration_seconds: number | null
  disconnect_events: number
  manual_overrides: number
  error_count: number
  error_codes: unknown
  temp_stability_score: number
  time_to_stabilization_seconds: number | null
  firmware_health_score: number
  session_reliability_score: number
  cook_success: boolean
  cook_intent: string | null
  cook_outcome: string | null
  held_target: boolean | null
  in_control_pct: number | null
  max_overshoot_f: number | null
  max_undershoot_f: number | null
}

export interface FirmwareDeviceSummary {
  mac: string
  latest_stream_event: FirmwareStreamEvent | null
  session_count: number
  app_side: FirmwareAppSideSummary
  cohorts: FirmwareCohortRef[]
}

export interface FirmwareDeviceShadow {
  mac: string
  event: FirmwareStreamEvent | null
  age_seconds: number | null
  fetched_at: string
}

export interface FirmwareDeviceActiveCook {
  mac: string
  active: boolean
  trail: FirmwareStreamEvent[]
  latest_event: FirmwareStreamEvent | null
  last_completed_session: FirmwareSession | null
}

export interface FirmwareLookupDevice {
  mac: string
  latest_stream_event: FirmwareStreamEvent | null
  session_count: number
  app_side: FirmwareAppSideSummary
}

export interface FirmwareLookupResult {
  query: string
  resolved_as: 'mac' | 'user_key'
  devices: FirmwareLookupDevice[]
}

export interface AlphaCohortMember {
  device_id: string
  user_id: string | null
  state: string
  candidate_score: number | null
  invited_at: string | null
  opted_in_at: string | null
  ota_pushed_at: string | null
  evaluated_at: string | null
  release_id: number
  release_version: string
  release_title: string | null
  release_status: string | null
}

export interface AlphaCohortResponse {
  members: AlphaCohortMember[]
  count: number
  state_distribution: Record<string, number>
}

export interface AlphaBulkImportResult {
  dry_run: boolean
  total_requested: number
  successful: number
  by_firmware_version: Record<string, number>
  releases_created: string[]
  invalid_macs: string[]
  unknown_firmware: string[]
  app_side_only: string[]
  already_registered: number
  results: Array<{
    input_mac: string
    mac?: string
    device_id_count?: number
    firmware_version?: string
    firmware_source?: 'stream' | 'app_side' | 'override'
    release_id?: number
    first_seen_on_version?: string | null
    status: 'registered' | 'would_register' | 'invalid_mac' | 'unknown_firmware' | 'no_telemetry'
    cohort_rows_inserted?: number
    note?: string
    user_id?: string | null
  }>
}

export interface AlphaFirmwareVersionRow {
  firmware_version: string
  stream_first_seen: string | null
  stream_last_seen: string | null
  stream_active_days: number
  stream_sample_count: number
  session_count: number
  first_session_at: string | null
  last_session_at: string | null
}

export interface AlphaFirmwareTimeline {
  mac: string
  device_id_count: number
  versions: AlphaFirmwareVersionRow[]
}

export interface AlphaCohortAnalyticsSegment {
  firmware_version: string
  cohort: 'alpha' | 'production'
  sessions: number
  devices: number
  cook_success_rate: number | null
  avg_disconnects_per_session: number | null
  avg_max_overshoot_f: number | null
  avg_in_control_pct: number | null
  avg_stability_score: number | null
  avg_time_to_stabilize_seconds: number | null
}

export interface AlphaCohortAnalytics {
  window_days: number
  alpha_device_id_count: number
  segments: AlphaCohortAnalyticsSegment[]
}

export interface AlphaCohortTrendPoint {
  firmware_version: string
  sessions: number
  devices: number
  cook_success_rate: number | null
  avg_disconnects_per_session: number | null
  avg_error_events_per_session: number | null
  avg_max_overshoot_f: number | null
  avg_in_control_pct: number | null
  avg_stability_score: number | null
  avg_time_to_stabilize_seconds: number | null
  small_sample: boolean
}

export interface AlphaCohortTrend {
  window_days: number
  alpha_device_id_count: number
  points: AlphaCohortTrendPoint[]
  production_baseline: AlphaCohortTrendPoint & { versions: string[] }
}

export interface AlphaErrorPatternVersion {
  firmware_version: string
  sessions: number
  error_free_sessions_pct: number | null
  top_error_codes: Array<{
    code: string
    occurrences: number
    incidence_pct: number | null
  }>
}

export interface AlphaCohortErrorPatterns {
  versions: AlphaErrorPatternVersion[]
  window_days: number
}

export interface AlphaInsightObservation {
  title: string
  detail: string
  recommendation: string
  severity: 'improving' | 'regressing' | 'investigate' | 'info'
  firmware_versions_cited: string[]
}

export interface OrderAgingBucket {
  label: string
  low_days: number
  high_days: number | null
  count: number
  oldest_order_days: number
  total_value_usd: number
}

export interface OrderAgingOldestOrder {
  order_id: string
  age_days: number
  bucket: string
  fulfillment_status: string
  total_value_usd: number
  created_at: string | null
  tags: string[]
}

export interface OrderAgingTrendSeries {
  label: string
  counts: number[]
}

export interface CharcoalDeviceSessionsResponse {
  mac: string
  device_id_count: number
  window_days?: number
  sessions: Array<{
    session_id: string | null
    source_event_id: string
    device_id: string | null
    session_start: string | null
    session_end: string | null
    duration_hours: number
    target_temp_f: number | null
    avg_actual_temp_f: number | null
    grill_type: string | null
    firmware_version: string | null
    cook_success: boolean
    product_family: string
  }>
  note?: string
}

export interface CharcoalFleetAggregateResponse {
  window: { start: string; end: string; days: number }
  filters: {
    grill_type: string | null
    firmware_version: string | null
    product_family: string | null
  }
  fleet_totals: {
    unique_devices: number
    total_sessions: number
    total_cook_hours: number
  }
  by_family: Array<{ product_family: string; devices: number; sessions: number; cook_hours: number }>
  per_device: Array<{
    device_id: string
    sessions: number
    cook_hours: number
    avg_target_temp_f: number | null
    avg_cook_temp_f: number | null
    grill_type: string | null
    firmware_version: string | null
    product_family: string
    first_session_at: string | null
    last_session_at: string | null
  }>
}

export interface CharcoalPartnerProduct {
  id: number
  partner: string
  handle: string
  title: string
  fuel_type: 'lump' | 'briquette' | 'other' | null
  // Narrower modeling bucket. 'lump_charcoal' | 'briquette' | 'other'.
  // Older rows may carry null until the next scraper pass fills them.
  category: 'lump_charcoal' | 'briquette' | 'other' | null
  bag_size_lb: number | null
  retail_price_usd: number
  currency: string
  source_url: string | null
  available: boolean
  last_fetched_at: string | null
}

export interface CharcoalCohortModelInput {
  product_families?: string[] | null
  min_cooks_in_window?: number
  lookback_days?: number
  /** 0 = target everyone (addressable). 75 = target top 25% by monthly burn. */
  target_percentile_floor?: number
  signup_pct?: number
  partner_product_id: number
  margin_pct?: number
  monthly_churn_pct?: number
  horizon_months?: number
}

export interface CharcoalCohortMonthlyCurveRow {
  month: number
  surviving_subscribers: number
  lb: number
  bags: number
  gmv_usd: number
  sg_margin_usd: number
  jd_payout_usd: number
  cumulative_gmv_usd: number
  cumulative_sg_margin_usd: number
  cumulative_jd_payout_usd: number
}

export interface CharcoalCohortModelResponse {
  ok: boolean
  computed_at: string
  inputs: {
    product_families: string[] | null
    min_cooks_in_window: number
    lookback_days: number
    target_percentile_floor: number
    signup_pct: number
    partner_product_id: number
    margin_pct: number
    monthly_churn_pct: number
    horizon_months: number
  }
  sku: {
    id: number
    partner: string
    title: string
    fuel_type: string
    category: string | null
    bag_size_lb: number
    retail_price_usd: number
    available: boolean
  }
  cohort: {
    eligible_devices: number
    mean_lb_per_month_per_device: number
    median_lb_per_month_per_device: number
    p25_lb_per_month_per_device: number
    p75_lb_per_month_per_device: number
    p90_lb_per_month_per_device: number
    families_breakdown: Record<string, number>
    lookback_days: number
  }
  targeted: {
    percentile_floor: number
    threshold_lb_per_month: number
    targeted_devices: number
    addressable_devices: number
    targeted_share_of_addressable_pct: number
    mean_lb_per_month_per_device: number
    median_lb_per_month_per_device: number
    p25_lb_per_month_per_device: number
    p75_lb_per_month_per_device: number
    p90_lb_per_month_per_device: number
    families_breakdown: Record<string, number>
    lift_over_addressable_mean: number
  }
  projected_initial_signups: number
  per_subscriber_monthly: {
    lb: number
    bags: number
    gmv_usd: number
    sg_margin_usd: number
    jd_payout_usd: number
  }
  month_1: {
    subscribers: number
    lb: number
    bags: number
    gmv_usd: number
    sg_margin_usd: number
    jd_payout_usd: number
  }
  horizon_totals: {
    months: number
    lb: number
    bags: number
    gmv_usd: number
    sg_margin_usd: number
    jd_payout_usd: number
    ltv_per_initial_subscriber_usd: number
  }
  monthly_curve: CharcoalCohortMonthlyCurveRow[]
  assumptions: Record<string, string | number>
}

export interface CharcoalPartnerProductsResponse {
  products: CharcoalPartnerProduct[]
  count: number
}

export interface CharcoalJITFinancial {
  partner: string
  partner_product_title: string
  bag_size_lb: number
  retail_price_usd: number
  margin_pct: number
  per_ship_revenue_usd: number
  per_ship_margin_usd: number
  per_ship_partner_payout_usd: number
  shipments_per_year: number
  annual_revenue_usd: number
  annual_margin_usd: number
  annual_partner_payout_usd: number
}

export interface CharcoalJITSubscription {
  id: number
  device_id: string | null
  mac: string | null
  user_key: string | null
  fuel_preference: 'lump' | 'briquette'
  bag_size_lb: number
  lead_time_days: number
  safety_stock_days: number
  shipping_zip: string | null
  shipping_lat: number | null
  shipping_lon: number | null
  status: 'active' | 'paused' | 'cancelled'
  enrolled_by: string | null
  notes: string | null
  partner_product_id: number | null
  margin_pct: number
  last_forecast: Record<string, unknown>
  last_shipped_at: string | null
  next_ship_after: string | null
  created_at: string | null
  updated_at: string | null
}

export interface CharcoalJITListResponse {
  subscriptions: CharcoalJITSubscription[]
  count: number
  by_status: Record<string, number>
  by_fuel: Record<string, number>
}

// ── Beta rollout: invitation engine ─────────────────────────────────

export type CharcoalJITInvitationStatus =
  'pending' | 'accepted' | 'declined' | 'expired' | 'revoked'

export interface CharcoalJITInvitation {
  id: number
  batch_id: string
  invitation_token: string
  device_id: string | null
  mac_normalized: string | null
  user_key: string | null
  partner_product_id: number | null
  bag_size_lb: number
  fuel_preference: 'lump' | 'briquette'
  margin_pct: number
  addressable_lb_per_month: number | null
  percentile_at_invite: number | null
  sessions_in_window_at_invite: number | null
  product_family_at_invite: string | null
  cohort_params: Record<string, unknown>
  status: CharcoalJITInvitationStatus
  invited_at: string | null
  expires_at: string | null
  accepted_at: string | null
  declined_at: string | null
  revoked_at: string | null
  invited_by: string | null
  notes: string | null
  subscription_id: number | null
}

export interface CharcoalJITInvitationCandidate {
  device_id: string | null
  mac_normalized: string | null
  product_family: string
  sessions_in_window: number
  lb_per_month: number
  percentile_at_invite: number
}

export interface CharcoalJITInvitationSummary {
  addressable_devices: number
  threshold_lb_per_month: number
  percentile_floor: number
  mean_lb_per_month: number
  reserved_excluded: number
  ranked_after_filters: number
  max_invitations: number
  selected: number
  product_families_filter: string[] | null
  min_cooks_in_window: number
  lookback_days: number
  sku: {
    id: number
    partner: string
    title: string
    fuel_type: string
    bag_size_lb: number
    retail_price_usd: number
  }
  expires_at?: string
  expiry_days?: number
}

export interface CharcoalJITInvitationSelectionInput {
  partner_product_id: number
  product_families?: string[] | null
  min_cooks_in_window?: number
  lookback_days?: number
  target_percentile_floor?: number
  max_invitations?: number
  margin_pct?: number
}

export interface CharcoalJITInvitationBatchInput extends CharcoalJITInvitationSelectionInput {
  expiry_days?: number
  invited_by?: string | null
  notes?: string | null
  /** Must equal 'SEND' on the backend — client-typed confirmation. */
  confirm: 'SEND'
}

export interface CharcoalJITInvitationPreviewResponse {
  ok: true
  preview: true
  computed_at: string
  summary: CharcoalJITInvitationSummary
  candidates: CharcoalJITInvitationCandidate[]
}

export interface CharcoalJITInvitationBatchResponse {
  ok: boolean
  preview: false
  batch_id?: string
  computed_at?: string
  summary?: CharcoalJITInvitationSummary
  invitations?: CharcoalJITInvitation[]
  candidates?: CharcoalJITInvitationCandidate[]
  error?: string
}

export interface CharcoalJITInvitationBatchSummary {
  batch_id: string
  first_invite_at: string | null
  last_invite_at: string | null
  expires_at: string | null
  invited_by: string | null
  counts: {
    pending: number
    accepted: number
    declined: number
    expired: number
    revoked: number
    total: number
  }
  acceptance_pct: number
}

export interface CharcoalJITInvitationBatchListResponse {
  batches: CharcoalJITInvitationBatchSummary[]
  count: number
}

export interface CharcoalJITInvitationBatchDetailResponse {
  ok: boolean
  batch_id: string
  invited_by: string | null
  cohort_params: Record<string, unknown>
  counts: {
    pending: number
    accepted: number
    declined: number
    expired: number
    revoked: number
    total: number
  }
  invitations: CharcoalJITInvitation[]
}

export interface CharcoalFleetFilters {
  grill_types: Array<{ value: string; devices: number }>
  firmware_versions: Array<{ value: string; devices: number }>
  product_families: string[]
}

export interface FleetFamilyBreakdown {
  'Kettle': number
  'Huntsman': number
  'Giant Huntsman': number
  'Unknown': number
}

export interface FleetSizeResponse {
  generated_at: string
  window_days: number
  active_24mo: {
    total: number
    by_family: FleetFamilyBreakdown
  }
  /** Devices enrolled in firmware alpha/beta testing — excluded from
   * `active_24mo` so experimental builds don't skew Fleet Health.
   * Surfaced separately for the Firmware Hub. */
  test_cohort?: {
    total: number
    by_family: FleetFamilyBreakdown
    note: string
  }
  /** Active fleet count including testers. Use only when the caller
   * explicitly wants "everyone, including alpha/beta" (Firmware Hub
   * reconciliation views). Default displays read active_24mo.total. */
  active_24mo_including_testers?: {
    total: number
  }
  definition: string
}

export interface FleetLifetimeResponse {
  generated_at: string
  aws_registered: {
    total: number
    by_family: FleetFamilyBreakdown
    note: string
  }
  shopify_units: {
    total: number
    by_family: FleetFamilyBreakdown
    coverage_orders_with_line_items: number
    coverage_orders_total: number
    note: string
  }
  amazon_units: {
    total: number | null
    by_family: FleetFamilyBreakdown | null
    note: string
  }
}

export interface OrderAgingResponse {
  current: {
    generated_at: string
    newest_snapshot_at: string | null
    total_unfulfilled: number
    total_unfulfilled_value_usd: number
    buckets: OrderAgingBucket[]
    oldest_orders: OrderAgingOldestOrder[]
  }
  trend: {
    days: string[]
    series: OrderAgingTrendSeries[]
  }
  meta: {
    method: string
    snapshot_rows_scanned: number
    notes: string
  }
}

export interface AlphaCohortInsight {
  generated_at: string | null
  model?: string
  overall_theme: string | null
  observations: AlphaInsightObservation[]
  cached?: boolean
  duration_ms?: number
}

export interface GammaWave {
  wave_index: number
  target_pct: number | null
  target_devices: number | null
  scheduled_at: string | null
  started_at: string | null
  completed_at: string | null
  aws_job_id: string | null
  status: string
}

export interface GammaReleaseStatus {
  release_id: number
  version: string
  title: string | null
  status: string | null
  approved_for_gamma: boolean
  approved_at: string | null
  released_at: string | null
  target_controller_model: string | null
  waves: GammaWave[]
  total_planned: number
  aws_job_id_count: number
}

export interface GammaStatusResponse {
  releases: GammaReleaseStatus[]
  count: number
}

export interface FirmwareControlProbe {
  probe: string
  current_temp: number | null
  target_temp: number | null
}

export interface FirmwareControlSignals {
  target_temp: number | null
  current_temp: number | null
  gap_f: number | null
  intensity: number | null
  heating: boolean | null
  engaged: boolean | null
  paused: boolean | null
  door_open: boolean | null
  power_on: boolean | null
  fahrenheit: boolean | null
  rssi: number | null
  firmware_version: string | null
  model: string | null
  errors: number[]
  probes: FirmwareControlProbe[]
}

export interface FirmwareDeviceControlSignals {
  mac: string
  event_at: string | null
  firmware_version?: string | null
  signals: FirmwareControlSignals | null
}

export type CookState =
  | 'ramping_up'
  | 'in_control'
  | 'out_of_control'
  | 'cooling_down'
  | 'manual_mode'
  | 'error'
  | 'idle'
  | 'unknown'

export interface FirmwareFleetControlDevice {
  mac: string | null
  device_id: string
  state: CookState
  state_label: string
  confidence: number
  reason: string
  target_temp: number | null
  current_temp: number | null
  gap_f: number | null
  intensity: number | null
  engaged: boolean | null
  door_open: boolean | null
  paused: boolean | null
  error_count: number
  ramp_elapsed_seconds: number | null
  ramp_budget_seconds: number | null
  expected_gap_f: number | null
  is_anomalous: boolean
  firmware_version: string | null
  grill_type: string | null
  product: string | null
  sample_timestamp: string | null
  cook_start_ts: string | null
  cook_elapsed_seconds: number | null
  target_set_at: string | null
}

export interface FirmwareFleetControlHealth {
  window_seconds: number
  total_reporting_devices: number
  active_cooks: number
  tallies: Partial<Record<CookState, number>>
  product_tallies: Record<string, number>
  anomalous_count: number
  baseline_driven: boolean
  devices: FirmwareFleetControlDevice[]
  page: number
  per_page: number
  total_filtered: number
  total_pages: number
  fetched_at: string
}

export interface CookBehaviorBaseline {
  target_temp_band: string
  firmware_version: string | null
  baseline_version: number
  sample_size: number
  ramp_time_p10: number | null
  ramp_time_p50: number | null
  ramp_time_p90: number | null
  steady_fan_p10: number | null
  steady_fan_p50: number | null
  steady_fan_p90: number | null
  steady_temp_stddev_p50: number | null
  steady_temp_stddev_p90: number | null
  cool_down_rate_p50: number | null
  typical_duration_p50: number | null
  computed_at: string | null
}

export interface CookBehaviorBaselinesResponse {
  baselines: CookBehaviorBaseline[]
  firmware_version: string | null
}

export interface CookBehaviorBacktestRow {
  run_at: string | null
  baseline_version: number
  target_temp_band: string
  metric: string
  sample_size: number
  coverage_pct: number | null
  median_error_pct: number | null
  in_band_count: number
  below_band_count: number
  above_band_count: number
}

export interface CookBehaviorBacktestResponse {
  rows: CookBehaviorBacktestRow[]
}

export interface CookCorrelationSessionSummary {
  session_id: string | null
  start: string | null
  end: string | null
  duration_seconds: number | null
  target_temp: number | null
  cook_intent: string | null
  cook_outcome: string | null
  held_target: boolean | null
  in_control_pct: number | null
  disturbance_count: number | null
  max_overshoot_f: number | null
  max_undershoot_f: number | null
  error_count: number | null
  firmware_version: string | null
}

export interface CookBehaviorTicketResponse {
  ticket_id: string
  correlation: {
    mac: string | null
    ticket_created_at: string | null
    window_start: string | null
    window_end: string | null
    sessions_matched: number
    evidence: {
      mac_resolution?: boolean
      device_ids?: string[]
      sessions?: CookCorrelationSessionSummary[]
    }
    computed_at: string | null
  } | null
}

export interface FirmwareOverviewMetrics {
  start: string
  end: string
  firmware_version: string | null
  sessions: number
  sessions_source: string
  sessions_stale: boolean
  sessions_latest_ts: string | null
  devices: number
  cook_success_rate: number | null
  avg_in_control_pct: number | null
  disconnect_events: number
  disconnect_rate_per_session: number | null
  firmware_distribution: Array<{ firmware_version: string; devices: number; pct: number }>
  product_distribution: Array<{ product: string; devices: number; pct: number }>
  active_devices_window: number
  /** Number of alpha/beta-cohort devices held out of the distributions above.
   *  0 when include_testers=true (or cache-first default, which was built with
   *  testers excluded). Used to label the "X testers held out" footer. */
  test_cohort_excluded?: number
  /** True when this payload includes alpha/beta firmware testers in the
   *  distributions (Firmware Hub asks for this). Default False on Fleet Health. */
  include_testers?: boolean
  cache_info?: {
    key: string
    computed_at: string | null
    duration_ms: number | null
    age_seconds: number | null
    source: string
  } | null
}

export interface FirmwareDeviceRecent {
  mac: string
  nickname: string | null
  last_viewed_at: string | null
}

export interface FirmwareOverview {
  window_hours: number
  active_devices: number
  firmware_distribution: Array<{ firmware_version: string; devices: number; pct: number }>
}

export interface EcrItem {
  task_id: string
  custom_id: string | null
  name: string | null
  description: string | null
  status: string | null
  status_type: string | null
  priority: string | null
  space_name: string | null
  list_name: string | null
  folder_name: string | null
  creator_username: string | null
  assignees: string[]
  url: string | null
  impact_areas: string[]
  dev_complete: string | null
  production_ready: string | null
  field_deploy: string | null
  cx_talking_points: string | null
  updated_at: string | null
  pipeline_stage: string
}

export interface BetaVerdictEvidence {
  per_tag?: Array<{ slug: string; pre: number; post: number; reduction?: number; verdict: string }>
  pre_sessions?: number
  post_sessions?: number
  judgable_tag_count?: number
  verdict?: string
  t0?: string
  evaluated_at?: string
}

export interface BetaProgramSummary {
  total_releases: number
  active_releases: number
  cohort_states: Record<string, number>
  recent: Array<{
    id: number
    version: string
    status: string
    addresses_issues: string[]
    release_health: string | null
    tally: Record<string, number>
    judgable_devices: number
    evaluated_at: string | null
  }>
}

export interface FirmwareDeployPreviewBody {
  release_id: number
  cohort: 'alpha' | 'beta' | 'gamma'
  device_ids?: string[]
  macs?: string[]
}

export interface FirmwareDeviceCheck {
  device_id: string
  mac: string | null
  current_version: string | null
  controller_model: string | null
  active_cook: boolean
  last_sample_age_seconds: number | null
  in_cohort: boolean
  version_is_newer: boolean | null
  model_matches: boolean | null
  hard_block_reasons: string[]
  soft_block_reasons: string[]
}

export interface FirmwarePreflight {
  release_id: number
  cohort: 'alpha' | 'beta' | 'gamma'
  release_ok: boolean
  release_reasons: string[]
  devices: FirmwareDeviceCheck[]
}

export interface FirmwareDeployPreviewResponse {
  token: string
  expires_at: string
  confirmation_required_text: string
  preflight: FirmwarePreflight
  kill_switch_enabled: boolean
}

export interface FirmwareDeployExecuteBody {
  preview_token: string
  confirm_version_typed: string
  override_device_ids?: string[]
  override_reason?: string
}

export interface FirmwareDeployExecuteResponse {
  ok: boolean
  aws_job_id: string
  deployed_device_ids: string[]
  skipped_device_count: number
  preflight: FirmwarePreflight
}

export interface FirmwareDeployStatusResponse {
  aws_job_id: string
  devices: Array<{
    device_id: string
    mac: string | null
    dashboard_status: string
    aws: Record<string, unknown>
    target_version: string | null
    prior_version: string | null
  }>
}

export interface FirmwareDeployLogRow {
  id: number
  release_id: number
  device_id: string
  mac: string | null
  cohort: string
  initiated_by: string
  aws_job_id: string | null
  status: string
  target_version: string | null
  prior_version: string | null
  created_at: string | null
  queued_at: string | null
  confirmed_at: string | null
  finished_at: string | null
  error_message: string | null
}

export interface FirmwareDeployLogResponse {
  total: number
  limit: number
  offset: number
  rows: FirmwareDeployLogRow[]
}

export interface FirmwareReleaseApprovalResponse {
  ok: boolean
  release_id: number
  approved_for_alpha: boolean
  approved_for_beta: boolean
  approved_for_gamma: boolean
  approval_audit_json: Array<{ at: string; by: string; cohort: string; approve: boolean; notes: string }>
}

export interface BetaReleaseSummary {
  id: number
  version: string
  title: string | null
  notes: string | null
  addresses_issues: string[]
  status: string
  beta_cohort_target_size: number
  clickup_task_id: string | null
  git_commit_sha: string | null
  beta_iot_job_id: string | null
  gamma_plan: Record<string, unknown>
  beta_report: Record<string, unknown>
  created_by: string | null
  approved_by: string | null
  approved_at: string | null
  released_at: string | null
  created_at: string | null
  cohort_counts: Record<string, number>
  binary_url?: string | null
  binary_sha256?: string | null
  binary_size_bytes?: number | null
  target_controller_model?: string | null
  approved_for_alpha?: boolean
  approved_for_beta?: boolean
  approved_for_gamma?: boolean
}
