import { BlockedDivisionPage } from '../components/BlockedDivisionPage'
import { ClickUpComplianceCard } from '../components/ClickUpComplianceCard'
import { ClickUpTasksCard } from '../components/ClickUpTasksCard'
import { ClickUpVelocityCard } from '../components/ClickUpVelocityCard'
import { SlackPulseCard } from '../components/SlackPulseCard'
import { EmailPulseCard } from '../components/EmailPulseCard'

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
        <ClickUpVelocityCard
          title="Team velocity — all ClickUp"
          subtitle="Throughput + cycle time across every space until an Ops space is stood up."
        />
        <ClickUpComplianceCard
          title="Tagging compliance — all ClickUp"
          subtitle="Closed tasks carrying the required taxonomy (Division / Customer Impact / Category)."
        />
        <SlackPulseCard
          title="Slack pulse — Inventory / Wholesale"
          subtitle="Operational Slack channels: inventory updates, retail/wholesale conversation."
          defaultChannelName="inventory-updates"
        />
        {/* Email archive pulse — leads with shipment/logistics escalations.
            Best operational signal we have until an ERP feed lands. */}
        <EmailPulseCard
          range={{
            startDate: new Date(Date.now() - 14 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10),
            endDate: new Date().toISOString().slice(0, 10),
          }}
          highlightArchetype="shipment_logistics"
        />
      </div>
    </>
  )
}
