import { useEffect, useState } from 'react'
import { ApiError, api } from '../lib/api'
import { CookTimelineChart } from './CookTimelineChart'

type DiagnosticEvent = {
  id: number
  event_type: string
  severity: string
  mac: string | null
  device_id: string | null
  user_id: string | null
  firmware_version: string | null
  app_version: string | null
  platform: string | null
  title: string | null
  details: Record<string, unknown>
  created_at: string | null
  resolved_at: string | null
  resolved_by: string | null
  resolution_note: string | null
}

type DiagnosticsResponse = {
  window_days: number
  total_in_window: number
  total_open: number
  by_type: Record<string, number>
  by_severity: Record<string, number>
  events: DiagnosticEvent[]
}

function fmtWhen(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  const diffMin = Math.round((Date.now() - d.getTime()) / 60000)
  if (diffMin < 60) return `${diffMin}m ago`
  if (diffMin < 1440) return `${Math.round(diffMin / 60)}h ago`
  return `${Math.round(diffMin / 1440)}d ago`
}

function sevClass(sev: string): string {
  if (sev === 'critical') return 'badge-bad'
  if (sev === 'error') return 'badge-bad'
  if (sev === 'warning') return 'badge-warn'
  return 'badge-neutral'
}

export function DiagnosticsCard() {
  const [data, setData] = useState<DiagnosticsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [includeResolved, setIncludeResolved] = useState(false)
  const [severityFilter, setSeverityFilter] = useState<string>('')
  const [focusedMac, setFocusedMac] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    api.diagnosticsEvents({
      days: 7,
      severity: severityFilter || undefined,
      includeResolved,
    })
      .then(r => { setData(r); setError(null) })
      .catch(e => setError(e instanceof ApiError ? e.message : 'Failed'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
    const t = window.setInterval(load, 30_000)
    return () => window.clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [severityFilter, includeResolved])

  const handleResolve = async (id: number) => {
    const note = prompt('Resolution note (optional):') ?? undefined
    try {
      await api.diagnosticsResolve(id, note)
      load()
    } catch (e) {
      alert(e instanceof ApiError ? e.message : 'Failed to resolve')
    }
  }

  if (loading && !data) return <section className="card"><div className="state-message">Loading diagnostics…</div></section>
  if (error && !data) return <section className="card"><div className="state-message" style={{ color: 'var(--red)' }}>Error: {error}</div></section>
  if (!data) return null

  return (
    <section className="card" style={{ borderLeft: '3px solid #3b82f6' }}>
      <div className="venom-panel-head">
        <div>
          <strong>Diagnostic events — in-app</strong>
          <p className="venom-chart-sub">
            Background events emitted by the Venom app (WiFi fails, controller errors, sensor faults).
            These used to land as [AUTOMATED] Freshdesk tickets and clutter the human queue — now they live here.
          </p>
        </div>
        <span className="venom-panel-hint">
          {data.total_open} open · {data.total_in_window} total in last {data.window_days}d
        </span>
      </div>

      <div className="venom-kpi-strip" style={{ marginTop: 10, marginBottom: 12 }}>
        {Object.entries(data.by_severity).map(([sev, n]) => (
          <div className="venom-kpi-card" key={sev} style={{ cursor: 'pointer', borderColor: severityFilter === sev ? 'var(--orange)' : 'var(--border)' }}
               onClick={() => setSeverityFilter(severityFilter === sev ? '' : sev)}>
            <div className="venom-kpi-label">{sev}</div>
            <div className="venom-kpi-value">{n}</div>
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap', alignItems: 'center', fontSize: 12 }}>
        <label style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <input type="checkbox" checked={includeResolved} onChange={e => setIncludeResolved(e.target.checked)} />
          <span>Include resolved</span>
        </label>
        {severityFilter ? (
          <button onClick={() => setSeverityFilter('')} className="badge badge-muted" style={{ fontSize: 10 }}>
            Clear filter: {severityFilter} ×
          </button>
        ) : null}
        <div style={{ marginLeft: 'auto', color: 'var(--muted)', fontSize: 11 }}>
          By type: {Object.entries(data.by_type).slice(0, 6).map(([t, n]) => `${t} (${n})`).join(' · ') || 'no events'}
        </div>
      </div>

      {data.events.length === 0 ? (
        <div className="state-message">No events in window.</div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse', minWidth: 820 }}>
            <thead>
              <tr style={{ textAlign: 'left', color: 'var(--muted)' }}>
                <th style={{ padding: '6px 8px' }}>When</th>
                <th>Severity</th>
                <th>Type</th>
                <th>Title</th>
                <th>MAC</th>
                <th>FW</th>
                <th>App</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {data.events.map(e => (
                <tr key={e.id} style={{ borderTop: '1px solid var(--border)', opacity: e.resolved_at ? 0.55 : 1 }}>
                  <td style={{ padding: '6px 8px' }} title={e.created_at ?? undefined}>{fmtWhen(e.created_at)}</td>
                  <td><span className={`badge ${sevClass(e.severity)}`} style={{ fontSize: 10 }}>{e.severity}</span></td>
                  <td style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11 }}>{e.event_type}</td>
                  <td title={e.title ?? undefined}>{(e.title || '').slice(0, 60) || <span style={{ color: 'var(--muted)' }}>—</span>}</td>
                  <td style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11, cursor: e.mac ? 'pointer' : 'default' }}
                      onClick={() => e.mac && setFocusedMac(e.mac)}
                      title={e.mac ? 'Click for cook timeline' : undefined}>
                    {e.mac || '—'}
                  </td>
                  <td style={{ fontSize: 11 }}>{e.firmware_version || '—'}</td>
                  <td style={{ fontSize: 11 }}>{e.app_version || '—'}</td>
                  <td style={{ textAlign: 'right' }}>
                    {!e.resolved_at ? (
                      <button onClick={() => handleResolve(e.id)} style={{ fontSize: 10, padding: '2px 8px' }}>
                        Resolve
                      </button>
                    ) : (
                      <span style={{ fontSize: 10, color: 'var(--muted)' }} title={e.resolution_note ?? undefined}>
                        ✓ {e.resolved_by ?? 'resolved'}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {focusedMac ? (
        <CookTimelineChart mac={focusedMac} lookbackHours={24} modal onClose={() => setFocusedMac(null)} />
      ) : null}
    </section>
  )
}
