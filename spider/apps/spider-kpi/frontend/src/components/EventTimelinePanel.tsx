import { useEffect, useRef, useState } from 'react'

import { api } from '../lib/api'
import type { LoreEvent, LoreEventCreate } from '../lib/types'

/**
 * EventTimelinePanel — editable list + inline-create form for lore events.
 * Typically dropped at the bottom of a division page next to the
 * seasonal baseline charts so Joseph can log "what was happening" in
 * the same surface where he's interpreting the data.
 *
 * Pairs with <EventTimelineStrip> for the visual overlay — this panel
 * is the CRUD interface behind it.
 */

type Props = {
  /** Optional pre-filter. Undefined = show everything; 'company' = only
   *  company-wide (division IS NULL); any string = that division name. */
  division?: string
  /** Pre-fill division on new events. Defaults to the filter value
   *  (when it's a real division name, not 'company'). */
  defaultDivisionForCreate?: string | null
  /** Starting date range for the list. Default: last 90 days. */
  defaultStart?: string
  defaultEnd?: string
  title?: string
  limit?: number
}

const EVENT_TYPES = [
  'launch', 'incident', 'campaign', 'promotion', 'firmware',
  'hardware_revision', 'personnel', 'press', 'external', 'holiday', 'other',
]

const CONFIDENCES = ['confirmed', 'inferred', 'rumored']

const DIVISIONS = [
  'commercial', 'support', 'marketing', 'product_engineering', 'executive', 'deci',
]

function ninetyDaysAgoIso(): string {
  const d = new Date()
  d.setUTCDate(d.getUTCDate() - 90)
  return d.toISOString().slice(0, 10)
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

export function EventTimelinePanel({
  division,
  defaultDivisionForCreate,
  defaultStart,
  defaultEnd,
  title = 'Event timeline',
  limit = 200,
}: Props) {
  const [events, setEvents] = useState<LoreEvent[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [start, setStart] = useState(defaultStart || ninetyDaysAgoIso())
  const [end, setEnd] = useState(defaultEnd || todayIso())
  const [showNew, setShowNew] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const seedDivision =
    defaultDivisionForCreate !== undefined
      ? defaultDivisionForCreate
      : (division && division !== 'company' ? division : null)

  const [form, setForm] = useState<LoreEventCreate>({
    event_type: 'launch',
    title: '',
    description: '',
    start_date: todayIso(),
    end_date: null,
    division: seedDivision,
    confidence: 'confirmed',
    source_type: 'manual',
  })

  const load = () => {
    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setLoading(true)
    setError(null)
    api.loreEvents({ start, end, division, limit }, ctrl.signal)
      .then((res) => {
        setEvents(res.events)
        setLoading(false)
      })
      .catch((e) => {
        if (ctrl.signal.aborted) return
        setError(e?.message || 'Failed to load events')
        setLoading(false)
      })
  }

  useEffect(() => {
    load()
    return () => abortRef.current?.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [start, end, division, limit])

  const onCreate = async () => {
    if (!form.title.trim() || !form.start_date) return
    setSaving(true)
    try {
      await api.loreEventCreate({
        ...form,
        title: form.title.trim(),
        description: form.description?.trim() || null,
        end_date: form.end_date || null,
        division: form.division || null,
      })
      setShowNew(false)
      setForm({
        event_type: 'launch',
        title: '',
        description: '',
        start_date: todayIso(),
        end_date: null,
        division: seedDivision,
        confidence: 'confirmed',
        source_type: 'manual',
      })
      load()
    } catch (e: any) {
      setError(e?.message || 'Failed to create event')
    } finally {
      setSaving(false)
    }
  }

  const onDelete = async (id: number) => {
    if (!window.confirm('Delete this event?')) return
    setSaving(true)
    try {
      await api.loreEventDelete(id)
      setEditingId(null)
      load()
    } catch (e: any) {
      setError(e?.message || 'Failed to delete event')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="card">
      <div className="card-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>{title}</span>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12 }}>
          <input
            type="date"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            style={dateInputStyle}
          />
          <span style={{ color: 'var(--muted)' }}>→</span>
          <input
            type="date"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            style={dateInputStyle}
          />
          <button
            type="button"
            onClick={() => setShowNew((v) => !v)}
            style={btnStyle(showNew ? '#ef4444' : '#6ea8ff')}
          >
            {showNew ? 'Cancel' : '+ New event'}
          </button>
        </div>
      </div>

      {showNew && (
        <div style={formWrap}>
          <div style={formRow}>
            <input
              placeholder="Event title (required)"
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              style={{ ...txtStyle, flex: 2 }}
            />
            <select
              value={form.event_type}
              onChange={(e) => setForm({ ...form, event_type: e.target.value })}
              style={selStyle}
            >
              {EVENT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
            <select
              value={form.confidence || 'confirmed'}
              onChange={(e) => setForm({ ...form, confidence: e.target.value as any })}
              style={selStyle}
            >
              {CONFIDENCES.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <select
              value={form.division || ''}
              onChange={(e) => setForm({ ...form, division: e.target.value || null })}
              style={selStyle}
            >
              <option value="">(company-wide)</option>
              {DIVISIONS.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </div>
          <div style={formRow}>
            <label style={lblStyle}>Start
              <input type="date" value={form.start_date}
                onChange={(e) => setForm({ ...form, start_date: e.target.value })}
                style={dateInputStyle} />
            </label>
            <label style={lblStyle}>End (optional)
              <input type="date" value={form.end_date || ''}
                onChange={(e) => setForm({ ...form, end_date: e.target.value || null })}
                style={dateInputStyle} />
            </label>
            <input
              placeholder="Description (optional)"
              value={form.description || ''}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              style={{ ...txtStyle, flex: 3 }}
            />
            <button type="button" onClick={onCreate} disabled={saving || !form.title.trim()} style={btnStyle('#22c55e')}>
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="state-message">Loading events…</div>
      ) : error ? (
        <div className="state-message error">{error}</div>
      ) : !events || events.length === 0 ? (
        <div className="state-message">No events in this range.</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {events.map((ev) => (
            <EventRow
              key={ev.id}
              event={ev}
              editing={editingId === ev.id}
              onEdit={() => setEditingId(editingId === ev.id ? null : ev.id)}
              onDelete={() => onDelete(ev.id)}
              onSaved={() => { setEditingId(null); load() }}
            />
          ))}
        </div>
      )}
    </section>
  )
}

function EventRow({
  event,
  editing,
  onEdit,
  onDelete,
  onSaved,
}: {
  event: LoreEvent
  editing: boolean
  onEdit: () => void
  onDelete: () => void
  onSaved: () => void
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

  const save = async () => {
    setSaving(true); setErr(null)
    try {
      await api.loreEventUpdate(event.id, {
        title: form.title.trim(),
        description: form.description.trim() || null,
        event_type: form.event_type,
        confidence: form.confidence as any,
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

  const color = '#6ea8ff'
  const dateLabel = event.end_date && event.end_date !== event.start_date
    ? `${event.start_date} → ${event.end_date}`
    : event.start_date

  if (!editing) {
    return (
      <div style={rowStyle}>
        <span style={{ ...typePillStyle, background: `${color}22`, color }}>{event.event_type}</span>
        <span style={{ fontWeight: 600, flex: 1 }}>{event.title}</span>
        <span style={{ fontSize: 11, color: 'var(--muted)' }}>{dateLabel}</span>
        {event.division && (
          <span style={{ fontSize: 10, color: 'var(--muted)', opacity: 0.8 }}>{event.division}</span>
        )}
        <span style={{ fontSize: 10, color: 'var(--muted)', opacity: 0.75 }}>{event.confidence}</span>
        <button type="button" onClick={onEdit} style={btnStyleSmall('#9fb0d4')}>Edit</button>
        <button type="button" onClick={onDelete} style={btnStyleSmall('#ef4444')}>Delete</button>
      </div>
    )
  }

  return (
    <div style={{ ...rowStyle, flexWrap: 'wrap' }}>
      <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })}
        style={{ ...txtStyle, flex: 2 }} />
      <select value={form.event_type} onChange={(e) => setForm({ ...form, event_type: e.target.value })} style={selStyle}>
        {EVENT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
      </select>
      <select value={form.confidence} onChange={(e) => setForm({ ...form, confidence: e.target.value as any })} style={selStyle}>
        {CONFIDENCES.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
      <select value={form.division} onChange={(e) => setForm({ ...form, division: e.target.value })} style={selStyle}>
        <option value="">(company-wide)</option>
        {DIVISIONS.map((d) => <option key={d} value={d}>{d}</option>)}
      </select>
      <input type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} style={dateInputStyle} />
      <input type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} style={dateInputStyle} />
      <input placeholder="Description" value={form.description}
        onChange={(e) => setForm({ ...form, description: e.target.value })}
        style={{ ...txtStyle, flex: 3 }} />
      <button type="button" onClick={save} disabled={saving} style={btnStyleSmall('#22c55e')}>
        {saving ? '…' : 'Save'}
      </button>
      <button type="button" onClick={onEdit} style={btnStyleSmall('#9fb0d4')}>Cancel</button>
      {err && <div style={{ width: '100%', color: '#ef4444', fontSize: 11 }}>{err}</div>}
    </div>
  )
}

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
const lblStyle: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: 2, fontSize: 10, color: 'var(--muted)' }

const btnStyle = (color: string): React.CSSProperties => ({
  background: `${color}22`, color, border: `1px solid ${color}66`,
  borderRadius: 4, padding: '4px 10px', fontSize: 12, cursor: 'pointer',
})
const btnStyleSmall = (color: string): React.CSSProperties => ({
  ...btnStyle(color), padding: '2px 8px', fontSize: 11,
})

const rowStyle: React.CSSProperties = {
  display: 'flex', gap: 8, alignItems: 'center',
  padding: '6px 8px',
  background: 'rgba(255,255,255,0.02)',
  border: '1px solid rgba(255,255,255,0.06)',
  borderRadius: 4,
  fontSize: 12,
}

const typePillStyle: React.CSSProperties = {
  padding: '2px 6px', borderRadius: 3, fontSize: 10, fontWeight: 600,
  whiteSpace: 'nowrap',
}

const formWrap: React.CSSProperties = {
  display: 'flex', flexDirection: 'column', gap: 6,
  padding: 8, marginBottom: 10,
  background: 'rgba(110,168,255,0.06)',
  border: '1px solid rgba(110,168,255,0.2)',
  borderRadius: 4,
}
const formRow: React.CSSProperties = {
  display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center',
}
