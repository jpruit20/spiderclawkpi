import { BlockedDivisionPage } from '../components/BlockedDivisionPage'
import { ClickUpTasksCard } from '../components/ClickUpTasksCard'
import { SlackPulseCard } from '../components/SlackPulseCard'

export function OperationsDivision() {
  return (
    <>
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
      {/* ClickUp tasks — Operations view. Until an ERP feed lands, ClickUp
          is the most honest source of live operational commitments. */}
      <div className="page-grid" style={{ marginTop: 16 }}>
        <ClickUpTasksCard
          title="ClickUp tasks — Operations"
          subtitle="Tasks from ClickUp that look operational (filter narrows as you tag / organize). A real ops feed will supplement, not replace, this."
          defaultFilter={{ limit: 30 }}
        />
        <SlackPulseCard
          title="Slack pulse — Inventory / Wholesale"
          subtitle="Operational Slack channels: inventory updates, retail/wholesale conversation."
          defaultChannelName="inventory-updates"
        />
      </div>
    </>
  )
}
