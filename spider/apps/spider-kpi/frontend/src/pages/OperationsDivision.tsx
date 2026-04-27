import { BlockedDivisionPage } from '../components/BlockedDivisionPage'
import { ClickUpComplianceCard } from '../components/ClickUpComplianceCard'
import { ClickUpTasksCard } from '../components/ClickUpTasksCard'
import { ClickUpVelocityCard } from '../components/ClickUpVelocityCard'
import { SlackPulseCard } from '../components/SlackPulseCard'
import { EmailPulseCard } from '../components/EmailPulseCard'
import { DivisionHero } from '../components/DivisionHero'
import { RecommendationsCard } from '../components/RecommendationsCard'
import { SharepointActivityCard } from '../components/SharepointActivityCard'
import { SharepointIntelligenceCard } from '../components/SharepointIntelligenceCard'
import { ShippingIntelligenceCard } from '../components/ShippingIntelligenceCard'
import { OrderAgingCard } from '../components/OrderAgingCard'
import { Link } from 'react-router-dom'

// 24h auto-expire. New requester-facing builds should replace this
// banner with their own short-lived note so the person who asked for
// the change sees it got done.
const ORDER_AGING_BANNER_EXPIRES_AT = Date.parse('2026-04-22T22:15:00Z')

function OrderAgingRequestBanner() {
  if (Date.now() > ORDER_AGING_BANNER_EXPIRES_AT) return null
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
        <strong>✅ Request deployed — for Conor</strong>
        <span className="venom-panel-hint">Auto-hides {new Date(ORDER_AGING_BANNER_EXPIRES_AT).toLocaleString()}</span>
      </div>
      <div style={{ fontSize: 13, lineHeight: 1.5 }}>
        Your ask — <em>"let's pull in order aging data from Shopify"</em> — is live below as the{' '}
        <strong>Order fulfillment aging</strong> card. It bucketes currently-unfulfilled Shopify orders
        into 0–1d / 1–3d / 3–7d / 7d+ and renders a stacked trend for the last 14 days. A compact
        version also sits on the{' '}
        <Link to="/division/customer-experience" style={{ color: 'var(--orange)', textDecoration: 'underline' }}>
          Customer Experience page
        </Link>
        {' '}under WISMO so the team can correlate shipping aging with ticket volume.
      </div>
      <ul style={{ fontSize: 12, color: 'var(--muted)', marginTop: 8, paddingLeft: 20, lineHeight: 1.6 }}>
        <li><strong>Shopify sync</strong> now captures <code>fulfillment_status</code>, <code>tags</code>, and <code>fulfillments</code> — the missing fields that previously made aging impossible.</li>
        <li><strong>Backfill</strong>: I ran a one-shot <code>sync-unfulfilled</code> on the droplet — 113 currently-unfulfilled orders pulled ($181K open, 72 orders &gt;7d old). You'll see those right away.</li>
        <li><strong>Owner-only</strong> "Refresh from Shopify" button on the aging card pulls the latest queue on demand; the regular poll keeps it fresh between clicks.</li>
        <li><strong>Trend reconstruction</strong>: counts per day are rebuilt from per-order snapshot state (created_at, first_fulfilled_at, cancelled_at). Days before we started capturing fulfillment fields are under-counted by design — older orders trickle in on normal poll cadence.</li>
      </ul>
    </section>
  )
}

export function OperationsDivision() {
  return (
    <>
      <OrderAgingRequestBanner />
      {/* ── DIVISION HERO — signature: throughput ─────────────────────
          Horizontal flow bar with animated shimmer. Stays in a muted
          "awaiting feed" state until Business Central is live;
          becomes a live operational cockpit post-integration. */}
      <DivisionHero
        accentColor="#6ea8ff"
        accentColorSoft="#39d08f"
        signature="throughput"
        title="Operations Division"
        subtitle="Conor's operating page — order throughput, aging, exceptions. Awaiting Business Central to go live-decision-grade."
        rightMeta={
          <div style={{ fontSize: 11, color: 'var(--muted)', textAlign: 'right' }}>
            <div>ERP feed · <span style={{ color: 'var(--orange)' }}>blocked</span></div>
            <div>ClickUp · live</div>
          </div>
        }
        primary={{
          label: 'Order throughput — awaiting ERP feed',
          value: '—',
          sublabel: 'Business Central integration pending',
          state: 'neutral',
          progress: 0,
          layers: [{ label: 'Stage', value: 'Source not connected' }],
        }}
        flanking={[
          {
            label: 'Open tasks (ClickUp)',
            value: '—',
            sublabel: 'live feed below',
            state: 'neutral',
          },
          {
            label: 'Late-ship exposure',
            value: '—',
            sublabel: 'needs ERP truth',
            state: 'neutral',
          },
        ]}
        tiles={[
          { label: 'Order throughput', value: '—', state: 'neutral' },
          { label: 'Fulfillment speed', value: '—', state: 'neutral' },
          { label: 'Aged orders', value: '—', state: 'neutral' },
          { label: 'Inventory bottlenecks', value: '—', state: 'neutral' },
          { label: 'Exception volume', value: '—', state: 'neutral' },
          { label: 'Late-ship reasons', value: '—', state: 'neutral' },
        ]}
      />
      {/* Top-of-page actionable recommendations. */}
      <RecommendationsCard division="operations" />

      {/* SharePoint Project Management activity — POs, quotations,
          master trackers, vendor specs from AMW's per-product
          sites. */}
      <ShippingIntelligenceCard defaultDays={90} showCxCorrelation />
      <SharepointIntelligenceCard division="operations" />
      <SharepointActivityCard division="operations" />

      {/* Order aging — Conor's 2026-04-21 ask. Lives here as a real ops
          KPI while the broader BC/ERP integration is still pending.
          Also rendered compact on the CX page for WISMO correlation. */}
      <OrderAgingCard variant="full" trendDays={14} />
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
