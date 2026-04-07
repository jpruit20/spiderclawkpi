import { DiagnosticItem, IssueClusterItem, KPIDaily, RecommendationItem, SourceHealthItem } from './types'

export type ActionLifecycle = 'open' | 'in_progress' | 'validated' | 'closed'

export interface DecisionAction {
  id: string
  title: string
  why: string
  owner: string
  sla: string
  lifecycle: ActionLifecycle
  impactWeekly: number
  confidence: number
  financialImpactLabel: string
  signal: 'revenue' | 'conversion' | 'friction' | 'support' | 'trust'
  priorityScore: number
}

export interface ConfidenceInputs {
  sourceHealth: SourceHealthItem[]
  requiredSources: string[]
  sampleSize?: number
  completeness?: number
}

const LIFE_ORDER: ActionLifecycle[] = ['open', 'in_progress', 'validated', 'closed']

export function impactFromConversion(sessions: number, conversionDeltaPctPoints: number, aov: number) {
  const conversionDelta = conversionDeltaPctPoints / 100
  return sessions * conversionDelta * aov
}

export function currency(value: number) {
  const sign = value < 0 ? '-' : ''
  const abs = Math.abs(value)
  if (abs >= 1000) return `${sign}$${(abs / 1000).toFixed(1)}k`
  return `${sign}$${abs.toFixed(0)}`
}

export function confidenceScore(inputs: ConfidenceInputs) {
  const { sourceHealth, requiredSources, sampleSize = 0, completeness = 1 } = inputs
  const required = requiredSources.length || 1
  const healthy = requiredSources.filter((name) => sourceHealth.find((row) => row.source === name)?.derived_status === 'healthy').length
  const healthScore = healthy / required
  const sampleScore = Math.min(1, sampleSize / 5000)
  const completenessScore = Math.max(0, Math.min(1, completeness))
  return Number(((healthScore * 0.5) + (sampleScore * 0.25) + (completenessScore * 0.25)).toFixed(2))
}

function lifecycleFromMetadata(metadata: Record<string, unknown> | undefined): ActionLifecycle {
  const value = String(metadata?.action_state || metadata?.lifecycle || 'open')
  return LIFE_ORDER.includes(value as ActionLifecycle) ? (value as ActionLifecycle) : 'open'
}

export function rankActions(actions: DecisionAction[]) {
  return [...actions].sort((a, b) => b.priorityScore - a.priorityScore || b.impactWeekly - a.impactWeekly || b.confidence - a.confidence)
}

export function topDiagnosticAction(
  rows: KPIDaily[],
  sourceHealth: SourceHealthItem[],
  diagnostics: DiagnosticItem[],
  recommendations: RecommendationItem[],
): DecisionAction[] {
  const latest = rows.at(-1)
  if (!latest) return []
  const sessions = Number(latest.sessions || 0)
  const aov = Number(latest.average_order_value || 0)
  const recommendation = recommendations[0]
  const diagnostic = diagnostics[0]
  if (!recommendation && !diagnostic) return []
  const convDelta = Math.max(0.15, Math.abs(Number(diagnostic?.details_json?.conversion_change_pct || 0)) / 100)
  const impact = impactFromConversion(sessions, convDelta, aov) * 7
  const confidence = confidenceScore({
    sourceHealth,
    requiredSources: ['shopify', 'triplewhale'],
    sampleSize: sessions,
    completeness: diagnostic ? Number(diagnostic.confidence || 0.6) : 0.55,
  })
  return [{
    id: 'action-diagnostic-primary',
    title: recommendation?.title || diagnostic?.title || 'Address primary commercial drag',
    why: recommendation?.recommended_action || diagnostic?.summary || 'Primary evidence set suggests this is the top recoverable revenue constraint.',
    owner: recommendation?.owner_team || diagnostic?.owner_team || 'Growth',
    sla: '48h',
    lifecycle: lifecycleFromMetadata(recommendation?.metadata_json),
    impactWeekly: impact,
    confidence,
    financialImpactLabel: `${currency(impact)}/week`,
    signal: 'conversion',
    priorityScore: impact * confidence,
  }]
}

export function backlogAction(rows: KPIDaily[], sourceHealth: SourceHealthItem[]): DecisionAction[] {
  const latest = rows.at(-1)
  if (!latest || !latest.open_backlog) return []
  const backlog = Number(latest.open_backlog || 0)
  const sessions = Number(latest.sessions || 0)
  const aov = Number(latest.average_order_value || 0)
  const impact = impactFromConversion(sessions * 0.18, Math.min(0.45, backlog / 1500), aov) * 7
  const confidence = confidenceScore({
    sourceHealth,
    requiredSources: ['freshdesk', 'shopify'],
    sampleSize: backlog,
    completeness: backlog > 0 ? 0.85 : 0.5,
  })
  return [{
    id: 'action-support-backlog',
    title: 'Reduce support backlog before it suppresses conversion',
    why: `Open backlog is ${backlog}, which increases purchase hesitation and repeat-contact drag.`,
    owner: 'Support Ops',
    sla: '24h',
    lifecycle: 'open',
    impactWeekly: impact,
    confidence,
    financialImpactLabel: `${currency(impact)}/week`,
    signal: 'support',
    priorityScore: impact * confidence,
  }]
}

export function issueAction(issue: IssueClusterItem | undefined, latest: KPIDaily | undefined, sourceHealth: SourceHealthItem[]): DecisionAction[] {
  if (!issue || !latest) return []
  const burden = Number(issue.details_json?.tickets_per_100_orders_by_theme || issue.details_json?.tickets_per_100_orders || 8)
  const convDelta = Math.min(0.6, Math.max(0.12, burden / 100))
  const impact = impactFromConversion(Number(latest.sessions || 0) * 0.35, convDelta, Number(latest.average_order_value || 0)) * 7
  const confidence = confidenceScore({
    sourceHealth,
    requiredSources: ['freshdesk', 'clarity', 'ga4'],
    sampleSize: Number(issue.details_json?.priority_score || 100),
    completeness: Number(issue.confidence || 0.6),
  })
  return [{
    id: `action-issue-${issue.id}`,
    title: issue.title,
    why: String(issue.details_json?.priority_reason_summary || 'High-friction issue is creating revenue drag.'),
    owner: issue.owner_team || 'CX + Product',
    sla: '72h',
    lifecycle: lifecycleFromMetadata(issue.details_json as Record<string, unknown>),
    impactWeekly: impact,
    confidence,
    financialImpactLabel: `${currency(impact)}/week`,
    signal: 'friction',
    priorityScore: impact * confidence,
  }]
}

export function trustAction(sourceHealth: SourceHealthItem[], latest: KPIDaily | undefined): DecisionAction[] {
  const unhealthy = sourceHealth.filter((row) => ['shopify', 'triplewhale', 'freshdesk', 'clarity', 'ga4'].includes(row.source) && row.derived_status !== 'healthy')
  if (!unhealthy.length || !latest) return []
  const impact = impactFromConversion(Number(latest.sessions || 0), 0.1, Number(latest.average_order_value || 0)) * 7
  const confidence = 0.4
  return [{
    id: 'action-data-trust',
    title: 'Restore data trust before changing spend or UX',
    why: `Unhealthy sources: ${unhealthy.map((row) => row.source).join(', ')}. Dependent insights should not drive revenue decisions until trust is restored.`,
    owner: 'Data Platform',
    sla: '4h',
    lifecycle: 'open',
    impactWeekly: impact,
    confidence,
    financialImpactLabel: `${currency(impact)}/week at risk`,
    signal: 'trust',
    priorityScore: impact * confidence,
  }]
}

export function summarizeLifecycle(actions: DecisionAction[]) {
  return {
    open: actions.filter((a) => a.lifecycle === 'open').length,
    in_progress: actions.filter((a) => a.lifecycle === 'in_progress').length,
    validated: actions.filter((a) => a.lifecycle === 'validated').length,
    closed: actions.filter((a) => a.lifecycle === 'closed').length,
    revenueRecovered: actions.filter((a) => a.lifecycle === 'validated' || a.lifecycle === 'closed').reduce((sum, a) => sum + a.impactWeekly, 0),
  }
}
