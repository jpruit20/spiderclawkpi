import { ReactNode } from 'react'

/**
 * Page-top executive summary. Every division page should open with
 * one of these so the reader answers "what do I need to know RIGHT
 * NOW?" before scrolling.
 *
 * Structure:
 *   left column       : title, subtitle, narrative / status line
 *   right column      : quick-action controls (tabs, range picker)
 *   below the header  : headline KPIs (caller supplies)
 *   optional footer   : 1-3 "what to do next" call-to-actions
 *
 * Intentionally dense — this block should stay above the fold even on
 * laptop monitors.
 */
type Props = {
  title: ReactNode
  subtitle?: ReactNode
  status?: ReactNode                  // short sentence — "fleet healthy, 2 anomalies open"
  controls?: ReactNode                // tabs, date picker, filter
  kpiStrip?: ReactNode                // usually <VenomKpiStrip>
  cta?: ReactNode                     // 1-3 top actions (e.g. Link pills)
  accentColor?: string                // optional left-edge accent
}

export function PageHero({ title, subtitle, status, controls, kpiStrip, cta, accentColor }: Props) {
  return (
    <section
      className="card"
      style={{
        padding: '18px 22px',
        borderLeft: accentColor ? `4px solid ${accentColor}` : undefined,
        background: 'linear-gradient(180deg, rgba(255,255,255,0.02) 0%, rgba(255,255,255,0) 100%)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16, flexWrap: 'wrap', marginBottom: kpiStrip ? 14 : 0 }}>
        <div style={{ flex: 1, minWidth: 280 }}>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, lineHeight: 1.2 }}>{title}</h1>
          {subtitle && (
            <p style={{ margin: '4px 0 0', color: 'var(--muted)', fontSize: 13 }}>{subtitle}</p>
          )}
          {status && (
            <p style={{ margin: '10px 0 0', fontSize: 13, lineHeight: 1.55 }}>{status}</p>
          )}
        </div>
        {controls && (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            {controls}
          </div>
        )}
      </div>
      {kpiStrip}
      {cta && (
        <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid rgba(255,255,255,0.06)', display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }}>
          <span style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.4, marginRight: 6 }}>
            Next best actions
          </span>
          {cta}
        </div>
      )}
    </section>
  )
}
