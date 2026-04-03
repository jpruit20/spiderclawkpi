import type {
  DataQualityResponse,
  DiagnosticItem,
  FreshdeskAgentDailyItem,
  FreshdeskTicketItem,
  IssueRadarResponse,
  KPIIntraday,
  KPIDaily,
  OverviewResponse,
  RecommendationItem,
  SourceHealthItem,
  SupportOverviewResponse,
} from './types'

const DEFAULT_API_BASE = ''
const API_BASE = (import.meta.env.VITE_API_BASE || DEFAULT_API_BASE).replace(/\/$/, '')
const APP_PASSWORD = import.meta.env.VITE_APP_PASSWORD || ''

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

async function request<T>(path: string): Promise<T> {
  const headers: HeadersInit = APP_PASSWORD ? { 'X-App-Password': APP_PASSWORD } : {}
  const response = await fetch(`${API_BASE}${path}`, { cache: 'no-store', headers })
  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new ApiError(`API error ${response.status} for ${path}${detail ? `: ${detail}` : ''}`, response.status, path)
  }
  return response.json()
}

export function getApiBase() {
  return API_BASE
}

export const api = {
  overview: () => request<OverviewResponse>('/api/overview'),
  dailyKpis: () => request<KPIDaily[]>('/api/kpis/daily'),
  currentKpi: async () => {
    const payload = await request<{ latest: KPIIntraday | null }>('/api/kpis/intraday')
    return payload.latest
  },
  intradaySeries: () => request<{ rows: Array<{ bucket_start: string; hour_label: string; revenue: number; sessions: number; orders: number }> }>('/api/kpis/intraday-series'),
  diagnostics: () => request<DiagnosticItem[]>('/api/diagnostics'),
  alerts: () => request('/api/alerts'),
  recommendations: () => request<RecommendationItem[]>('/api/recommendations'),
  sourceHealth: () => request<SourceHealthItem[]>('/api/source-health'),
  supportOverview: () => request<SupportOverviewResponse>('/api/support/overview'),
  supportAgents: () => request<FreshdeskAgentDailyItem[]>('/api/support/agents'),
  supportTickets: () => request<FreshdeskTicketItem[]>('/api/support/tickets'),
  issues: () => request<IssueRadarResponse>('/api/issues'),
  dataQuality: () => request<DataQualityResponse>('/api/data-quality'),
}
