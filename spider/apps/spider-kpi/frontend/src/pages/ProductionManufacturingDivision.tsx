import { BlockedDivisionPage } from '../components/BlockedDivisionPage'
import { DivisionHero } from '../components/DivisionHero'
import { RecommendationsCard } from '../components/RecommendationsCard'
import { SharepointActivityCard } from '../components/SharepointActivityCard'
import { SharepointIntelligenceCard } from '../components/SharepointIntelligenceCard'
import { DivisionTargetsButton } from '../components/DivisionTargetsButton'

export function ProductionManufacturingDivision() {
  return (
    <>
      {/* ── DIVISION HERO — signature: stack ───────────────────────────
          Vertical stacked bars — the physical build pipeline. Stays in
          a muted "awaiting feed" state until manufacturing feeds go
          live; flips to real built/QC/shipped counts post-integration. */}
      <DivisionHero
        accentColor="#94a3b8"
        accentColorSoft="#64748b"
        signature="stack"
        title="Production / Manufacturing"
        subtitle="David's operating page — build pipeline, yield, defects, station bottlenecks. Awaiting manufacturing execution system feed."
        rightMeta={
          <div style={{ fontSize: 11, color: 'var(--muted)', textAlign: 'right' }}>
            <div>MES feed · <span style={{ color: 'var(--orange)' }}>blocked</span></div>
            <div>Quality feed · blocked</div>
          </div>
        }
        primary={{
          label: 'Built → QC pass → Shipped',
          value: '—',
          sublabel: 'source not connected',
          state: 'neutral',
          progress: 0.05,
          progressSecondary: 0.05,
          progressInner: 0.05,
          layers: [
            { label: 'Built', value: '—' },
            { label: 'QC pass', value: '—' },
            { label: 'Shipped', value: '—' },
          ],
        }}
        flanking={[
          { label: 'On-time production', value: '—', sublabel: 'needs MES', state: 'neutral' },
          { label: 'Defect rate', value: '—', sublabel: 'needs QA log', state: 'neutral' },
        ]}
        tiles={[
          { label: 'Output', value: '—', state: 'neutral' },
          { label: 'Yield', value: '—', state: 'neutral' },
          { label: 'Rework', value: '—', state: 'neutral' },
          { label: 'Downtime', value: '—', state: 'neutral' },
          { label: 'Escapes', value: '—', state: 'neutral' },
          { label: 'Bottlenecks', value: '—', state: 'neutral' },
        ]}
      />
      {/* Action recommendations specifically for Manufacturing now
          that we have real Production-and-QC document signal flowing
          through the engine. */}
      <RecommendationsCard division="manufacturing" />

      {/* SharePoint Production & QC activity — pulls from AMW's per-product
          sites' "Production and QC" folders. First real manufacturing
          data on this page; production output / yield / defect feeds
          remain blocked below until MES integration lands. */}
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <DivisionTargetsButton division="manufacturing" metrics={["orders", "tickets_created"]} label="Manufacturing targets" />
      </div>
      <SharepointIntelligenceCard division="manufacturing" />
      <SharepointActivityCard division="manufacturing" />

      <BlockedDivisionPage
        title="Production / Manufacturing"
        owner="David"
        summary="Output, defects, rework, yield, downtime, and station bottlenecks should be managed here once manufacturing data exists in a truthful form."
        blockedReason="This page is intentionally blocked from presenting manufacturing truth before line/shift/batch quality and output data are connected."
        readiness={[
          { label: 'Manufacturing output feed', status: 'blocked', detail: 'No live production output feed is connected to the KPI system.' },
          { label: 'Quality / defect feed', status: 'blocked', detail: 'Defect, rework, and escape reasons are not exposed yet.' },
          { label: 'Shift / line segmentation', status: 'blocked', detail: 'Line, station, and shift visibility do not exist in current KPI data.' },
        ]}
        requiredMetrics={[
          'Production output',
          'On-time production %',
          'Defect rate',
          'Rework rate',
          'Yield',
          'Downtime / bottlenecks',
        ]}
        sources={['Manufacturing execution system', 'Quality logs', 'Line/station downtime logs']}
        actions={[
          {
            title: 'Stand up manufacturing source-of-truth feed',
            owner: 'David',
            sla: 'Next integration phase',
            why: 'Without real line/shift/batch data, this page would encourage false certainty.',
            nextStep: 'Expose output, defect reasons, rework reasons, quality escapes, station bottlenecks, and line/shift/day rollups before promoting this page to full operator status.',
          },
        ]}
        drilldowns={[{ label: 'Open System Health', href: '/system-health' }]}
      />
    </>
  )
}
