import { compareValue } from './compare'
import { ActionObject, BlockedStateOutput, KPIObject, KPIStatus, KPITrend, KPITruthState, SourceHealthItem } from './types'

export type RankedActionObject = ActionObject & {
  truth_state: KPITruthState
  sample_reliability?: KPIObject['sample_reliability']
  ranking_score: number
  ranking_reason: string
  can_top_rank: boolean
  blocked_state?: BlockedStateOutput
}

function directionFor(deltaPct: number | null): KPIObject['delta']['direction'] {
  if (deltaPct === null || Number.isNaN(deltaPct)) return 'unknown'
  if (Math.abs(deltaPct) < 0.01) return 'flat'
  return deltaPct > 0 ? 'improving' : 'worsening'
}

export function trendFromDelta(deltaPct: number | null): KPITrend {
  if (deltaPct === null || Number.isNaN(deltaPct) || Math.abs(deltaPct) < 0.01) return 'flat'
  return deltaPct > 0 ? 'up' : 'down'
}

export function statusFromNumeric(current: number | null, target: number | null, thresholds?: { greenAtOrAbove?: number; yellowAtOrAbove?: number }): KPIStatus {
  if (current === null) return 'red'
  if (thresholds?.greenAtOrAbove !== undefined && current >= thresholds.greenAtOrAbove) return 'green'
  if (thresholds?.yellowAtOrAbove !== undefined && current >= thresholds.yellowAtOrAbove) return 'yellow'
  if (target !== null && target !== 0) {
    const ratio = current / target
    if (ratio >= 1) return 'green'
    if (ratio >= 0.85) return 'yellow'
  }
  return 'red'
}

export function buildNumericKpi(input: {
  key: string
  currentValue: number | null
  targetValue: number | null
  priorValue?: number | null
  owner: string
  truthState: KPITruthState
  lastUpdated: string
  comparisonBasis?: KPIObject['delta']['comparison_basis']
  thresholds?: { greenAtOrAbove?: number; yellowAtOrAbove?: number }
  sampleSize?: number | null
  sampleScope?: string | null
  sampleReliability?: KPIObject['sample_reliability']
}): KPIObject {
  const comparison = compareValue(input.currentValue ?? 0, input.priorValue ?? null, input.key)
  return {
    key: input.key,
    current_value: input.currentValue,
    target_value: input.targetValue,
    delta: {
      absolute: comparison.delta,
      percent: comparison.deltaPct,
      direction: directionFor(comparison.deltaPct),
      comparison_basis: input.comparisonBasis || 'vs_prior_period',
    },
    trend: trendFromDelta(comparison.deltaPct),
    owner: input.owner,
    status: statusFromNumeric(input.currentValue, input.targetValue, input.thresholds),
    truth_state: input.truthState,
    last_updated: input.lastUpdated,
    sample_size: input.sampleSize ?? null,
    sample_scope: input.sampleScope ?? null,
    sample_reliability: input.sampleReliability ?? null,
  }
}

export function buildTextKpi(input: {
  key: string
  currentValue: string | null
  targetValue: string | null
  owner: string
  status: KPIStatus
  truthState: KPITruthState
  lastUpdated: string
  sampleSize?: number | null
  sampleScope?: string | null
  sampleReliability?: KPIObject['sample_reliability']
}): KPIObject {
  return {
    key: input.key,
    current_value: input.currentValue,
    target_value: input.targetValue,
    delta: {
      absolute: null,
      percent: null,
      direction: 'unknown',
      comparison_basis: 'vs_prior_period',
    },
    trend: 'flat',
    owner: input.owner,
    status: input.status,
    truth_state: input.truthState,
    last_updated: input.lastUpdated,
    sample_size: input.sampleSize ?? null,
    sample_scope: input.sampleScope ?? null,
    sample_reliability: input.sampleReliability ?? null,
  }
}

export function buildBlockedState(output: BlockedStateOutput): BlockedStateOutput {
  return output
}

export function truthStateFromSource(sourceHealth: SourceHealthItem[], requiredSources: string[], fallback: KPITruthState = 'canonical'): KPITruthState {
  if (!requiredSources.length) return fallback
  const rows = requiredSources.map((source) => sourceHealth.find((row) => row.source === source)).filter(Boolean)
  if (!rows.length) return 'blocked'
  const missing = requiredSources.filter((source) => !sourceHealth.find((row) => row.source === source))
  if (missing.length) return 'blocked'
  const degraded = rows.some((row) => row && row.derived_status !== 'healthy')
  return degraded ? 'degraded' : fallback
}

export function sampleReliabilityMultiplier(sampleReliability: KPIObject['sample_reliability']) {
  switch (sampleReliability) {
    case 'high': return 1
    case 'medium': return 0.8
    case 'low': return 0.45
    default: return 0.7
  }
}

export function truthStateMultiplier(truthState: KPITruthState) {
  switch (truthState) {
    case 'canonical': return 1
    case 'proxy': return 0.85
    case 'estimated': return 0.7
    case 'degraded': return 0.35
    case 'blocked': return 0
    case 'unavailable': return 0
    default: return 0.5
  }
}

export function canTopRank(truthState: KPITruthState) {
  return truthState === 'canonical' || truthState === 'proxy' || truthState === 'estimated'
}

export function enforceActionContract(actions: RankedActionObject[]) {
  return [...actions]
    .map((action) => {
      const multiplier = truthStateMultiplier(action.truth_state) * sampleReliabilityMultiplier(action.sample_reliability ?? null)
      const ranking_score = Number((action.ranking_score * multiplier).toFixed(2))
      const blockedOptimization = action.truth_state === 'blocked' && !action.required_action.toLowerCase().includes('unblock')
      const lowSampleConfidence = action.sample_reliability === 'low'
      const can_top_rank = canTopRank(action.truth_state) && !blockedOptimization && !lowSampleConfidence
      return {
        ...action,
        ranking_score: can_top_rank ? ranking_score : -1,
        can_top_rank,
        ranking_reason: blockedOptimization
          ? 'blocked KPI may only emit unblock actions'
          : lowSampleConfidence
            ? 'limited sample — directional only; keep as early warning, not top-ranked decision'
            : action.truth_state === 'degraded'
              ? 'degraded KPI ranking suppressed by truth-state enforcement'
              : action.truth_state === 'blocked'
                ? 'blocked KPI can only rank unblock actions below optimization actions'
                : action.ranking_reason,
      }
    })
    .sort((a, b) => b.ranking_score - a.ranking_score)
}

export function actionFromKpi(input: {
  id: string
  triggerKpi: KPIObject
  triggerCondition: string
  owner: string
  requiredAction: string
  priority: ActionObject['priority']
  status?: ActionObject['status']
  evidence: string[]
  dueDate: string
  snapshotTimestamp: string
  coOwner?: string
  escalationOwner?: string
  baseRankingScore: number
  blockedState?: BlockedStateOutput
  scope?: ActionObject['scope']
  confidence?: ActionObject['confidence']
}): RankedActionObject {
  return {
    id: input.id,
    trigger_kpi: input.triggerKpi.key,
    trigger_condition: input.triggerCondition,
    owner: input.owner,
    co_owner: input.coOwner,
    escalation_owner: input.escalationOwner,
    required_action: input.requiredAction,
    priority: input.priority,
    status: input.status || 'open',
    evidence: input.evidence,
    due_date: input.dueDate,
    snapshot_timestamp: input.snapshotTimestamp,
    scope: input.scope,
    confidence: input.confidence,
    truth_state: input.triggerKpi.truth_state,
    sample_reliability: input.triggerKpi.sample_reliability,
    ranking_score: input.baseRankingScore,
    ranking_reason: 'base ranking derived from business impact before truth-state enforcement',
    can_top_rank: canTopRank(input.triggerKpi.truth_state),
    blocked_state: input.blockedState,
  }
}
