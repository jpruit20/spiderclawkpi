import { useEffect, useState } from 'react'

/**
 * CommandCenter morning briefing.
 *
 * Aggregates the top recommendations from every division into one
 * card so Joseph's first scroll of the day shows him what's most
 * urgent across the whole business in 30 seconds. Each item carries
 * a division pill so it's clear who owns the action.
 *
 * If no division has any recommendations, the card collapses to a
 * single green "all clear, calm morning" line.
 */

type Severity = 'critical' | 'warn' | 'info'

interface FlatItem {
  division: string
  title: string
  severity: Severity
  evidence: string
  action: string
  impact: string
  key: string
}

interface Brief {
  generated_at: string
  total_actions: number
  shown: number
  flat: FlatItem[]
}

const SEVERITY_COLOR: Record<Severity, string> = {
  critical: 'var(--red)',
  warn: 'var(--orange)',
  info: 'var(--blue)',
}

const DIVISION_LABEL: Record<string, string> = {
  pe: 'Product',
  cx: 'CX',
  marketing: 'Marketing',
  operations: 'Ops',
  firmware: 'Firmware',
}

const DIVISION_LINK: Record<string, string> = {
  pe: '/divisions/product-engineering',
  cx: '/divisions/customer-experience',
  marketing: '/divisions/marketing',
  operations: '/divisions/operations',
  firmware: '/firmware',
}

export function MorningBriefingCard() {
  const [data, setData] = useState<Brief | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const ctl = new AbortController()
    fetch('/api/recommendations/all/morning-brief', { signal: ctl.signal, credentials: 'include' })
      .then(async r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(d => setData(d as Brief))
      .catch(err => { if (err.name !== 'AbortError') setError(String(err.message || err)) })
    return () => ctl.abort()
  }, [])

  if (error) {
    return (
      <section className="card" style={{ borderLeft: '3px solid var(--muted)' }}>
        <div style={{ fontSize: 11, color: 'var(--muted)' }}>
          Morning briefing unavailable: {error}
        </div>
      </section>
    )
  }
  if (!data) {
    return (
      <section className="card" style={{ borderLeft: '3px solid var(--muted)' }}>
        <div style={{ fontSize: 11, color: 'var(--muted)' }}>Loading morning briefing…</div>
      </section>
    )
  }

  if (data.flat.length === 0) {
    return (
      <section className="card" style={{ borderLeft: '3px solid var(--green)', padding: '12px 16px' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
          <strong style={{ color: 'var(--green)', fontSize: 14 }}>✓ Calm morning.</strong>
          <span style={{ color: 'var(--muted)' }}>
            No prioritized actions across any division right now. Use the time to ship something nice.
          </span>
        </div>
      </section>
    )
  }

  const topSeverity = data.flat[0]?.severity ?? 'info'

  return (
    <section className="card" style={{ borderLeft: `3px solid ${SEVERITY_COLOR[topSeverity]}` }}>
      <div className="venom-panel-head" style={{ alignItems: 'flex-start' }}>
        <div>
          <strong>Morning briefing</strong>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            {data.total_actions} prioritized action{data.total_actions === 1 ? '' : 's'} across all divisions. Most urgent first.
          </div>
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 12 }}>
        {data.flat.map(r => (
          <a
            key={r.key}
            href={DIVISION_LINK[r.division] ?? '#'}
            style={{
              display: 'block',
              padding: 10,
              background: 'var(--panel-2)',
              borderRadius: 6,
              borderLeft: `3px solid ${SEVERITY_COLOR[r.severity]}`,
              textDecoration: 'none',
              color: 'var(--text)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <span style={{
                fontSize: 9,
                fontWeight: 700,
                letterSpacing: 1,
                padding: '2px 6px',
                borderRadius: 3,
                background: 'var(--panel)',
                color: SEVERITY_COLOR[r.severity],
              }}>
                {r.severity.toUpperCase()}
              </span>
              <span style={{
                fontSize: 9,
                fontWeight: 700,
                letterSpacing: 1,
                color: 'var(--muted)',
                textTransform: 'uppercase',
              }}>
                {DIVISION_LABEL[r.division] ?? r.division}
              </span>
              <strong style={{ fontSize: 13, flex: 1 }}>{r.title}</strong>
            </div>
            <div style={{ fontSize: 12, marginTop: 4, color: 'var(--muted)' }}>
              <strong style={{ color: 'var(--text)' }}>Action:</strong> {r.action}
            </div>
          </a>
        ))}
      </div>
    </section>
  )
}
