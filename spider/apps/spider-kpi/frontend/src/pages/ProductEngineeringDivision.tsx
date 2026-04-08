import { BlockedDivisionPage } from '../components/BlockedDivisionPage'

export function ProductEngineeringDivision() {
  return (
    <BlockedDivisionPage
      title="Product / Engineering"
      owner="Kyle"
      summary="Telemetry-backed product reliability, continuation improvements, firmware risk, and feature behavior should live here once AWS / Venom is decision-grade."
      blockedReason="This page is intentionally blocked from pretending to know product truth before AWS / Venom telemetry is fully connected, persisted, and trustworthy enough for management decisions."
      readiness={[
        { label: 'Telemetry schema', status: 'partial', detail: 'Backend telemetry foundation exists, but production schema/source readiness is incomplete.' },
        { label: 'Live AWS / Venom source', status: 'blocked', detail: 'Real export / credentials / production sync not yet complete.' },
        { label: 'Issue correlation', status: 'partial', detail: 'Issue Radar can host telemetry later, but current signal is intentionally limited.' },
      ]}
      requiredMetrics={[
        'Cook success rate',
        'Disconnect rate',
        'Temp stability score',
        'Time to stabilization',
        'Firmware health score',
        'Manual override rate',
        'Session reliability score',
      ]}
      sources={['AWS telemetry', 'Venom telemetry', 'Issue Radar correlation', 'System Health']}
      actions={[
        {
          title: 'Finish telemetry source hookup',
          owner: 'Kyle',
          sla: 'This sprint',
          why: 'Without a real telemetry feed, product priorities would be anecdotal or fake-complete.',
          nextStep: 'Connect the real AWS / Venom export, validate schema on production, and expose only the metrics that are truthfully supported.',
        },
        {
          title: 'Gate product prioritization on trustworthy cohorts',
          owner: 'Kyle',
          sla: 'After telemetry hookup',
          why: 'Firmware/product/use-case cuts must exist before this page can drive continuation-improvement decisions.',
          nextStep: 'Add firmware, grill type, and cohort segmentation to the telemetry summary before promoting this page to full operator status.',
        },
      ]}
      drilldowns={[{ label: 'Open System Health', href: '/system-health' }, { label: 'Open Issue Radar', href: '/issues' }, { label: 'Open Root Cause', href: '/root-cause' }]}
    />
  )
}
