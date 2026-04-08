import { BlockedDivisionPage } from '../components/BlockedDivisionPage'

export function OperationsDivision() {
  return (
    <BlockedDivisionPage
      title="Operations"
      owner="Conor"
      summary="Order throughput, aging, late-ship exposure, exception volume, and bottlenecks should live here once ops/ERP sources are real enough to trust."
      blockedReason="This page is intentionally blocked from showing fake throughput, aging, or late-shipment truth before the underlying operations/ERP feed is available in a decision-grade form."
      readiness={[
        { label: 'Order/ERP feed', status: 'blocked', detail: 'Business Central / Dynamics operational feed is not yet live in the KPI backend.' },
        { label: 'Backlog staging model', status: 'blocked', detail: 'Stage-by-stage order aging and exception state are not exposed yet.' },
        { label: 'Customer-facing proxy data', status: 'partial', detail: 'Support and revenue can hint at operational pain, but they are not substitutes for real ops truth.' },
      ]}
      requiredMetrics={[
        'Order throughput',
        'Fulfillment speed',
        'Aged orders',
        'Inventory bottlenecks',
        'Late shipment exposure',
        'Operational exception volume',
      ]}
      sources={['Business Central / Dynamics', 'Shopify fulfillment events', 'Operations exception logs']}
      actions={[
        {
          title: 'Connect operational source of truth',
          owner: 'Conor',
          sla: 'Next integration phase',
          why: 'Without order-stage and late-ship truth, an operations page would be theater.',
          nextStep: 'Expose order aging buckets, backlog by stage, late-ship reasons, stock blockers, and exception trends from the operational system of record.',
        },
      ]}
      drilldowns={[{ label: 'Open Financial / Revenue', href: '/revenue' }, { label: 'Open System Health', href: '/system-health' }]}
    />
  )
}
