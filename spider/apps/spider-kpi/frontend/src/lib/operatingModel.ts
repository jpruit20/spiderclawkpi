import { DiagnosticItem, IssueClusterItem, KPIDaily, RecommendationItem, SourceHealthItem } from './types'

export type ActionLifecycle = 'open' | 'in_progress' | 'validated' | 'closed'
export type ActionTrustState = 'trusted' | 'conditional' | 'trust_limited'

export interface DecisionAction {
  id: string
  title: string
  why: string
  owner: string
  sla: string
  lifecycle: ActionLifecycle
  impactWeekly: number
  confidence: number
  baseConfidence: number
  confidencePenalty: number
  financialImpactLabel: string
  signal: 'revenue' | 'conversion' | 'friction' | 'support' | 'trust'
  severity?: 'critical' | 'high' | 'medium' | 'low'
  recommendedAction?: string
  evidenceSources?: string[]
  priorityScore: number
  trustState: ActionTrustState
  trustLabel: string
  blockedBy: string[]
  canonicalRank?: number
}

export interface ConfidenceInputs {
  sourceHealth: SourceHealthItem[]
  requiredSources: string[]
  sampleSize?: number
  completeness?: number
}

const LIFE_ORDER: ActionLifecycle[] = ['open', 'in_progress', 'validated', 'closed']
const CORE_SOURCES = ['shopify', 'triplewhale', 'freshdesk', 'clarity', 'ga4']

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

function unhealthySources(sourceHealth: SourceHealthItem[], requiredSources: string[]) {
  return requiredSources.filter((name) => sourceHealth.find((row) => row.source === name)?.derived_status !== 'healthy')
}

function trustStateFor(blockedBy: string[]) {
  if (blockedBy.length >= 2) return 'trust_limited'
  if (blockedBy.length === 1) return 'conditional'
  return 'trusted'
}

function trustLabelFor(blockedBy: string[]) {
  if (blockedBy.length >= 2) return `Trust-limited · depends on ${blockedBy.join(', ')}`
  if (blockedBy.length === 1) return `Conditional · depends on ${blockedBy[0]}`
  return 'Trusted'
}

function withTrust(action: Omit<DecisionAction, 'baseConfidence' | 'confidencePenalty' | 'trustState' | 'trustLabel' | 'blockedBy'>, sourceHealth: SourceHealthItem[], requiredSources: string[]): DecisionAction {
  const blockedBy = unhealthySources(sourceHealth, requiredSources)
  const penalty = blockedBy.length >= 2 ? 0.3 : blockedBy.length === 1 ? 0.15 : 0
  const confidence = Math.max(0.15, Number((action.confidence - penalty).toFixed(2)))
  const trustState = trustStateFor(blockedBy)
  return {
    ...action,
    baseConfidence: action.confidence,
    confidencePenalty: penalty,
    confidence,
    trustState,
    trustLabel: trustLabelFor(blockedBy),
    blockedBy,
    priorityScore: Number((action.impactWeekly * confidence).toFixed(2)),
  }
}

export function frictionRankingScore(input: {
  impact: number
  confidence: number
  sourceHealth: SourceHealthItem[]
  usesClarity: boolean
  corroborated: boolean
}) {
  const { impact, confidence, sourceHealth, usesClarity, corroborated } = input
  const clarityHealthy = sourceHealth.find((row) => row.source === 'clarity')?.derived_status === 'healthy'
  if (usesClarity && !clarityHealthy && !corroborated) {
    return Number((impact * Math.min(confidence, 0.15) * 0.05).toFixed(2))
  }
  return Number((impact * confidence).toFixed(2))
}

export function rankActions(actions: DecisionAction[]) {
  return [...actions]
    .sort((a, b) => b.priorityScore - a.priorityScore || b.impactWeekly - a.impactWeekly || b.confidence - a.confidence)
    .map((action, index) => ({ ...action, canonicalRank: index + 1 }))
}

export function summarizeTrust(sourceHealth: SourceHealthItem[]) {
  const relevant = sourceHealth.filter((row) => CORE_SOURCES.includes(row.source))
  const degraded = relevant.filter((row) => row.derived_status !== 'healthy')
  return {
    total: relevant.length,
    healthy: relevant.length - degraded.length,
    degraded: degraded.length,
    degradedSources: degraded.map((row) => row.source),
  }
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
  const action = withTrust({
    id: 'action-diagnostic-primary',
    title: recommendation?.title || diagnostic?.title || 'Address primary commercial drag',
    why: recommendation?.recommended_action || diagnostic?.summary || 'Primary evidence set suggests this is the top recoverable revenue constraint.',
    owner: recommendation?.owner_team || diagnostic?.owner_team || 'Marketing',
    sla: '48h',
    lifecycle: lifecycleFromMetadata(recommendation?.metadata_json),
    impactWeekly: impact,
    confidence: confidenceScore({
      sourceHealth,
      requiredSources: ['shopify', 'triplewhale'],
      sampleSize: sessions,
      completeness: diagnostic ? Number(diagnostic.confidence || 0.6) : 0.55,
    }),
    financialImpactLabel: `${currency(impact)}/week`,
    signal: 'conversion',
    severity: 'high',
    recommendedAction: recommendation?.recommended_action || 'Inspect the top commercial drag and fix the highest-confidence conversion constraint before expanding spend.',
    evidenceSources: ['shopify', 'triplewhale', diagnostic ? 'diagnostics' : 'overview'],
    priorityScore: impact,
  }, sourceHealth, ['shopify', 'triplewhale'])
  return [action]
}

export function backlogAction(rows: KPIDaily[], sourceHealth: SourceHealthItem[]): DecisionAction[] {
  const latest = rows.at(-1)
  if (!latest || !latest.open_backlog) return []
  const backlog = Number(latest.open_backlog || 0)
  const sessions = Number(latest.sessions || 0)
  const aov = Number(latest.average_order_value || 0)
  const impact = impactFromConversion(sessions * 0.18, Math.min(0.45, backlog / 1500), aov) * 7
  const action = withTrust({
    id: 'action-support-backlog',
    title: 'Reduce support backlog before it suppresses conversion',
    why: `Open backlog is ${backlog}, which increases purchase hesitation and repeat-contact drag.`,
    owner: 'Support Ops',
    sla: '24h',
    lifecycle: 'open',
    impactWeekly: impact,
    confidence: confidenceScore({
      sourceHealth,
      requiredSources: ['freshdesk', 'shopify'],
      sampleSize: backlog,
      completeness: backlog > 0 ? 0.85 : 0.5,
    }),
    financialImpactLabel: `${currency(impact)}/week`,
    signal: 'support',
    severity: backlog > 200 ? 'critical' : 'high',
    recommendedAction: 'Rebalance support load, clear aged backlog, and prevent queue drag from suppressing purchase confidence.',
    evidenceSources: ['freshdesk', 'shopify'],
    priorityScore: impact,
  }, sourceHealth, ['freshdesk', 'shopify'])
  return [action]
}

export function issueAction(issue: IssueClusterItem | undefined, latest: KPIDaily | undefined, sourceHealth: SourceHealthItem[]): DecisionAction[] {
  if (!issue || !latest) return []
  const burden = Number(issue.details_json?.tickets_per_100_orders_by_theme || issue.details_json?.tickets_per_100_orders || 8)
  const convDelta = Math.min(0.6, Math.max(0.12, burden / 100))
  const impact = impactFromConversion(Number(latest.sessions || 0) * 0.35, convDelta, Number(latest.average_order_value || 0)) * 7
  const action = withTrust({
    id: `action-issue-${issue.id}`,
    title: issue.title,
    why: String(issue.details_json?.priority_reason_summary || 'High-friction issue is creating revenue drag.'),
    owner: issue.owner_team || 'CX + Product',
    sla: '72h',
    lifecycle: lifecycleFromMetadata(issue.details_json as Record<string, unknown>),
    impactWeekly: impact,
    confidence: confidenceScore({
      sourceHealth,
      requiredSources: ['freshdesk', 'clarity', 'ga4'],
      sampleSize: Number(issue.details_json?.priority_score || 100),
      completeness: Number(issue.confidence || 0.6),
    }),
    financialImpactLabel: `${currency(impact)}/week`,
    signal: 'friction',
    severity: issue.severity === 'high' ? 'critical' : issue.severity === 'medium' ? 'high' : 'medium',
    recommendedAction: String(issue.details_json?.recommended_action || 'Confirm root cause, assign an owner, and remove the highest-burden friction path.'),
    evidenceSources: ['freshdesk', 'clarity', 'ga4'],
    priorityScore: impact,
  }, sourceHealth, ['freshdesk', 'clarity', 'ga4'])
  return [action]
}

export function trustAction(sourceHealth: SourceHealthItem[], latest: KPIDaily | undefined): DecisionAction[] {
  const unhealthy = sourceHealth.filter((row) => CORE_SOURCES.includes(row.source) && row.derived_status !== 'healthy')
  if (!unhealthy.length || !latest) return []
  const impact = impactFromConversion(Number(latest.sessions || 0), 0.1, Number(latest.average_order_value || 0)) * 7
  return [{
    id: 'action-data-trust',
    title: 'Restore data trust before changing spend or UX',
    why: `Unhealthy sources: ${unhealthy.map((row) => row.source).join(', ')}. Dependent insights should not drive revenue decisions until trust is restored.`,
    owner: 'Data Platform',
    sla: '4h',
    lifecycle: 'open',
    impactWeekly: impact,
    confidence: 0.4,
    baseConfidence: 0.4,
    confidencePenalty: 0,
    financialImpactLabel: `${currency(impact)}/week at risk`,
    signal: 'trust',
    severity: 'critical',
    recommendedAction: 'Restore unhealthy sources before changing spend, UX, or operational priorities.',
    evidenceSources: unhealthy.map((row) => row.source),
    priorityScore: Number((impact * 0.4).toFixed(2)),
    trustState: 'trusted',
    trustLabel: 'Trusted',
    blockedBy: [],
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
