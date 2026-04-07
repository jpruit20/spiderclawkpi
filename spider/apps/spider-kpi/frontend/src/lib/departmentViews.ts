import { DecisionAction, currency } from './operatingModel'
import { FreshdeskAgentDailyItem, FreshdeskTicketItem, IssueClusterItem, KPIDaily, SourceHealthItem } from './types'

export interface DepartmentAction {
  title: string
  severity: 'critical' | 'high' | 'medium' | 'low'
  impact: string
  owner: string
  sla: string
  whatToDo: string
  evidence: string[]
}

export interface DepartmentViewModel {
  key: string
  leader: string
  department: string
  summary: string
  whatsWorking: string[]
  whatsNot: string[]
  actions: DepartmentAction[]
  highLevelKpis: Array<{ label: string; value: string }>
  lowLevelSignals: string[]
}

function sum(rows: KPIDaily[], key: keyof KPIDaily) {
  return rows.reduce((total, row) => total + Number(row[key] || 0), 0)
}

function avg(rows: KPIDaily[], key: keyof KPIDaily) {
  return rows.length ? sum(rows, key) / rows.length : 0
}

function pct(value: number, digits = 2) {
  return `${value.toFixed(digits)}%`
}

function hours(value: number, digits = 1) {
  return `${value.toFixed(digits)}h`
}

function sourceHealthy(rows: SourceHealthItem[], source: string) {
  return rows.find((row) => row.source === source)?.derived_status === 'healthy'
}

function sourcePresent(rows: SourceHealthItem[], names: string[]) {
  return rows.some((row) => names.includes(row.source))
}

function mapSeverity(action: DecisionAction['trustState'] | undefined, fallback: DepartmentAction['severity'] = 'medium'): DepartmentAction['severity'] {
  if (action === 'trust_limited') return 'critical'
  if (action === 'conditional') return 'high'
  return fallback
}

function normalizeDate(value?: string) {
  return value ? value.slice(0, 10) : undefined
}

function isClosedStatus(status?: string) {
  const normalized = String(status || '').toLowerCase()
  return normalized.includes('closed') || normalized.includes('resolved') || normalized.includes('solved')
}

export function buildDepartmentViews(input: {
  dailyRows: KPIDaily[]
  supportRows: KPIDaily[]
  sourceHealth: SourceHealthItem[]
  issueClusters: IssueClusterItem[]
  decisionActions: DecisionAction[]
  supportAgents: FreshdeskAgentDailyItem[]
  supportTickets: FreshdeskTicketItem[]
}) {
  const { dailyRows, supportRows, sourceHealth, issueClusters, decisionActions, supportAgents, supportTickets } = input
  const recentDaily = dailyRows.slice(-7)
  const recentSupport = supportRows.slice(-7)
  const latestDaily = recentDaily.at(-1)
  const latestSupport = recentSupport.at(-1)
  const revenue = sum(recentDaily, 'revenue')
  const sessions = sum(recentDaily, 'sessions')
  const orders = sum(recentDaily, 'orders')
  const adSpend = sum(recentDaily, 'ad_spend')
  const aov = orders ? revenue / orders : 0
  const conversion = sessions ? (orders / sessions) * 100 : 0
  const mer = adSpend ? revenue / adSpend : 0
  const addToCart = avg(recentDaily, 'add_to_cart_rate')
  const checkoutCompletion = avg(recentDaily, 'purchases') && avg(recentDaily, 'add_to_cart_rate')
    ? Math.min(100, (avg(recentDaily, 'purchases') / Math.max(1, avg(recentDaily, 'sessions') * (avg(recentDaily, 'add_to_cart_rate') / 100))) * 100)
    : 0

  const leaderByTeam: Record<string, string> = {
    Growth: 'Bailey',
    Marketing: 'Bailey',
    'Support Ops': 'Jeremiah',
    'CX + Product': 'Jeremiah + Kyle',
    Product: 'Kyle',
    Engineering: 'Kyle',
    Operations: 'Conor',
    Manufacturing: 'David',
    'Data Platform': 'Joseph',
  }

  const executiveActions: DepartmentAction[] = decisionActions.slice(0, 5).map((action) => ({
    title: action.title,
    severity: action.severity || mapSeverity(action.trustState, 'high'),
    impact: action.financialImpactLabel,
    owner: leaderByTeam[action.owner] || action.owner,
    sla: action.sla,
    whatToDo: action.recommendedAction || action.why,
    evidence: action.evidenceSources?.length ? action.evidenceSources : ['kpi_daily'],
  }))

  const agentCounts = new Map<string, number>()
  supportTickets.forEach((ticket) => {
    const created = normalizeDate(ticket.created_at_source)
    const cutoff = recentSupport[0]?.business_date
    if (cutoff && created && created < cutoff) return
    const agent = ticket.raw_payload?.responder_name || ticket.agent_id || 'Unassigned'
    agentCounts.set(String(agent), (agentCounts.get(String(agent)) || 0) + 1)
  })
  const totalAssigned = Array.from(agentCounts.values()).reduce((a, b) => a + b, 0)
  const leadAgent = Array.from(agentCounts.entries()).sort((a, b) => b[1] - a[1])[0]
  const overloadedShare = leadAgent && totalAssigned ? (leadAgent[1] / totalAssigned) * 100 : 0

  const avgFrt = avg(recentSupport, 'first_response_time')
  const avgResolution = avg(recentSupport, 'resolution_time')
  const avgBurden = avg(recentSupport, 'tickets_per_100_orders')
  const avgReopen = avg(recentSupport, 'reopen_rate')
  const backlog = Number(latestSupport?.open_backlog || 0)
  const unresolvedAged = supportTickets.filter((ticket) => {
    const created = normalizeDate(ticket.created_at_source)
    if (!created) return false
    if (created > (latestSupport?.business_date || '9999-12-31')) return false
    return !isClosedStatus(ticket.status)
  }).length

  const telemetryPresent = sourcePresent(sourceHealth, ['venom', 'aws_telemetry', 'aws', 'telemetry'])
  const telemetryHealthy = sourceHealthy(sourceHealth, 'venom') || sourceHealthy(sourceHealth, 'aws_telemetry') || sourceHealthy(sourceHealth, 'aws')
  const telemetryIssues = issueClusters.filter((item) => {
    const blob = JSON.stringify(item.details_json || {}).toLowerCase()
    return blob.includes('firmware') || blob.includes('disconnect') || blob.includes('telemetry') || blob.includes('venom') || blob.includes('temperature')
  })
  const telemetryLead = telemetryIssues[0]

  const views: DepartmentViewModel[] = [
    {
      key: 'joseph',
      leader: 'Joseph',
      department: 'Executive command view',
      summary: '10-second ranked intervention stack across revenue, support burden, trust, and issue risk.',
      whatsWorking: [
        sourceHealthy(sourceHealth, 'shopify') && sourceHealthy(sourceHealth, 'triplewhale') ? 'Core commercial sources are healthy enough for top-line decisions.' : 'Commercial source trust is not yet clean.',
        decisionActions[0] ? `A ranked top action exists: ${decisionActions[0].title}.` : 'No ranked executive action yet.',
      ].filter((item) => !item.startsWith('Commercial source trust is not yet clean.')),
      whatsNot: [
        !decisionActions.length ? 'No executive action stack returned.' : '',
        decisionActions.some((action) => action.trustState !== 'trusted') ? 'At least one top executive action is conditional on degraded data trust.' : '',
        !telemetryPresent ? 'AWS / Venom telemetry is not yet live in source health, so product reliability risk is under-observed.' : '',
      ].filter(Boolean),
      actions: executiveActions,
      highLevelKpis: [
        { label: '7d revenue', value: currency(revenue) },
        { label: '7d sessions', value: sessions.toFixed(0) },
        { label: '7d conversion', value: pct(conversion) },
        { label: 'open backlog', value: String(backlog) },
      ],
      lowLevelSignals: [
        `Top issue cluster: ${issueClusters[0]?.title || 'none'}`,
        `Conditional actions: ${decisionActions.filter((action) => action.trustState === 'conditional').length}`,
        `Trust-limited actions: ${decisionActions.filter((action) => action.trustState === 'trust_limited').length}`,
      ],
    },
    {
      key: 'bailey',
      leader: 'Bailey',
      department: 'Marketing',
      summary: 'Channel efficiency and funnel health with explicit next actions instead of passive metrics.',
      whatsWorking: [
        mer >= 3 ? `MER is healthy at ${mer.toFixed(2)}.` : '',
        conversion >= 1.5 ? `Conversion is holding at ${pct(conversion)}.` : '',
        addToCart >= 6 ? `PDP-to-cart rate is supportive at ${pct(addToCart)}.` : '',
      ].filter(Boolean),
      whatsNot: [
        mer < 3 ? `MER is soft at ${mer.toFixed(2)}.` : '',
        conversion < 1.5 ? `Conversion is weak at ${pct(conversion)}.` : '',
        checkoutCompletion < 35 ? `Checkout completion estimate is weak at ${pct(checkoutCompletion)}.` : '',
        !sourceHealthy(sourceHealth, 'ga4') || !sourceHealthy(sourceHealth, 'clarity') ? 'GA4 or Clarity trust is degraded, limiting funnel diagnosis confidence.' : '',
      ].filter(Boolean),
      actions: [
        {
          title: 'Tighten the highest-leak funnel segment this week',
          severity: conversion < 1.2 ? 'critical' : 'high',
          impact: `${currency((sessions * 0.0025 * Math.max(aov, 1)) * 7)}/week`,
          owner: 'Bailey',
          sla: 'This week',
          whatToDo: 'Use GA4 + Clarity to isolate the worst landing / checkout friction path, then fix the highest-traffic leak before increasing spend.',
          evidence: ['ga4', 'clarity', 'shopify'],
        },
      ],
      highLevelKpis: [
        { label: 'revenue', value: currency(revenue) },
        { label: 'sessions', value: sessions.toFixed(0) },
        { label: 'conversion', value: pct(conversion) },
        { label: 'AOV', value: currency(aov) },
        { label: 'MER', value: mer.toFixed(2) },
        { label: 'PDP→cart', value: pct(addToCart) },
        { label: 'checkout completion', value: pct(checkoutCompletion) },
      ],
      lowLevelSignals: [
        sourceHealthy(sourceHealth, 'clarity') ? 'Clarity rage/dead click evidence available for prioritization.' : 'Clarity evidence degraded or unavailable.',
        sourceHealthy(sourceHealth, 'ga4') ? 'GA4 funnel behavior is live for landing-page and checkout diagnosis.' : 'GA4 funnel behavior currently not trustworthy.',
        'Use campaign-level conversion, landing page conversion, checkout step abandonment, CTA interaction, and device leakage as next drill-down layers.',
      ],
    },
    {
      key: 'kyle',
      leader: 'Kyle',
      department: 'New product design / engineering / continuation improvements',
      summary: 'Product reliability and improvement priorities should be driven by telemetry-linked evidence, not anecdote.',
      whatsWorking: [
        telemetryHealthy ? 'AWS / Venom telemetry source appears healthy enough to support product insight.' : '',
        telemetryLead ? `A telemetry-linked issue is already surfacing: ${telemetryLead.title}.` : '',
      ].filter(Boolean),
      whatsNot: [
        !telemetryPresent ? 'AWS / Venom telemetry is not yet exposed as a live source, so Kyle’s page remains partially blind.' : '',
        !telemetryLead ? 'No telemetry-specific issue clusters are being surfaced yet for product prioritization.' : '',
      ].filter(Boolean),
      actions: [
        {
          title: telemetryLead?.title || 'Stand up telemetry-backed product issue ranking',
          severity: telemetryLead ? 'high' : 'critical',
          impact: telemetryLead ? `${currency(Number(telemetryLead.details_json?.priority_score || 250) * 12)}/week estimated` : 'Decision speed blocked',
          owner: 'Kyle',
          sla: telemetryLead ? '72h' : 'This sprint',
          whatToDo: telemetryLead
            ? 'Use firmware/version/grill cohort cuts to confirm the failure pattern, then convert it into a continuation-improvement backlog item with ownership.'
            : 'Wire AWS/Venom telemetry into source health, issue radar, diagnostics, and Kyle’s view so disconnects, temp instability, overrides, and firmware failures rank visibly.',
          evidence: telemetryLead ? ['aws_telemetry', 'issue radar', 'diagnostics'] : ['source health', 'issue radar'],
        },
      ],
      highLevelKpis: [
        { label: 'telemetry source', value: telemetryPresent ? (telemetryHealthy ? 'healthy' : 'degraded') : 'not live' },
        { label: 'telemetry issues', value: String(telemetryIssues.length) },
        { label: 'top product issue', value: telemetryLead?.title || 'none surfaced' },
      ],
      lowLevelSignals: [
        'Desired derived metrics: cook success, disconnect rate, temp stability, stabilization time, firmware health, manual override rate, session reliability.',
        'Desired drill-downs: firmware version, grill type, user cohort, product/use case, overshoot/undershoot patterns.',
        telemetryLead ? `Current leading telemetry-linked signal: ${telemetryLead.title}.` : 'Telemetry-linked clusters are not yet visible in current issue outputs.',
      ],
    },
    {
      key: 'conor',
      leader: 'Conor',
      department: 'Operations',
      summary: 'Operational bottlenecks must be visible even while ERP coverage is incomplete.',
      whatsWorking: [
        backlog < 120 ? 'Customer-facing queue pressure is not overwhelming operations today.' : '',
      ].filter(Boolean),
      whatsNot: [
        'Order throughput, fulfillment aging, stock blockers, and late-ship reasons remain under-modeled until ERP data is live.',
        !sourcePresent(sourceHealth, ['business_central', 'dynamics']) ? 'Dynamics / Business Central is not live, so Conor’s page is still trust-limited.' : '',
      ].filter(Boolean),
      actions: [
        {
          title: 'Close the ERP blind spot for operational risk',
          severity: 'critical',
          impact: 'Operational decisions trust-limited',
          owner: 'Conor',
          sla: 'This sprint',
          whatToDo: 'Connect Dynamics / Business Central and expose order aging buckets, backlog by stage, stock blockers, late-ship reasons, and exception trends.',
          evidence: ['source health', 'executive overview'],
        },
      ],
      highLevelKpis: [
        { label: 'ops data trust', value: sourcePresent(sourceHealth, ['business_central', 'dynamics']) ? 'partial' : 'blocked' },
        { label: 'orders (7d)', value: orders.toFixed(0) },
        { label: 'support backlog', value: String(backlog) },
      ],
      lowLevelSignals: [
        'Required next layers: order aging buckets, backlog by stage, late-ship reasons, stock-related blockers, exception trends.',
      ],
    },
    {
      key: 'david',
      leader: 'David',
      department: 'Production / manufacturing',
      summary: 'Manufacturing should surface defects, rework, yield, and downtime instead of being absent from the operating system.',
      whatsWorking: [],
      whatsNot: [
        'Production output, defect, rework, yield, and downtime data are not yet connected.',
        'No line / shift / batch manufacturing signals are currently visible in the dashboard.',
      ],
      actions: [
        {
          title: 'Add manufacturing signal coverage',
          severity: 'critical',
          impact: 'Manufacturing operating view missing',
          owner: 'David',
          sla: 'Next integration phase',
          whatToDo: 'Ingest production output, defect reasons, rework reasons, station bottlenecks, and batch/shift trends so manufacturing can be managed from the dashboard.',
          evidence: ['source health'],
        },
      ],
      highLevelKpis: [
        { label: 'manufacturing data', value: 'not live' },
      ],
      lowLevelSignals: [
        'Required metrics: output, on-time production, defect rate, rework rate, yield, downtime, bottlenecks.',
      ],
    },
  ]

  return views
}

function currentRowsPerDay(rows: KPIDaily[], key: keyof KPIDaily) {
  return rows.length ? (sum(rows, key) / rows.length).toFixed(1) : '0.0'
}
