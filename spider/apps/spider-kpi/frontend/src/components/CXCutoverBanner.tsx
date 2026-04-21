import type { CXCutoverInfo } from '../lib/types'

/**
 * CX operations cutover banner.
 *
 * Before the cutover date (2026-05-01): amber "reset coming" banner
 * telling the team when the new rules start. Pre-cutover operational
 * metrics are shown as-is, but framed honestly — the 9k+ "open backlog"
 * is a Freshdesk artifact, not real work.
 *
 * On/after the cutover date: green "data since YYYY-MM-DD" badge,
 * making it obvious that operational KPIs only cover forward activity.
 */
export function CXCutoverBanner({ cutover }: { cutover?: CXCutoverInfo | null }) {
  if (!cutover || !cutover.date) return null
  const d = cutover.date

  if (!cutover.active) {
    const daysUntil = cutover.days_until
    const whenLabel = daysUntil <= 0
      ? 'today'
      : daysUntil === 1
        ? 'tomorrow'
        : `in ${daysUntil} days`
    return (
      <section
        className="card"
        style={{
          borderLeft: '3px solid var(--orange)',
          padding: '10px 14px',
          background: 'rgba(245, 158, 11, 0.06)',
        }}
      >
        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', flexWrap: 'wrap' }}>
          <span style={{ fontSize: 18 }}>🚧</span>
          <div style={{ flex: 1, minWidth: 280 }}>
            <div style={{ fontWeight: 600, fontSize: 13 }}>
              CX operations reset — live on {d} ({whenLabel})
            </div>
            <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4, lineHeight: 1.5 }}>
              Team is transitioning to new rules: close tickets on resolution,
              follow SLA, tag consistently. Metrics below reflect the legacy
              operating model — the 9k+ "open backlog" is mostly closed in
              reality but never clicked Resolved. On <strong>{d}</strong> the
              pre-cutover ghost backlog gets retro-closed and this dashboard
              switches to a forward-looking view. Pre-cutover data stays
              searchable as historical reference.
            </div>
          </div>
        </div>
      </section>
    )
  }

  return (
    <section
      className="card"
      style={{
        borderLeft: '3px solid var(--green)',
        padding: '8px 14px',
        background: 'rgba(34, 197, 94, 0.05)',
      }}
    >
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', fontSize: 12 }}>
        <span style={{ fontSize: 15 }}>✓</span>
        <strong>CX operational data since {d}.</strong>
        <span style={{ color: 'var(--muted)' }}>
          Pre-cutover tickets live in the historical reference section
          below — not compared against current team performance.
        </span>
      </div>
    </section>
  )
}
