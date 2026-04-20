import { useEffect, useMemo, useRef, useState } from 'react'

import { api, ApiError } from '../lib/api'
import type { LoreEvent, LoreEventStats, LoreConfidence } from '../lib/types'

/**
 * Lore Ledger — the review/curation surface for the company-lore corpus.
 *
 * Phase 1 piece 3 of the company-lore surface. The Opus seed pass dropped
 * ~474 events (2023-2026) at `inferred` / `rumored` confidence; this page
 * exists so Joseph can promote credible events to `confirmed`, sweep
 * noise, and keep the ledger trustworthy before it feeds the anomaly
 * narrative, AI insights, and the morning brief.
 *
 * Surface:
 *   - Header: full-corpus stats (total + by confidence + by type + by division)
 *   - Filter row: year, event_type, confidence, division, free-text search
 *   - Results: checkbox-selectable rows with inline edit
 *   - Bulk action bar (only visible when ≥1 row is selected):
 *       Confidence: (upgrade) to confirmed / (downgrade) to rumored
 *       Event type: reassign
 *       Division: reassign
 *       Delete
 */

const EVENT_TYPES = [
  'launch', 'incident', 'campaign', 'promotion', 'firmware',
  'hardware_revision', 'personnel', 'press', 'external', 'holiday', 'other',
]

const CONFIDENCES: LoreConfidence[] = ['confirmed', 'inferred', 'rumored']

const DIVISIONS = [
  'commercial', 'support', 'marketing', 'product_engineering', 'executive', 'deci',
]

const EVENT_TYPE_COLOR: Record<string, string> = {
  launch:            '#22c55e',
  incident:          '#ef4444',
  campaign:          '#ff6d7a',
  promotion:         '#f59e0b',
  firmware:          '#6ea8ff',
  hardware_revision: '#a78bfa',
  personnel:         '#38bdf8',
  press:             '#fbbf24',
  external:          '#94a3b8',
  holiday:           '#34d399',
  other:             '#9ca3af',
}

const CONFIDENCE_COLOR: Record<LoreConfidence, string> = {
  confirmed: '#22c55e',
  inferred:  '#f59e0b',
  rumored:   '#9ca3af',
}

function yearRange(): string[] {
  const y = new Date().getFullYear()
  const out: string[] = []
  for (let i = y; i >= 2023; i--) out.push(String(i))
  return out
}

export function LoreLedger() {
  const [events, setEvents] = useState<LoreEvent[] | null>(null)
  const [stats, setStats] = useState<LoreEventStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  // Filters
  const [year, setYear] = useState<string>('all')
  const [eventType, setEventType] = useState<string>('all')
  const [confidence, setConfidence] = useState<string>('all')
  const [division, setDivision] = useState<string>('all')
  const [search, setSearch] = useState<string>('')
  const [debouncedSearch, setDebouncedSearch] = useState<string>('')

  // Selection / edit
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [editingId, setEditingId] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState<string | null>(null)

  // Debounce text search so each keystroke doesn't re-query.
  useEffect(() => {
    const h = setTimeout(() => setDebouncedSearch(search.trim()), 250)
    return () => clearTimeout(h)
  }, [search])

  const filterKey = useMemo(
    () => JSON.stringify({ year, eventType, confidence, division, q: debouncedSearch }),
    [year, eventType, confidence, division, debouncedSearch],
  )

  const load = () => {
    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setLoading(true)
    setError(null)

    const opts: Parameters<typeof api.loreEvents>[0] = { limit: 2000 }
    if (year !== 'all') {
      opts.start = `${year}-01-01`
      opts.end   = `${year}-12-31`
    } else {
      opts.start = '2023-01-01'
      opts.end   = new Date().toISOString().slice(0, 10)
    }
    if (eventType !== 'all') opts.event_type = eventType
    if (confidence !== 'all') opts.confidence = confidence
    if (division !== 'all') opts.division = division
    if (debouncedSearch) opts.q = debouncedSearch

    Promise.all([
      api.loreEvents(opts, ctrl.signal),
      api.loreEventStats({ start: '2023-01-01' }, ctrl.signal),
    ])
      .then(([list, summary]) => {
        setEvents(list.events)
        setStats(summary)
        setSelected(new Set()) // drop stale selection after filter change
        setLoading(false)
      })
      .catch((e) => {
        if (ctrl.signal.aborted) return
        setError(e instanceof ApiError ? e.message : 'Failed to load events')
        setLoading(false)
      })
  }

  useEffect(() => {
    load()
    return () => abortRef.current?.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey])

  const showToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(null), 2500)
  }

  const toggle = (id: number) => {
    setSelected((s) => {
      const n = new Set(s)
      if (n.has(id)) n.delete(id); else n.add(id)
      return n
    })
  }
  const toggleAll = () => {
    if (!events) return
    setSelected((s) => {
      if (s.size === events.length) return new Set()
      return new Set(events.map((e) => e.id))
    })
  }

  const bulkConfidence = async (c: LoreConfidence) => {
    if (selected.size === 0 || busy) return
    setBusy(true)
    try {
      const res = await api.loreEventBulkUpdate({ ids: [...selected], confidence: c })
      showToast(`${res.updated} event${res.updated === 1 ? '' : 's'} set to ${c}`)
      load()
    } catch (e: any) {
      setError(e?.message || 'Bulk update failed')
    } finally {
      setBusy(false)
    }
  }

  const bulkDelete = async () => {
    if (selected.size === 0 || busy) return
    if (!window.confirm(`Delete ${selected.size} event${selected.size === 1 ? '' : 's'}? This can't be undone.`)) return
    setBusy(true)
    try {
      const res = await api.loreEventBulkDelete([...selected])
      showToast(`Deleted ${res.deleted} event${res.deleted === 1 ? '' : 's'}`)
      load()
    } catch (e: any) {
      setError(e?.message || 'Bulk delete failed')
    } finally {
      setBusy(false)
    }
  }

  const bulkType = async (t: string) => {
    if (selected.size === 0 || busy) return
    setBusy(true)
    try {
      const res = await api.loreEventBulkUpdate({ ids: [...selected], event_type: t })
      showToast(`${res.updated} event${res.updated === 1 ? '' : 's'} retyped as ${t}`)
      load()
    } catch (e: any) {
      setError(e?.message || 'Bulk update failed')
    } finally {
      setBusy(false)
    }
  }

  const bulkDivision = async (d: string) => {
    if (selected.size === 0 || busy) return
    setBusy(true)
    try {
      const res = await api.loreEventBulkUpdate({ ids: [...selected], division: d || '' })
      showToast(`${res.updated} reassigned to ${d || 'company-wide'}`)
      load()
    } catch (e: any) {
      setError(e?.message || 'Bulk update failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page-grid">
      <div className="page-head" style={{ marginBottom: 4 }}>
        <h2 style={{ marginBottom: 2 }}>Company lore ledger</h2>
        <p style={{ margin: 0, fontSize: 12, color: 'var(--muted)' }}>
          Curated record of launches, incidents, campaigns, and external shocks — feeds seasonality
          context, anomaly narratives, and AI insight grounding.
        </p>
      </div>

      {/* Stats strip */}
      {stats && <StatsStrip stats={stats} />}

      {/* Filter bar */}
      <section className="card">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', fontSize: 12 }}>
          <label style={lblStyle}>Year
            <select value={year} onChange={(e) => setYear(e.target.value)} style={selStyle}>
              <option value="all">all</option>
              {yearRange().map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
          </label>
          <label style={lblStyle}>Type
            <select value={eventType} onChange={(e) => setEventType(e.target.value)} style={selStyle}>
              <option value="all">all</option>
              {EVENT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </label>
          <label style={lblStyle}>Confidence
            <select value={confidence} onChange={(e) => setConfidence(e.target.value)} style={selStyle}>
              <option value="all">all</option>
              {CONFIDENCES.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          <label style={lblStyle}>Division
            <select value={division} onChange={(e) => setDivision(e.target.value)} style={selStyle}>
              <option value="all">all</option>
              <option value="company">(company-wide)</option>
              {DIVISIONS.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </label>
          <label style={{ ...lblStyle, flex: 1, minWidth: 200 }}>Search
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="title or description"
              style={{ ...txtStyle, width: '100%' }}
            />
          </label>
          <button
            type="button"
            onClick={() => {
              setYear('all'); setEventType('all'); setConfidence('all'); setDivision('all'); setSearch('')
            }}
            style={btnStyle('#9fb0d4')}
          >
            Clear filters
          </button>
        </div>
      </section>

      {/* Bulk action bar */}
      {selected.size > 0 && (
        <section className="card" style={{ borderLeft: '3px solid #4a7aff' }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', fontSize: 12 }}>
            <strong style={{ color: '#4a7aff' }}>{selected.size} selected</strong>
            <span style={{ color: 'var(--muted)' }}>·</span>
            <span style={{ color: 'var(--muted)' }}>Set confidence:</span>
            <button type="button" onClick={() => bulkConfidence('confirmed')} disabled={busy} style={btnStyle('#22c55e')}>confirmed</button>
            <button type="button" onClick={() => bulkConfidence('inferred')}  disabled={busy} style={btnStyle('#f59e0b')}>inferred</button>
            <button type="button" onClick={() => bulkConfidence('rumored')}   disabled={busy} style={btnStyle('#9ca3af')}>rumored</button>
            <span style={{ color: 'var(--muted)' }}>·</span>
            <label style={lblStyle}>Retype
              <select onChange={(e) => { if (e.target.value) { bulkType(e.target.value); e.target.value = '' } }} style={selStyle} defaultValue="">
                <option value="">—</option>
                {EVENT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </label>
            <label style={lblStyle}>Reassign division
              <select onChange={(e) => { if (e.target.value !== '__') { bulkDivision(e.target.value); e.target.value = '__' } }} style={selStyle} defaultValue="__">
                <option value="__">—</option>
                <option value="">(company-wide)</option>
                {DIVISIONS.map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
            </label>
            <button type="button" onClick={bulkDelete} disabled={busy} style={btnStyle('#ef4444')}>Delete</button>
            <button type="button" onClick={() => setSelected(new Set())} style={btnStyle('#9fb0d4')}>Clear</button>
          </div>
        </section>
      )}

      {/* Results */}
      <section className="card">
        <div className="card-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
          <span>
            {loading ? 'Loading…' : `${events?.length ?? 0} result${(events?.length ?? 0) === 1 ? '' : 's'}`}
          </span>
          {toast && (
            <span style={{ fontSize: 12, color: '#22c55e', fontWeight: 500 }}>
              {toast}
            </span>
          )}
        </div>

        {error && <div className="state-message error">{error}</div>}

        {!loading && events && events.length > 0 && (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ textAlign: 'left', color: 'var(--muted)', borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
                  <th style={{ padding: '6px 4px', width: 28 }}>
                    <input
                      type="checkbox"
                      checked={events.length > 0 && selected.size === events.length}
                      onChange={toggleAll}
                    />
                  </th>
                  <th style={{ padding: '6px 4px', width: 90 }}>Date</th>
                  <th style={{ padding: '6px 4px', width: 100 }}>Type</th>
                  <th style={{ padding: '6px 4px' }}>Title</th>
                  <th style={{ padding: '6px 4px', width: 130 }}>Division</th>
                  <th style={{ padding: '6px 4px', width: 90 }}>Confidence</th>
                  <th style={{ padding: '6px 4px', width: 90 }}>Source</th>
                  <th style={{ padding: '6px 4px', width: 110 }} />
                </tr>
              </thead>
              <tbody>
                {events.map((ev) => (
                  <EventTableRow
                    key={ev.id}
                    event={ev}
                    checked={selected.has(ev.id)}
                    onToggle={() => toggle(ev.id)}
                    editing={editingId === ev.id}
                    onEdit={() => setEditingId(editingId === ev.id ? null : ev.id)}
                    onSaved={() => { setEditingId(null); load() }}
                    onDelete={async () => {
                      if (!window.confirm(`Delete "${ev.title}"?`)) return
                      await api.loreEventDelete(ev.id)
                      load()
                    }}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}

        {!loading && events && events.length === 0 && (
          <div className="state-message">No events match these filters.</div>
        )}
      </section>
    </div>
  )
}

/* ─── Stats strip ─────────────────────────────────────────────────────── */

function StatsStrip({ stats }: { stats: LoreEventStats }) {
  const confOrder: LoreConfidence[] = ['confirmed', 'inferred', 'rumored']
  return (
    <section className="card">
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12 }}>
        <StatTile label="Total events" value={stats.total} color="#4a7aff" />
        {confOrder.map((c) => (
          <StatTile
            key={c}
            label={`${c}`}
            value={stats.by_confidence[c] || 0}
            color={CONFIDENCE_COLOR[c]}
            pct={stats.total ? (stats.by_confidence[c] || 0) / stats.total : 0}
          />
        ))}
        <StatTile
          label="Top type"
          value={topKey(stats.by_type)}
          color={EVENT_TYPE_COLOR[topKey(stats.by_type) as string] || '#9ca3af'}
          raw
          sub={`${stats.by_type[topKey(stats.by_type) as string] || 0} events`}
        />
        <StatTile
          label="Top division"
          value={topKey(stats.by_division)}
          color="#a78bfa"
          raw
          sub={`${stats.by_division[topKey(stats.by_division) as string] || 0} events`}
        />
      </div>
    </section>
  )
}

function topKey(m: Record<string, number>): string {
  let best = ''
  let max = -1
  for (const [k, v] of Object.entries(m)) {
    if (v > max) { best = k; max = v }
  }
  return best
}

function StatTile({
  label, value, color, pct, raw, sub,
}: { label: string; value: string | number; color: string; pct?: number; raw?: boolean; sub?: string }) {
  return (
    <div
      style={{
        padding: '10px 12px',
        borderLeft: `3px solid ${color}`,
        borderRadius: 6,
        background: 'rgba(255,255,255,0.02)',
      }}
    >
      <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.4 }}>{label}</div>
      <div style={{ fontSize: raw ? 14 : 22, fontWeight: 700, color, lineHeight: 1.1, marginTop: 3 }}>{value}</div>
      {pct != null && (
        <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 2 }}>
          {(pct * 100).toFixed(0)}% of total
        </div>
      )}
      {sub && <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

/* ─── Table row ───────────────────────────────────────────────────────── */

function EventTableRow({
  event, checked, onToggle, editing, onEdit, onSaved, onDelete,
}: {
  event: LoreEvent
  checked: boolean
  onToggle: () => void
  editing: boolean
  onEdit: () => void
  onSaved: () => void
  onDelete: () => void
}) {
  const [form, setForm] = useState({
    title: event.title,
    description: event.description || '',
    event_type: event.event_type,
    confidence: event.confidence,
    division: event.division || '',
    start_date: event.start_date,
    end_date: event.end_date || '',
  })
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const typeColor = EVENT_TYPE_COLOR[event.event_type] || '#9ca3af'
  const confColor = CONFIDENCE_COLOR[event.confidence as LoreConfidence] || '#9ca3af'

  const save = async () => {
    setSaving(true); setErr(null)
    try {
      await api.loreEventUpdate(event.id, {
        title: form.title.trim(),
        description: form.description.trim() || null,
        event_type: form.event_type,
        confidence: form.confidence as LoreConfidence,
        division: form.division || null,
        start_date: form.start_date,
        end_date: form.end_date || null,
      })
      onSaved()
    } catch (e: any) {
      setErr(e?.message || 'Update failed')
    } finally {
      setSaving(false)
    }
  }

  const dateLabel = event.end_date && event.end_date !== event.start_date
    ? `${event.start_date} → ${event.end_date}`
    : event.start_date

  if (!editing) {
    return (
      <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
        <td style={{ padding: '6px 4px' }}>
          <input type="checkbox" checked={checked} onChange={onToggle} />
        </td>
        <td style={{ padding: '6px 4px', color: 'var(--muted)', whiteSpace: 'nowrap' }}>{dateLabel}</td>
        <td style={{ padding: '6px 4px' }}>
          <span style={{ ...typePillStyle, background: `${typeColor}22`, color: typeColor }}>
            {event.event_type}
          </span>
        </td>
        <td style={{ padding: '6px 4px' }}>
          <div style={{ fontWeight: 500 }}>{event.title}</div>
          {event.description && (
            <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2, lineHeight: 1.3 }}>
              {event.description}
            </div>
          )}
        </td>
        <td style={{ padding: '6px 4px', color: 'var(--muted)' }}>{event.division || '—'}</td>
        <td style={{ padding: '6px 4px' }}>
          <span style={{ ...typePillStyle, background: `${confColor}22`, color: confColor }}>
            {event.confidence}
          </span>
        </td>
        <td style={{ padding: '6px 4px', fontSize: 11, color: 'var(--muted)' }}>{event.source_type}</td>
        <td style={{ padding: '6px 4px', textAlign: 'right' }}>
          <button type="button" onClick={onEdit} style={btnStyleSmall('#9fb0d4')}>Edit</button>{' '}
          <button type="button" onClick={onDelete} style={btnStyleSmall('#ef4444')}>Delete</button>
        </td>
      </tr>
    )
  }

  return (
    <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', background: 'rgba(110,168,255,0.05)' }}>
      <td style={{ padding: '6px 4px' }}>
        <input type="checkbox" checked={checked} onChange={onToggle} />
      </td>
      <td style={{ padding: '6px 4px' }}>
        <input type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} style={dateInputStyle} />
        <input type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} style={{ ...dateInputStyle, marginTop: 2 }} />
      </td>
      <td style={{ padding: '6px 4px' }}>
        <select value={form.event_type} onChange={(e) => setForm({ ...form, event_type: e.target.value })} style={selStyle}>
          {EVENT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </td>
      <td style={{ padding: '6px 4px' }}>
        <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} style={{ ...txtStyle, width: '100%' }} />
        <input
          placeholder="Description"
          value={form.description}
          onChange={(e) => setForm({ ...form, description: e.target.value })}
          style={{ ...txtStyle, width: '100%', marginTop: 2 }}
        />
        {err && <div style={{ color: '#ef4444', fontSize: 11 }}>{err}</div>}
      </td>
      <td style={{ padding: '6px 4px' }}>
        <select value={form.division} onChange={(e) => setForm({ ...form, division: e.target.value })} style={selStyle}>
          <option value="">(company-wide)</option>
          {DIVISIONS.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
      </td>
      <td style={{ padding: '6px 4px' }}>
        <select value={form.confidence} onChange={(e) => setForm({ ...form, confidence: e.target.value as LoreConfidence })} style={selStyle}>
          {CONFIDENCES.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </td>
      <td style={{ padding: '6px 4px', fontSize: 11, color: 'var(--muted)' }}>{event.source_type}</td>
      <td style={{ padding: '6px 4px', textAlign: 'right' }}>
        <button type="button" onClick={save} disabled={saving} style={btnStyleSmall('#22c55e')}>
          {saving ? '…' : 'Save'}
        </button>{' '}
        <button type="button" onClick={onEdit} style={btnStyleSmall('#9fb0d4')}>Cancel</button>
      </td>
    </tr>
  )
}

/* ─── shared styles ───────────────────────────────────────────────────── */

const dateInputStyle: React.CSSProperties = {
  background: 'rgba(255,255,255,0.05)',
  border: '1px solid rgba(255,255,255,0.1)',
  color: 'var(--fg)',
  borderRadius: 4,
  padding: '4px 6px',
  fontSize: 12,
}
const txtStyle: React.CSSProperties = { ...dateInputStyle }
const selStyle: React.CSSProperties = { ...dateInputStyle }
const lblStyle: React.CSSProperties = {
  display: 'flex', flexDirection: 'column', gap: 2, fontSize: 10, color: 'var(--muted)',
}

const btnStyle = (color: string): React.CSSProperties => ({
  background: `${color}22`, color, border: `1px solid ${color}66`,
  borderRadius: 4, padding: '4px 10px', fontSize: 12, cursor: 'pointer',
})
const btnStyleSmall = (color: string): React.CSSProperties => ({
  ...btnStyle(color), padding: '2px 8px', fontSize: 11,
})

const typePillStyle: React.CSSProperties = {
  padding: '2px 6px', borderRadius: 3, fontSize: 10, fontWeight: 600,
  whiteSpace: 'nowrap', display: 'inline-block',
}
