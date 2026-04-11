import type {
  CXActionItem,
  CXSnapshotResponse,
  DataQualityResponse,
  DiagnosticItem,
  FreshdeskAgentDailyItem,
  FreshdeskTicketItem,
  IssueRadarResponse,
  KPIIntraday,
  KPIDaily,
  OverviewResponse,
  SocialMention,
  SocialPulse,
  SocialTrend,
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
      return 'https://api-kpi.spidergrills.com'
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
      const response = await fetch(`${API_BASE}${path}`, { cache: 'no-store', signal: controller.signal })
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
  telemetrySummary: (signal?: AbortSignal) => request<TelemetrySummary>('/api/telemetry/summary', { signal }),
  supportOverview: (signal?: AbortSignal) => request<SupportOverviewResponse>('/api/support/overview', { signal }),
  supportAgents: (signal?: AbortSignal) => request<FreshdeskAgentDailyItem[]>('/api/support/agents', { signal }),
  supportTickets: (signal?: AbortSignal) => request<FreshdeskTicketItem[]>('/api/support/tickets', { signal }),
  issues: (signal?: AbortSignal) => request<IssueRadarResponse>('/api/issues', { signal }),
  cxSnapshot: (signal?: AbortSignal) => request<CXSnapshotResponse>('/api/cx/snapshot', { signal }),
  cxActions: (status?: string, signal?: AbortSignal) => request<CXActionItem[]>(`/api/cx/actions${status ? `?status=${encodeURIComponent(status)}` : ''}`, { signal }),
  updateCxAction: (id: string, status: 'open' | 'in_progress' | 'resolved') => fetch(`${API_BASE}/api/cx/actions/${id}/update`, {
    method: 'POST',
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
    request<SocialTrend[]>(`/api/social/trends${days ? `?days=${days}` : ''}`, { signal }),
}
