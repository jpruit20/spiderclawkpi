import { ChatPanel } from '../components/ChatPanel'
import { BlockedDivisionPage } from '../components/BlockedDivisionPage'

export function ProductionManufacturingDivision() {
  return (
    <>
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
    <ChatPanel division="production-manufacturing" />
    </>
  )
}
