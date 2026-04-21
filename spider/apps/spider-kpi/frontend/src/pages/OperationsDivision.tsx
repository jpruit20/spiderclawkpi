import { BlockedDivisionPage } from '../components/BlockedDivisionPage'
import { ClickUpComplianceCard } from '../components/ClickUpComplianceCard'
import { ClickUpTasksCard } from '../components/ClickUpTasksCard'
import { ClickUpVelocityCard } from '../components/ClickUpVelocityCard'
import { SlackPulseCard } from '../components/SlackPulseCard'
import { EmailPulseCard } from '../components/EmailPulseCard'
import { Link } from 'react-router-dom'

const KETTLE_CART_BANNER_EXPIRES_AT = Date.parse('2026-04-22T03:00:00Z')

function KettleCartRequestBanner() {
  if (Date.now() > KETTLE_CART_BANNER_EXPIRES_AT) return null
  return (
    <section
      className="card"
      style={{
        marginBottom: 12,
        borderLeft: '4px solid var(--green, #10b981)',
        background: 'rgba(16, 185, 129, 0.06)',
      }}
    >
      <div className="venom-panel-head">
        <strong>✅ Request approved & deployed — for Conor</strong>
        <span className="venom-panel-hint">Auto-hides {new Date(KETTLE_CART_BANNER_EXPIRES_AT).toLocaleString()}</span>
      </div>
      <div style={{ fontSize: 13, lineHeight: 1.5 }}>
        Your request — <em>"Can you look through customer service tickets and social media posts and
        comments to figure out how many people have complaints about the 22&quot; Kettle Cart product?"</em> —
        is live on the{' '}
        <Link to="/division/customer-experience" style={{ color: 'var(--orange)', textDecoration: 'underline' }}>
          Customer Experience page
        </Link>
        {' '}as the <strong>Product complaint search</strong> card (defaulted to Kettle Cart).
      </div>
      <ul style={{ fontSize: 12, color: 'var(--muted)', marginTop: 8, paddingLeft: 20, lineHeight: 1.6 }}>
        <li><strong>Freshdesk:</strong> full 5-year archive (9,370 tickets) now searchable — subject, description, and conversation bodies. ~150 Kettle Cart mentions already indexed; conversation backfill still completing.</li>
        <li><strong>Social / reviews / community:</strong> search is wired, but most feeds (Reddit, Facebook, Google Reviews, Shopify product reviews) need credentials before they return data. YouTube + Amazon are live but show 0 Kettle Cart hits so far.</li>
        <li>Follow-ups in flight: (1) Jeremiah to add "Kettle Cart" to the Freshdesk accessory dropdown; (2) enabling the stubbed social connectors will broaden the signal.</li>
      </ul>
    </section>
  )
}

export function OperationsDivision() {
  return (
    <>
      <KettleCartRequestBanner />
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
