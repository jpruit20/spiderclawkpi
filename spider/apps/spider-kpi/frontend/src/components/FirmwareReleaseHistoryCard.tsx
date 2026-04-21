import { useEffect, useMemo, useState } from 'react'
import { ApiError, api } from '../lib/api'

type FirmwareRelease = {
  vendor?: string
  family?: string
  internal_version?: string | null
  shadow_version?: string | null
  release_candidate?: string | null
  production_release?: string | null
  ota_channel?: string | null
  ecr?: string | null
  release_date?: string | null
  notes?: string | null
}

type FirmwareBug = {
  id: string
  type?: string | null
  title?: string | null
  description?: string | null
  module?: string | null
  fw_found?: string | null
  priority?: string | null
  severity?: string | null
  status?: string | null
  opened_at?: string | null
  closed_at?: string | null
  fw_released?: string | null
  reporter?: string | null
}

type HistoryResponse = {
  releases: FirmwareRelease[]
  bugs: FirmwareBug[]
  error?: string
}

function fmtDate(d?: string | null): string {
  if (!d || d === 'None') return '—'
  const s = d.length >= 10 ? d.slice(0, 10) : d
  return s
}

function severityBadge(sev?: string | null): string {
  const s = (sev || '').toLowerCase()
  if (s.includes('critical') || s.includes('blocker')) return 'badge-bad'
  if (s.includes('major')) return 'badge-warn'
  if (s.includes('minor')) return 'badge-neutral'
  return 'badge-muted'
}

function statusBadge(st?: string | null): string {
  const s = (st || '').toLowerCase()
  if (s === 'done') return 'badge-good'
  if (s === 'new' || s === 'triaged') return 'badge-warn'
  if (s.includes('progress')) return 'badge-neutral'
  return 'badge-muted'
}

export function FirmwareReleaseHistoryCard() {
  const [data, setData] = useState<HistoryResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<'releases' | 'bugs'>('releases')
  const [familyFilter, setFamilyFilter] = useState<string>('')
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [expandedRelease, setExpandedRelease] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api.firmwareReleaseHistory()
      .then(r => { if (!cancelled) setData(r) })
      .catch(e => { if (!cancelled) setError(e instanceof ApiError ? e.message : 'Failed') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  const releases = useMemo(() => {
    if (!data) return []
    let r = data.releases
    if (familyFilter) r = r.filter(x => (x.family || '').includes(familyFilter))
    // Sort descending by date, then by version
    return [...r].sort((a, b) => {
      const ad = a.release_date || ''
      const bd = b.release_date || ''
      return bd.localeCompare(ad)
    })
  }, [data, familyFilter])

  const bugs = useMemo(() => {
    if (!data) return []
    let r = data.bugs
    if (statusFilter) r = r.filter(b => (b.status || '') === statusFilter)
    return [...r].sort((a, b) => (b.opened_at || '').localeCompare(a.opened_at || ''))
  }, [data, statusFilter])

  if (loading) return <section className="card"><div className="state-message">Loading firmware history…</div></section>
  if (error) return <section className="card"><div className="state-message" style={{ color: 'var(--red)' }}>Error: {error}</div></section>
  if (!data) return null

  return (
    <section className="card">
      <div className="venom-panel-head">
        <div>
          <strong>Firmware release history</strong>
          <p className="venom-chart-sub">
            Full archive of every Venom firmware release ({data.releases.length} versions across V1 and V2)
            plus the V2 bug tracker ({data.bugs.length} items). Sourced from the QA team's tracking sheets.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 4, background: 'var(--panel-2)', borderRadius: 6, padding: 2 }}>
          <button
            className={`range-button${tab === 'releases' ? ' active' : ''}`}
            onClick={() => setTab('releases')}
          >Releases ({data.releases.length})</button>
          <button
            className={`range-button${tab === 'bugs' ? ' active' : ''}`}
            onClick={() => setTab('bugs')}
          >Bugs ({data.bugs.length})</button>
        </div>
      </div>

      {tab === 'releases' ? (
        <>
          <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap', fontSize: 12 }}>
            <button onClick={() => setFamilyFilter('')} className={`badge ${familyFilter === '' ? 'badge-good' : 'badge-muted'}`}>All ({data.releases.length})</button>
            <button onClick={() => setFamilyFilter('V2')} className={`badge ${familyFilter === 'V2' ? 'badge-good' : 'badge-muted'}`}>V2 (ADN)</button>
            <button onClick={() => setFamilyFilter('V1')} className={`badge ${familyFilter === 'V1' ? 'badge-good' : 'badge-muted'}`}>V1 (legacy)</button>
          </div>
          <div style={{ marginTop: 10, overflowX: 'auto' }}>
            <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse', minWidth: 820 }}>
              <thead>
                <tr style={{ textAlign: 'left', color: 'var(--muted)' }}>
                  <th style={{ padding: '6px 8px' }}>Family</th>
                  <th>Version</th>
                  <th>Shadow / RC</th>
                  <th>OTA</th>
                  <th>Date</th>
                  <th>Notes</th>
                </tr>
              </thead>
              <tbody>
                {releases.map((r, i) => {
                  const key = `${r.family}:${r.internal_version}:${r.release_candidate}:${i}`
                  const isOpen = expandedRelease === key
                  const shortNotes = (r.notes || '').split('\n')[0].slice(0, 100)
                  return (
                    <tr
                      key={key}
                      onClick={() => setExpandedRelease(isOpen ? null : key)}
                      style={{ borderTop: '1px solid var(--border)', cursor: 'pointer' }}
                    >
                      <td style={{ padding: '6px 8px' }}>
                        <span className={`badge ${r.family?.includes('V2') ? 'badge-good' : 'badge-neutral'}`} style={{ fontSize: 10 }}>
                          {r.family || '?'}
                        </span>
                      </td>
                      <td style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11 }}>{r.internal_version || '—'}</td>
                      <td style={{ fontSize: 11, color: 'var(--muted)' }}>
                        {r.shadow_version || r.release_candidate || '—'}
                      </td>
                      <td style={{ fontSize: 11, color: 'var(--muted)' }}>{r.ota_channel || '—'}</td>
                      <td style={{ fontSize: 11 }}>{fmtDate(r.release_date)}</td>
                      <td style={{ fontSize: 11 }}>
                        {isOpen ? (
                          <pre style={{ whiteSpace: 'pre-wrap', margin: 0, fontFamily: 'inherit' }}>{r.notes || '(no notes)'}</pre>
                        ) : (
                          <span style={{ color: 'var(--muted)' }}>{shortNotes}{(r.notes?.length ?? 0) > 100 ? ' … (click row)' : ''}</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <>
          <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap', fontSize: 12 }}>
            <button onClick={() => setStatusFilter('')} className={`badge ${statusFilter === '' ? 'badge-good' : 'badge-muted'}`}>All ({data.bugs.length})</button>
            <button onClick={() => setStatusFilter('New')} className={`badge ${statusFilter === 'New' ? 'badge-good' : 'badge-muted'}`}>New</button>
            <button onClick={() => setStatusFilter('Done')} className={`badge ${statusFilter === 'Done' ? 'badge-good' : 'badge-muted'}`}>Done</button>
          </div>
          <div style={{ marginTop: 10, overflowX: 'auto' }}>
            <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse', minWidth: 900 }}>
              <thead>
                <tr style={{ textAlign: 'left', color: 'var(--muted)' }}>
                  <th style={{ padding: '6px 8px' }}>ID</th>
                  <th>Type</th>
                  <th>Title</th>
                  <th>Module</th>
                  <th>Found / Fixed</th>
                  <th>Severity</th>
                  <th>Status</th>
                  <th>Opened</th>
                </tr>
              </thead>
              <tbody>
                {bugs.map(b => (
                  <tr key={b.id} style={{ borderTop: '1px solid var(--border)' }}>
                    <td style={{ padding: '6px 8px', fontFamily: 'ui-monospace, monospace', fontSize: 11 }}>{b.id}</td>
                    <td style={{ fontSize: 11 }}>{b.type || '—'}</td>
                    <td style={{ fontSize: 12 }} title={b.description || undefined}>
                      {b.title || '—'}
                    </td>
                    <td style={{ fontSize: 11, color: 'var(--muted)' }}>{b.module || '—'}</td>
                    <td style={{ fontSize: 11 }}>
                      {b.fw_found || '?'} {b.fw_released ? <span style={{ color: 'var(--muted)' }}>→ {b.fw_released}</span> : null}
                    </td>
                    <td><span className={`badge ${severityBadge(b.severity)}`} style={{ fontSize: 10 }}>{b.severity || '—'}</span></td>
                    <td><span className={`badge ${statusBadge(b.status)}`} style={{ fontSize: 10 }}>{b.status || '—'}</span></td>
                    <td style={{ fontSize: 11 }}>{fmtDate(b.opened_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  )
}
