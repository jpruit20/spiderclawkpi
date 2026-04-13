import type {
  AuthCodeRequestResponse,
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
  OverviewResponse,
  SocialMention,
  SocialPulse,
  SocialTrendsResponse,
  YouTubePerformance,
  AmazonProductHealth,
  MarketIntelligence,
  TelemetrySummary,
  RecommendationItem,
  SourceHealthItem,
  SupportOverviewResponse,
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
  const { signal, timeoutMs = 15000, retries = 1 } = options

  for (let attempt = 0; attempt <= retries; attempt += 1) {
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), timeoutMs)
    const abortListener = () => controller.abort()
    signal?.addEventListener('abort', abortListener)
    const startedAt = performance.now()
    console.info('[kpi-ui] api_request_start', { path, attempt })

    try {
      const response = await fetch(`${API_BASE}${path}`, { cache: 'no-store', signal: controller.signal, credentials: 'include' })
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
  telemetrySummary: (days?: number, signal?: AbortSignal) => request<TelemetrySummary>(`/api/telemetry/summary${days ? `?days=${days}` : ''}`, { signal }),
  supportOverview: (signal?: AbortSignal) => request<SupportOverviewResponse>('/api/support/overview', { signal }),
  supportAgents: (signal?: AbortSignal) => request<FreshdeskAgentDailyItem[]>('/api/support/agents', { signal }),
  supportTickets: (signal?: AbortSignal) => request<FreshdeskTicketItem[]>('/api/support/tickets', { signal }),
  issues: (signal?: AbortSignal) => request<IssueRadarResponse>('/api/issues', { signal }),
  clusterDetail: (theme: string, signal?: AbortSignal) => request<ClusterTicketDetail>(`/api/issues/clusters/${encodeURIComponent(theme)}/detail`, { signal }),
  cxSnapshot: (signal?: AbortSignal) => request<CXSnapshotResponse>('/api/cx/snapshot', { signal }),
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
}
