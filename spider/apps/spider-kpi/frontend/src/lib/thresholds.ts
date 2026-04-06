import { ThresholdTone } from './decisionSupport'

export type ThresholdDirection = 'higher_is_better' | 'lower_is_better'

export interface ThresholdDefinition {
  metric: string
  label: string
  good?: number
  warn?: number
  direction: ThresholdDirection
  unit?: 'currency' | 'percent' | 'hours' | 'count' | 'ratio'
  reason: string
}

export interface ThresholdSummary extends ThresholdDefinition {
  tone: ThresholdTone
  gapToGood?: number | null
  gapToWarn?: number | null
}

export const THRESHOLDS: Record<string, ThresholdDefinition> = {
  conversion_rate: {
    metric: 'conversion_rate',
    label: 'Conversion',
    good: 1.5,
    warn: 1.0,
    direction: 'higher_is_better',
    unit: 'percent',
    reason: 'Below 1% means traffic is not turning into orders efficiently enough to scale demand confidently.',
  },
  mer: {
    metric: 'mer',
    label: 'MER',
    good: 4,
    warn: 3,
    direction: 'higher_is_better',
    unit: 'ratio',
    reason: 'Sub-3 MER is a warning that media efficiency is soft relative to revenue output.',
  },
  average_order_value: {
    metric: 'average_order_value',
    label: 'AOV',
    good: 500,
    warn: 400,
    direction: 'higher_is_better',
    unit: 'currency',
    reason: 'AOV below the merchandising target usually means bundle/accessory leverage is weak.',
  },
  open_backlog: {
    metric: 'open_backlog',
    label: 'Open backlog',
    good: 150,
    warn: 250,
    direction: 'lower_is_better',
    unit: 'count',
    reason: 'Elevated backlog means support demand is outpacing handling capacity or issue recurrence is rising.',
  },
  tickets_per_100_orders: {
    metric: 'tickets_per_100_orders',
    label: 'Tickets / 100 orders',
    good: 10,
    warn: 20,
    direction: 'lower_is_better',
    unit: 'count',
    reason: 'Support burden above 20 / 100 orders signals product, logistics, or expectation problems worth operational action.',
  },
  first_response_time: {
    metric: 'first_response_time',
    label: 'First response time',
    good: 4,
    warn: 12,
    direction: 'lower_is_better',
    unit: 'hours',
    reason: 'Slow first response increases customer anxiety and can amplify refund, cancellation, and complaint risk.',
  },
  resolution_time: {
    metric: 'resolution_time',
    label: 'Resolution time',
    good: 24,
    warn: 48,
    direction: 'lower_is_better',
    unit: 'hours',
    reason: 'Resolution time above 48 hours usually indicates queue congestion, repeated follow-up, or unclear ownership.',
  },
  sla_breach_rate: {
    metric: 'sla_breach_rate',
    label: 'SLA breach rate',
    good: 10,
    warn: 20,
    direction: 'lower_is_better',
    unit: 'percent',
    reason: 'SLA breach rate rising above 20% means the support operation is missing promised customer response commitments too often.',
  },
  bounce_rate: {
    metric: 'bounce_rate',
    label: 'Bounce rate',
    good: 45,
    warn: 60,
    direction: 'lower_is_better',
    unit: 'percent',
    reason: 'High bounce rate on meaningful landing pages suggests traffic mismatch, weak messaging, or page-load / UX friction.',
  },
}

export function evaluateThreshold(metric: string, value?: number | null): ThresholdTone {
  const definition = THRESHOLDS[metric]
  if (!definition || value == null) return 'muted'

  if (definition.direction === 'higher_is_better') {
    if (definition.good != null && value >= definition.good) return 'good'
    if (definition.warn != null && value >= definition.warn) return 'warn'
    return 'bad'
  }

  if (definition.good != null && value <= definition.good) return 'good'
  if (definition.warn != null && value <= definition.warn) return 'warn'
  return 'bad'
}

function gapToTarget(definition: ThresholdDefinition, value?: number | null, target?: number) {
  if (value == null || target == null) return null
  return definition.direction === 'higher_is_better' ? value - target : target - value
}

export function thresholdSummary(metric: string, value?: number | null): ThresholdSummary | null {
  const definition = THRESHOLDS[metric]
  const tone = evaluateThreshold(metric, value)
  return definition
    ? {
        ...definition,
        tone,
        gapToGood: gapToTarget(definition, value, definition.good),
        gapToWarn: gapToTarget(definition, value, definition.warn),
      }
    : null
}
