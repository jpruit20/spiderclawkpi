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
import { ShippingCostBySkuCard } from '../components/ShippingCostBySkuCard'
import { FedexReconciliationCard } from '../components/FedexReconciliationCard'
import { VendorWorkspaceCard } from '../components/VendorWorkspaceCard'
import { DivisionTargetsButton } from '../components/DivisionTargetsButton'
import { OrderAgingCard } from '../components/OrderAgingCard'
import { CustomizableCard } from '../components/CustomizableCard'
import { CollapsibleSection } from '../components/CollapsibleSection'
import { DivisionPageHeader } from '../components/DivisionPageHeader'
import { usePageConfig } from '../lib/usePageConfig'
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
      <details style={{ marginTop: 8 }}>
        <summary style={{ fontSize: 12, color: 'var(--muted)', cursor: 'pointer' }}>What changed under the hood</summary>
        <ul style={{ fontSize: 12, color: 'var(--muted)', marginTop: 6, paddingLeft: 20, lineHeight: 1.6 }}>
          <li><strong>Shopify sync</strong> now captures <code>fulfillment_status</code>, <code>tags</code>, and <code>fulfillments</code> — the missing fields that previously made aging impossible.</li>
          <li><strong>Backfill</strong>: I ran a one-shot <code>sync-unfulfilled</code> on the droplet — 113 currently-unfulfilled orders pulled ($181K open, 72 orders &gt;7d old). You'll see those right away.</li>
          <li><strong>Owner-only</strong> "Refresh from Shopify" button on the aging card pulls the latest queue on demand; the regular poll keeps it fresh between clicks.</li>
          <li><strong>Trend reconstruction</strong>: counts per day are rebuilt from per-order snapshot state (created_at, first_fulfilled_at, cancelled_at). Days before we started capturing fulfillment fields are under-counted by design — older orders trickle in on normal poll cadence.</li>
        </ul>
      </details>
    </section>
  )
}

export function OperationsDivision() {
  const cfg = usePageConfig('operations')
  return (
    <>
      <OrderAgingRequestBanner />
      <DivisionPageHeader cfg={cfg} divisionLabel="Operations · Conor" />
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
      <CustomizableCard
        id="recommendations" defaultTitle="Recommendations" cfg={cfg}
        collapsible defaultOpen
        subtitle="AI-generated action items for Operations"
      >
        <RecommendationsCard division="operations" />
      </CustomizableCard>

      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <DivisionTargetsButton division="operations" metrics={["orders", "tickets_created"]} label="Operations targets" />
      </div>

      <CustomizableCard
        id="shipping_intelligence" defaultTitle="Shipping intelligence" cfg={cfg}
        collapsible defaultOpen
        subtitle="Carrier mix, transit times, geographic distribution, 3PL ROI"
      >
        <ShippingIntelligenceCard defaultDays={90} showCxCorrelation />
      </CustomizableCard>

      {/* Shipping cost drill-down: per-SKU spend, carrier mix per SKU,
          and per-carrier trend over time. Folded by default since the
          parent shipping card already covers carrier mix headline. */}
      <CustomizableCard
        id="shipping_cost_by_sku" defaultTitle="Shipping cost by SKU" cfg={cfg}
        collapsible defaultOpen={false}
        subtitle="Per-SKU shipping spend · carrier mix · trend"
      >
        <ShippingCostBySkuCard />
      </CustomizableCard>

      {/* FedEx rate cross-check / contract-savings reconciliation card. */}
      <CustomizableCard
        id="fedex_reconciliation" defaultTitle="FedEx rate reconciliation" cfg={cfg}
        collapsible defaultOpen
        subtitle="ShipStation est vs Rate-API quote vs invoice (truth)"
      >
        <FedexReconciliationCard />
      </CustomizableCard>

      {/* Vendor inbound — Kienco + Qifei SharePoint. The card itself
          uses CollapsibleSection internally (with rich preview), so
          we skip the outer collapsible wrapper to avoid double-nesting. */}
      <CustomizableCard id="vendor_workspace" defaultTitle="Vendor inbound (Kienco · Qifei)" cfg={cfg}>
        <VendorWorkspaceCard />
      </CustomizableCard>

      <CustomizableCard
        id="sharepoint_intelligence" defaultTitle="SharePoint intelligence" cfg={cfg}
        collapsible defaultOpen={false}
        subtitle="Per-product engineering folder activity"
      >
        <SharepointIntelligenceCard division="operations" />
      </CustomizableCard>

      {/* SharePoint activity feed — long per-file activity list, folded
          by default so the Ops landing isn't dominated by it. */}
      <CustomizableCard
        id="sharepoint_activity" defaultTitle="SharePoint activity feed" cfg={cfg}
        collapsible defaultOpen={false}
        subtitle="Per-file activity from AMW SharePoint folders"
      >
        <SharepointActivityCard division="operations" />
      </CustomizableCard>

      <CustomizableCard
        id="order_aging" defaultTitle="Order fulfillment aging" cfg={cfg}
        collapsible defaultOpen
        subtitle="0–1d / 1–3d / 3–7d / 7d+ buckets · 14-day trend"
      >
        <OrderAgingCard variant="full" trendDays={14} />
      </CustomizableCard>
      <CollapsibleSection
        id="ops-page-gated"
        title="Why this page is gated"
        subtitle="Required ERP feeds, sources, and the integration plan"
        density="compact"
      >
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
      </CollapsibleSection>
      <div className="page-grid" style={{ marginTop: 16 }}>
        <CustomizableCard
          id="clickup_tasks" defaultTitle="ClickUp tasks — Operations" cfg={cfg}
          collapsible defaultOpen={false}
          subtitle="Operational ClickUp tasks (filter narrows as tags improve)"
        >
          <ClickUpTasksCard
            title={cfg.cardTitle('clickup_tasks', 'ClickUp tasks — Operations')}
            subtitle="Tasks from ClickUp that look operational (filter narrows as you tag / organize)."
            defaultFilter={{ limit: 30 }}
          />
        </CustomizableCard>
        <CustomizableCard
          id="clickup_velocity" defaultTitle="Team velocity — all ClickUp" cfg={cfg}
          collapsible defaultOpen={false}
          subtitle="Throughput + cycle time across spaces"
        >
          <ClickUpVelocityCard
            title={cfg.cardTitle('clickup_velocity', 'Team velocity — all ClickUp')}
            subtitle="Throughput + cycle time across every space until an Ops space is stood up."
          />
        </CustomizableCard>
        <CustomizableCard
          id="clickup_compliance" defaultTitle="Tagging compliance — all ClickUp" cfg={cfg}
          collapsible defaultOpen={false}
          subtitle="Closed tasks carrying the required taxonomy"
        >
          <ClickUpComplianceCard
            title={cfg.cardTitle('clickup_compliance', 'Tagging compliance — all ClickUp')}
            subtitle="Closed tasks carrying the required taxonomy (Division / Customer Impact / Category)."
          />
        </CustomizableCard>
        <CustomizableCard
          id="slack_pulse" defaultTitle="Slack pulse — Inventory / Wholesale" cfg={cfg}
          collapsible defaultOpen={false}
          subtitle="Operational Slack channels: inventory + retail/wholesale"
        >
          <SlackPulseCard
            title={cfg.cardTitle('slack_pulse', 'Slack pulse — Inventory / Wholesale')}
            subtitle="Operational Slack channels: inventory updates, retail/wholesale conversation."
            defaultChannelName="inventory-updates"
          />
        </CustomizableCard>
        <CustomizableCard
          id="email_pulse" defaultTitle="Email pulse — shipment / logistics" cfg={cfg}
          collapsible defaultOpen={false}
          subtitle="14-day email volume across shipment / logistics threads"
        >
          <EmailPulseCard
            range={{
              startDate: new Date(Date.now() - 14 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10),
              endDate: new Date().toISOString().slice(0, 10),
            }}
            highlightArchetype="shipment_logistics"
          />
        </CustomizableCard>
      </div>
    </>
  )
}
