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
  betaGammaStatus: (signal?: AbortSignal) =>
    request<GammaStatusResponse>('/api/beta/gamma-status', { signal }),
  ecrs: (includeClosed = false, signal?: AbortSignal) =>
    request<{ ecrs: EcrItem[]; count: number; fields_expected: string[] }>(
      `/api/ecrs?include_closed=${includeClosed}`, { signal },
    ),
  firmwareOverview: (signal?: AbortSignal) =>
    request<FirmwareOverview>('/api/firmware/overview', { signal }),
  firmwareOverviewMetrics: (
    params: { start?: string; end?: string; firmware_version?: string },
    signal?: AbortSignal,
  ) => {
    const q = new URLSearchParams()
    if (params.start) q.set('start', params.start)
    if (params.end) q.set('end', params.end)
    if (params.firmware_version) q.set('firmware_version', params.firmware_version)
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
