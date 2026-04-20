import { useEffect, useMemo, useRef, useState } from 'react'

import { api, ApiError } from '../lib/api'
import type { LoreEvent, LoreEventStats, LoreConfidence, LoreEventCreate } from '../lib/types'
import { EventImpactStrip } from '../components/EventImpactStrip'

/**
 * Lore Ledger — the narrative company-history surface.
 *
 * Three modes:
 *   - Story    (default): chapter-by-chapter narrative view. Events
 *               grouped into eras, most-notable events surfaced, prose
 *               description, inline timeline strip per era.
 *   - Timeline: a full-width visual timeline (years × months) with
 *               events as colored pins. Click a pin for details.
 *   - Manage:   the curation grid — filters, inline edit, bulk actions,
 *               add-event form. This is where you promote/retype/sweep
 *               Opus-seeded events.
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

const DIVISION_COLOR: Record<string, string> = {
  commercial:         '#6ea8ff',
  support:            '#f59e0b',
  marketing:          '#ff6d7a',
  product_engineering:'#a78bfa',
  executive:          '#fbbf24',
  deci:               '#34d399',
}

// Rank events by "narrative weight" — what deserves top-billing in a
// chapter summary. Higher = more likely to be a featured card.
const TYPE_PRIORITY: Record<string, number> = {
  incident:          100,
  launch:            90,
  hardware_revision: 85,
  firmware:          80,
  press:             60,
  personnel:         55,
  campaign:          50,
  promotion:         40,
  external:          30,
  holiday:           10,
  other:             5,
}

const CONF_PRIORITY: Record<LoreConfidence, number> = {
  confirmed: 20, inferred: 10, rumored: 0,
}

type TabKey = 'story' | 'timeline' | 'manage'

export function LoreLedger() {
  const [tab, setTab] = useState<TabKey>('story')

  return (
    <div className="page-grid">
      <div className="page-head" style={{ marginBottom: 4 }}>
        <h2 style={{ marginBottom: 2 }}>Company lore ledger</h2>
        <p style={{ margin: 0, fontSize: 12, color: 'var(--muted)' }}>
          The institutional memory of Spider Grills — launches, incidents, campaigns, and
          external shocks. Feeds seasonality context, anomaly narratives, and AI insight
          grounding across every division page.
        </p>
      </div>

      <TabBar tab={tab} onChange={setTab} />

      {tab === 'story'    && <LoreStoryView />}
      {tab === 'timeline' && <LoreTimelineView />}
      {tab === 'manage'   && <LoreManageView />}
    </div>
  )
}

/* ═══════════════════════════════════════════════════════════════════════
   Tab bar
   ═══════════════════════════════════════════════════════════════════════ */

function TabBar({ tab, onChange }: { tab: TabKey; onChange: (t: TabKey) => void }) {
  const tabs: { key: TabKey; label: string; hint: string }[] = [
    { key: 'story',    label: 'Story',    hint: 'Chaptered narrative history' },
    { key: 'timeline', label: 'Timeline', hint: 'Visual event timeline' },
    { key: 'manage',   label: 'Manage',   hint: 'Curate + promote + sweep' },
  ]
  return (
    <div style={{ display: 'flex', gap: 2, borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
      {tabs.map((t) => {
        const active = tab === t.key
        return (
          <button
            key={t.key}
            type="button"
            onClick={() => onChange(t.key)}
            title={t.hint}
            style={{
              background: 'transparent',
              color: active ? '#fff' : 'var(--muted)',
              border: 'none',
              borderBottom: active ? '2px solid #6ea8ff' : '2px solid transparent',
              padding: '8px 16px',
              fontSize: 13,
              fontWeight: active ? 600 : 400,
              cursor: 'pointer',
              marginBottom: -1,
            }}
          >
            {t.label}
          </button>
        )
      })}
    </div>
  )
}

/* ═══════════════════════════════════════════════════════════════════════
   Shared data hook — events + stats for a date range
   ═══════════════════════════════════════════════════════════════════════ */

function useLoreData(
  { start, end }: { start: string; end: string },
) {
  const [events, setEvents] = useState<LoreEvent[] | null>(null)
  const [stats, setStats] = useState<LoreEventStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)

  useEffect(() => {
    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setLoading(true)
    setError(null)
    Promise.all([
      api.loreEvents({ start, end, limit: 5000 }, ctrl.signal),
      api.loreEventStats({ start, end }, ctrl.signal),
    ])
      .then(([list, summary]) => {
        setEvents(list.events)
        setStats(summary)
        setLoading(false)
      })
      .catch((e) => {
        if (ctrl.signal.aborted) return
        setError(e instanceof ApiError ? e.message : 'Failed to load events')
        setLoading(false)
      })
    return () => ctrl.abort()
  }, [start, end, refreshKey])

  return {
    events, stats, loading, error,
    refresh: () => setRefreshKey((k) => k + 1),
  }
}

/* ═══════════════════════════════════════════════════════════════════════
   STORY view — chapter-by-chapter narrative
   ═══════════════════════════════════════════════════════════════════════ */

type Chapter = {
  key: string              // e.g. "2025-Q2"
  label: string            // e.g. "Q2 2025"
  dateLabel: string        // e.g. "Apr – Jun 2025"
  start: string            // YYYY-MM-DD
  end: string              // YYYY-MM-DD
  events: LoreEvent[]
  byType: Record<string, number>
  byConfidence: Record<string, number>
  featured: LoreEvent[]
  narrative: string
}

function quarterOf(ymd: string): { q: number; year: number } {
  const d = new Date(ymd + 'T00:00:00Z')
  const month = d.getUTCMonth() + 1
  return { q: Math.floor((month - 1) / 3) + 1, year: d.getUTCFullYear() }
}

function quarterBounds(year: number, q: number): { start: string; end: string } {
  const firstMonth = (q - 1) * 3 + 1
  const lastMonth = firstMonth + 2
  const start = `${year}-${String(firstMonth).padStart(2, '0')}-01`
  const lastDay = new Date(Date.UTC(year, lastMonth, 0)).getUTCDate()
  const end = `${year}-${String(lastMonth).padStart(2, '0')}-${String(lastDay).padStart(2, '0')}`
  return { start, end }
}

function quarterDateLabel(year: number, q: number): string {
  const months = [
    ['Jan', 'Feb', 'Mar'], ['Apr', 'May', 'Jun'],
    ['Jul', 'Aug', 'Sep'], ['Oct', 'Nov', 'Dec'],
  ][q - 1]
  return `${months[0]} – ${months[2]} ${year}`
}

function rankEvent(e: LoreEvent): number {
  return (TYPE_PRIORITY[e.event_type] ?? 0)
    + (CONF_PRIORITY[e.confidence as LoreConfidence] ?? 0)
}

function buildChapters(events: LoreEvent[]): Chapter[] {
  const buckets: Record<string, LoreEvent[]> = {}
  for (const ev of events) {
    const { q, year } = quarterOf(ev.start_date)
    const key = `${year}-Q${q}`
    if (!buckets[key]) buckets[key] = []
    buckets[key].push(ev)
  }
  const chapters: Chapter[] = Object.entries(buckets).map(([key, evs]) => {
    const [yearStr, qStr] = key.split('-Q')
    const year = Number(yearStr)
    const q = Number(qStr)
    const { start, end } = quarterBounds(year, q)

    const byType: Record<string, number> = {}
    const byConfidence: Record<string, number> = {}
    for (const e of evs) {
      byType[e.event_type] = (byType[e.event_type] || 0) + 1
      byConfidence[e.confidence] = (byConfidence[e.confidence] || 0) + 1
    }

    const ranked = [...evs].sort((a, b) => rankEvent(b) - rankEvent(a))
    const featured = ranked.slice(0, 5)

    const narrative = composeNarrative(year, q, evs, byType, featured)

    return {
      key,
      label: `Q${q} ${year}`,
      dateLabel: quarterDateLabel(year, q),
      start, end,
      events: evs.sort((a, b) => a.start_date.localeCompare(b.start_date)),
      byType, byConfidence,
      featured,
      narrative,
    }
  })
  // Newest chapter first so the most recent history is what you land on.
  chapters.sort((a, b) => b.key.localeCompare(a.key))
  return chapters
}

function composeNarrative(
  year: number, q: number, evs: LoreEvent[],
  byType: Record<string, number>, featured: LoreEvent[],
): string {
  if (evs.length === 0) return 'A quiet quarter — no recorded events.'

  const n = evs.length
  const topTypes = Object.entries(byType)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 3)
    .map(([t, c]) => `${c} ${t.replace('_', ' ')}${c === 1 ? '' : 's'}`)

  const incidentCount = byType.incident || 0
  const launchCount = byType.launch || 0
  const firmwareCount = byType.firmware || 0
  const campaignCount = (byType.campaign || 0) + (byType.promotion || 0)

  const bits: string[] = []
  bits.push(`Q${q} ${year} recorded ${n} event${n === 1 ? '' : 's'}`)
  bits[0] += ` — mostly ${topTypes.join(', ')}.`

  if (incidentCount >= 3) {
    bits.push(`A heavy incident quarter (${incidentCount}), suggesting reliability pressure.`)
  } else if (incidentCount > 0) {
    bits.push(`${incidentCount} incident${incidentCount === 1 ? '' : 's'} recorded.`)
  }

  if (launchCount >= 2) {
    bits.push(`${launchCount} launch events — a notable product-push quarter.`)
  } else if (launchCount === 1) {
    const launch = featured.find((e) => e.event_type === 'launch')
    if (launch) bits.push(`Launch: ${launch.title}.`)
  }

  if (firmwareCount >= 2) {
    bits.push(`${firmwareCount} firmware releases — the fleet saw active update pressure.`)
  }

  if (campaignCount >= 3) {
    bits.push(`${campaignCount} marketing pushes this quarter.`)
  }

  return bits.join(' ')
}

function LoreStoryView() {
  // Fixed wide window — we want *all* history here, grouped into chapters.
  const { events, stats, loading, error } = useLoreData({
    start: '2023-01-01',
    end: new Date().toISOString().slice(0, 10),
  })

  const chapters = useMemo(() => (events ? buildChapters(events) : []), [events])

  if (loading) return <section className="card"><div className="state-message">Loading company history…</div></section>
  if (error) return <section className="card"><div className="state-message error">{error}</div></section>
  if (!events || events.length === 0) {
    return (
      <section className="card">
        <div className="state-message">
          No events recorded yet. Head to Manage and add your first event, or run the
          Opus seed pass to extract events from the email archive.
        </div>
      </section>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {stats && <OverallNarrativeStrip stats={stats} chapters={chapters} />}
      {chapters.map((c) => (
        <ChapterCard key={c.key} chapter={c} />
      ))}
    </div>
  )
}

function OverallNarrativeStrip({ stats, chapters }: { stats: LoreEventStats; chapters: Chapter[] }) {
  const firstDate = chapters[chapters.length - 1]?.events[0]?.start_date
  const lastDate = chapters[0]?.events[chapters[0].events.length - 1]?.start_date
  const topType = Object.entries(stats.by_type).sort(([, a], [, b]) => b - a)[0]
  const topDiv = Object.entries(stats.by_division).sort(([, a], [, b]) => b - a)[0]
  return (
    <section className="card" style={{ borderLeft: '3px solid #6ea8ff' }}>
      <div className="card-title" style={{ marginBottom: 8 }}>The Spider Grills story so far</div>
      <div style={{ fontSize: 13, lineHeight: 1.55, color: 'var(--fg)' }}>
        <strong>{stats.total}</strong> recorded event{stats.total === 1 ? '' : 's'}
        {firstDate && lastDate ? ` between ${firstDate} and ${lastDate}` : ''},
        spread across <strong>{chapters.length}</strong> quarter{chapters.length === 1 ? '' : 's'}.
        {topType && <> Dominant theme: <strong style={{ color: EVENT_TYPE_COLOR[topType[0]] || '#fff' }}>{topType[0].replace('_', ' ')}</strong> ({topType[1]} events).</>}
        {topDiv && <> Most-active division: <strong>{topDiv[0]}</strong> ({topDiv[1]}).</>}
        {' '}Scroll down to read chapter-by-chapter.
      </div>
      <div style={{ marginTop: 10, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {CONFIDENCES.map((c) => {
          const v = stats.by_confidence[c] || 0
          if (!v) return null
          return (
            <span
              key={c}
              style={{
                fontSize: 10, padding: '2px 8px', borderRadius: 10,
                background: `${CONFIDENCE_COLOR[c]}22`, color: CONFIDENCE_COLOR[c],
                border: `1px solid ${CONFIDENCE_COLOR[c]}55`,
              }}
            >
              {v} {c}
            </span>
          )
        })}
      </div>
    </section>
  )
}

function ChapterCard({ chapter }: { chapter: Chapter }) {
  const [expanded, setExpanded] = useState(false)
  const typeRanking = Object.entries(chapter.byType).sort(([, a], [, b]) => b - a)

  return (
    <section className="card">
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', justifyContent: 'space-between', gap: 8, marginBottom: 6 }}>
        <div>
          <h3 style={{ margin: 0, fontSize: 18 }}>{chapter.label}</h3>
          <div style={{ fontSize: 11, color: 'var(--muted)' }}>{chapter.dateLabel}</div>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, justifyContent: 'flex-end' }}>
          {typeRanking.slice(0, 5).map(([t, c]) => (
            <span
              key={t}
              style={{
                fontSize: 10, padding: '2px 7px', borderRadius: 10,
                background: `${EVENT_TYPE_COLOR[t] || '#9ca3af'}22`,
                color: EVENT_TYPE_COLOR[t] || '#9ca3af',
                border: `1px solid ${EVENT_TYPE_COLOR[t] || '#9ca3af'}44`,
              }}
            >
              {c} {t.replace('_', ' ')}
            </span>
          ))}
        </div>
      </div>

      <div style={{ fontSize: 13, lineHeight: 1.55, color: 'var(--fg)', marginBottom: 10 }}>
        {chapter.narrative}
      </div>

      {/* Inline timeline strip for this chapter */}
      <ChapterTimelineStrip chapter={chapter} />

      {/* Featured events */}
      {chapter.featured.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 6 }}>
            Key moments
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 8 }}>
            {chapter.featured.map((ev) => <FeaturedEventCard key={ev.id} event={ev} />)}
          </div>
        </div>
      )}

      {chapter.events.length > chapter.featured.length && (
        <div style={{ marginTop: 10 }}>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            style={{
              background: 'transparent',
              color: '#6ea8ff',
              border: 'none',
              padding: 0,
              fontSize: 12,
              cursor: 'pointer',
              textDecoration: 'underline',
            }}
          >
            {expanded
              ? 'Hide all events'
              : `See all ${chapter.events.length} events`}
          </button>
          {expanded && (
            <div style={{ marginTop: 8, maxHeight: 360, overflowY: 'auto' }}>
              {chapter.events.map((ev) => <CompactEventRow key={ev.id} event={ev} />)}
            </div>
          )}
        </div>
      )}
    </section>
  )
}

function ChapterTimelineStrip({ chapter }: { chapter: Chapter }) {
  // Local inline timeline — no network call, uses chapter events.
  const startMs = new Date(chapter.start + 'T00:00:00Z').getTime()
  const endMs = new Date(chapter.end + 'T23:59:59Z').getTime()
  const span = Math.max(1, endMs - startMs)
  const height = 34

  return (
    <div
      style={{
        position: 'relative', height, width: '100%',
        background: 'rgba(255,255,255,0.03)',
        border: '1px solid rgba(255,255,255,0.06)',
        borderRadius: 4, overflow: 'hidden',
      }}
    >
      {/* Month gridlines */}
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          style={{
            position: 'absolute', top: 0, bottom: 0,
            left: `${(i / 3) * 100}%`,
            width: 1,
            background: 'rgba(255,255,255,0.05)',
          }}
        />
      ))}

      {chapter.events.map((ev) => {
        const s = new Date(ev.start_date + 'T00:00:00Z').getTime()
        const e = ev.end_date
          ? new Date(ev.end_date + 'T23:59:59Z').getTime()
          : s + 1000 * 60 * 60 * 24
        const leftPct = Math.max(0, Math.min(100, ((s - startMs) / span) * 100))
        const widthPct = Math.max(0.5, Math.min(100 - leftPct, ((e - s) / span) * 100))
        const color = EVENT_TYPE_COLOR[ev.event_type] || '#9ca3af'
        const confOpacity = ev.confidence === 'confirmed' ? 1 : ev.confidence === 'inferred' ? 0.65 : 0.4
        return (
          <div
            key={ev.id}
            title={`${ev.title}\n${ev.start_date}${ev.end_date ? ' → ' + ev.end_date : ''}\n${ev.event_type} · ${ev.confidence}`}
            style={{
              position: 'absolute',
              left: `${leftPct}%`,
              width: `${Math.max(3, widthPct)}%`,
              top: 6, bottom: 6,
              background: color,
              borderRadius: 2,
              opacity: confOpacity,
              cursor: 'default',
            }}
          />
        )
      })}
    </div>
  )
}

function FeaturedEventCard({ event }: { event: LoreEvent }) {
  const color = EVENT_TYPE_COLOR[event.event_type] || '#9ca3af'
  const confColor = CONFIDENCE_COLOR[event.confidence as LoreConfidence] || '#9ca3af'
  const dateLabel = event.end_date && event.end_date !== event.start_date
    ? `${event.start_date} → ${event.end_date}`
    : event.start_date
  return (
    <div
      style={{
        padding: '10px 12px',
        background: 'rgba(255,255,255,0.03)',
        border: '1px solid rgba(255,255,255,0.08)',
        borderLeft: `3px solid ${color}`,
        borderRadius: 4,
        minWidth: 0,
      }}
    >
      <div style={{ display: 'flex', gap: 6, alignItems: 'baseline', marginBottom: 4 }}>
        <span
          style={{
            fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 3,
            background: `${color}22`, color,
            textTransform: 'uppercase', letterSpacing: 0.5,
          }}
        >
          {event.event_type.replace('_', ' ')}
        </span>
        <span style={{ fontSize: 10, color: 'var(--muted)' }}>{dateLabel}</span>
        <span
          style={{
            fontSize: 9, marginLeft: 'auto',
            color: confColor,
          }}
          title={`confidence: ${event.confidence}`}
        >
          ● {event.confidence}
        </span>
      </div>
      <div style={{ fontSize: 13, fontWeight: 500, lineHeight: 1.35 }}>
        {event.title}
      </div>
      {event.description && (
        <div
          style={{
            fontSize: 11, color: 'var(--muted)', marginTop: 4,
            lineHeight: 1.45,
            display: '-webkit-box',
            WebkitLineClamp: 3,
            WebkitBoxOrient: 'vertical',
            overflow: 'hidden',
          }}
        >
          {event.description}
        </div>
      )}
      {event.division && (
        <div style={{ fontSize: 10, color: DIVISION_COLOR[event.division] || 'var(--muted)', marginTop: 5 }}>
          {event.division}
        </div>
      )}
      <EventImpactStrip eventId={event.id} />
    </div>
  )
}

function CompactEventRow({ event }: { event: LoreEvent }) {
  const color = EVENT_TYPE_COLOR[event.event_type] || '#9ca3af'
  const confOpacity = event.confidence === 'confirmed' ? 1 : event.confidence === 'inferred' ? 0.75 : 0.55
  return (
    <div
      style={{
        display: 'flex', gap: 8, alignItems: 'baseline',
        padding: '4px 0',
        borderBottom: '1px solid rgba(255,255,255,0.04)',
        opacity: confOpacity,
        fontSize: 12,
      }}
    >
      <span style={{ fontSize: 10, color: 'var(--muted)', minWidth: 76, fontVariantNumeric: 'tabular-nums' }}>
        {event.start_date}
      </span>
      <span
        style={{
          fontSize: 9, padding: '1px 5px', borderRadius: 3,
          background: `${color}22`, color, minWidth: 60, textAlign: 'center',
        }}
      >
        {event.event_type}
      </span>
      <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {event.title}
      </span>
      {event.division && (
        <span style={{ fontSize: 10, color: 'var(--muted)' }}>{event.division}</span>
      )}
    </div>
  )
}

/* ═══════════════════════════════════════════════════════════════════════
   TIMELINE view — full-width horizontal view across all years
   ═══════════════════════════════════════════════════════════════════════ */

function LoreTimelineView() {
  const [division, setDivision] = useState<string>('all')
  const [typeFilter, setTypeFilter] = useState<string>('all')
  const [confFilter, setConfFilter] = useState<string>('all')
  const today = new Date().toISOString().slice(0, 10)
  const { events, loading, error } = useLoreData({ start: '2023-01-01', end: today })

  const filtered = useMemo(() => {
    if (!events) return []
    return events.filter((e) => {
      if (division !== 'all') {
        if (division === 'company' && e.division) return false
        if (division !== 'company' && e.division !== division) return false
      }
      if (typeFilter !== 'all' && e.event_type !== typeFilter) return false
      if (confFilter !== 'all' && e.confidence !== confFilter) return false
      return true
    })
  }, [events, division, typeFilter, confFilter])

  // Group filtered events by year for the big timeline lanes.
  const byYear = useMemo(() => {
    const buckets: Record<string, LoreEvent[]> = {}
    for (const e of filtered) {
      const y = e.start_date.slice(0, 4)
      if (!buckets[y]) buckets[y] = []
      buckets[y].push(e)
    }
    return Object.entries(buckets).sort(([a], [b]) => b.localeCompare(a))
  }, [filtered])

  if (loading) return <section className="card"><div className="state-message">Loading timeline…</div></section>
  if (error) return <section className="card"><div className="state-message error">{error}</div></section>

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Filter bar */}
      <section className="card" style={{ padding: '8px 12px' }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', fontSize: 11 }}>
          <span style={{ color: 'var(--muted)' }}>Filter:</span>
          <select value={division} onChange={(e) => setDivision(e.target.value)} style={selStyle}>
            <option value="all">all divisions</option>
            <option value="company">(company-wide)</option>
            {DIVISIONS.map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
          <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} style={selStyle}>
            <option value="all">all types</option>
            {EVENT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
          <select value={confFilter} onChange={(e) => setConfFilter(e.target.value)} style={selStyle}>
            <option value="all">all confidence</option>
            {CONFIDENCES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <span style={{ color: 'var(--muted)', marginLeft: 'auto' }}>
            {filtered.length} event{filtered.length === 1 ? '' : 's'} shown
          </span>
        </div>

        {/* Legend */}
        <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {EVENT_TYPES.map((t) => (
            <span key={t} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 10, color: 'var(--muted)' }}>
              <span style={{ display: 'inline-block', width: 10, height: 10, background: EVENT_TYPE_COLOR[t], borderRadius: 2 }} />
              {t.replace('_', ' ')}
            </span>
          ))}
        </div>
      </section>

      {byYear.length === 0 && (
        <section className="card"><div className="state-message">No events match these filters.</div></section>
      )}

      {byYear.map(([year, evs]) => (
        <YearLane key={year} year={year} events={evs} />
      ))}
    </div>
  )
}

function YearLane({ year, events }: { year: string; events: LoreEvent[] }) {
  const yearStart = new Date(`${year}-01-01T00:00:00Z`).getTime()
  const yearEnd = new Date(`${year}-12-31T23:59:59Z`).getTime()
  const span = yearEnd - yearStart

  return (
    <section className="card" style={{ padding: '10px 12px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
        <h3 style={{ margin: 0, fontSize: 16 }}>{year}</h3>
        <span style={{ fontSize: 11, color: 'var(--muted)' }}>{events.length} event{events.length === 1 ? '' : 's'}</span>
      </div>

      {/* Month axis */}
      <div style={{ display: 'flex', fontSize: 9, color: 'var(--muted)', marginBottom: 2 }}>
        {['J','F','M','A','M','J','J','A','S','O','N','D'].map((m, i) => (
          <div key={i} style={{ flex: 1, textAlign: 'center' }}>{m}</div>
        ))}
      </div>

      {/* Timeline track */}
      <div
        style={{
          position: 'relative', height: 60,
          background: 'rgba(255,255,255,0.02)',
          border: '1px solid rgba(255,255,255,0.06)',
          borderRadius: 4, overflow: 'hidden',
        }}
      >
        {/* Month gridlines */}
        {Array.from({ length: 12 }).map((_, i) => (
          <div
            key={i}
            style={{
              position: 'absolute', top: 0, bottom: 0,
              left: `${(i / 12) * 100}%`,
              width: 1,
              background: 'rgba(255,255,255,0.06)',
            }}
          />
        ))}

        {events.map((ev, idx) => {
          const s = new Date(ev.start_date + 'T00:00:00Z').getTime()
          const e = ev.end_date
            ? new Date(ev.end_date + 'T23:59:59Z').getTime()
            : s + 1000 * 60 * 60 * 24
          const leftPct = Math.max(0, Math.min(100, ((s - yearStart) / span) * 100))
          const widthPct = Math.max(0.3, Math.min(100 - leftPct, ((e - s) / span) * 100))
          const color = EVENT_TYPE_COLOR[ev.event_type] || '#9ca3af'
          const opacity = ev.confidence === 'confirmed' ? 1 : ev.confidence === 'inferred' ? 0.7 : 0.45
          // Stagger vertically to reduce overlap — simple row-mod-3.
          const row = idx % 3
          return (
            <div
              key={ev.id}
              title={`${ev.title}\n${ev.start_date}${ev.end_date ? ' → ' + ev.end_date : ''}\n${ev.event_type} · ${ev.confidence}${ev.division ? ' · ' + ev.division : ''}${ev.description ? '\n\n' + ev.description : ''}`}
              style={{
                position: 'absolute',
                left: `${leftPct}%`,
                width: `${Math.max(2, widthPct)}%`,
                top: 6 + row * 17,
                height: 14,
                background: color,
                borderRadius: 2,
                opacity,
              }}
            />
          )
        })}
      </div>
    </section>
  )
}

/* ═══════════════════════════════════════════════════════════════════════
   MANAGE view — the curation grid (formerly the whole page)
   ═══════════════════════════════════════════════════════════════════════ */

function yearRange(): string[] {
  const y = new Date().getFullYear()
  const out: string[] = []
  for (let i = y; i >= 2023; i--) out.push(String(i))
  return out
}

function LoreManageView() {
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

  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [editingId, setEditingId] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const [showAdd, setShowAdd] = useState(false)

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
        setSelected(new Set())
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
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {stats && <ManageStatsStrip stats={stats} />}

      {/* Division pills + add */}
      <section className="card" style={{ padding: '8px 12px' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', fontSize: 11 }}>
          <span style={{ color: 'var(--muted)', marginRight: 4 }}>Quick division:</span>
          <DivisionPill label="all" active={division === 'all'} onClick={() => setDivision('all')} color="#9fb0d4" />
          <DivisionPill label="company-wide" active={division === 'company'} onClick={() => setDivision('company')} color="#94a3b8" />
          {DIVISIONS.map((d) => (
            <DivisionPill
              key={d}
              label={d}
              active={division === d}
              onClick={() => setDivision(d)}
              color={DIVISION_COLOR[d] || '#a78bfa'}
              count={stats?.by_division?.[d]}
            />
          ))}
          <span style={{ marginLeft: 'auto' }}>
            <button type="button" onClick={() => setShowAdd((v) => !v)} style={btnStyle('#22c55e')}>
              {showAdd ? '× Cancel' : '+ Add event'}
            </button>
          </span>
        </div>
      </section>

      {showAdd && (
        <AddEventForm
          onCancel={() => setShowAdd(false)}
          onCreated={() => { setShowAdd(false); showToast('Event created'); load() }}
        />
      )}

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

/* ─── Manage-view stats strip ──────────────────────────────────────────── */

function ManageStatsStrip({ stats }: { stats: LoreEventStats }) {
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

/* ─── Manage-view table row ─────────────────────────────────────────────── */

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

/* ─── Division pill ───────────────────────────────────────────────────── */

function DivisionPill({
  label, active, onClick, color, count,
}: { label: string; active: boolean; onClick: () => void; color: string; count?: number }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        background: active ? `${color}33` : 'transparent',
        color: active ? color : 'var(--muted)',
        border: `1px solid ${active ? color : 'rgba(255,255,255,0.1)'}`,
        borderRadius: 12,
        padding: '3px 10px',
        fontSize: 11,
        fontWeight: active ? 600 : 400,
        cursor: 'pointer',
      }}
    >
      {label}{count != null ? ` · ${count}` : ''}
    </button>
  )
}

/* ─── Add event form ──────────────────────────────────────────────────── */

function AddEventForm({ onCancel, onCreated }: { onCancel: () => void; onCreated: () => void }) {
  const today = new Date().toISOString().slice(0, 10)
  const [form, setForm] = useState<LoreEventCreate>({
    event_type: 'launch',
    title: '',
    description: '',
    start_date: today,
    end_date: '',
    division: '',
    confidence: 'confirmed',
    source_type: 'manual',
  })
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const submit = async () => {
    if (!form.title.trim()) { setErr('Title is required'); return }
    setSaving(true); setErr(null)
    try {
      await api.loreEventCreate({
        event_type: form.event_type,
        title: form.title.trim(),
        description: (form.description || '').trim() || null,
        start_date: form.start_date,
        end_date: form.end_date || null,
        division: form.division || null,
        confidence: form.confidence || 'confirmed',
        source_type: form.source_type || 'manual',
      })
      onCreated()
    } catch (e: any) {
      setErr(e?.message || 'Create failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="card" style={{ borderLeft: '3px solid #22c55e' }}>
      <div className="card-title" style={{ marginBottom: 8 }}>New event</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 8, fontSize: 12 }}>
        <label style={lblStyle}>Type
          <select value={form.event_type} onChange={(e) => setForm({ ...form, event_type: e.target.value })} style={selStyle}>
            {EVENT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <label style={lblStyle}>Start date
          <input type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} style={dateInputStyle} />
        </label>
        <label style={lblStyle}>End date (optional)
          <input type="date" value={form.end_date || ''} onChange={(e) => setForm({ ...form, end_date: e.target.value })} style={dateInputStyle} />
        </label>
        <label style={lblStyle}>Division
          <select value={form.division || ''} onChange={(e) => setForm({ ...form, division: e.target.value })} style={selStyle}>
            <option value="">(company-wide)</option>
            {DIVISIONS.map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
        </label>
        <label style={lblStyle}>Confidence
          <select value={form.confidence} onChange={(e) => setForm({ ...form, confidence: e.target.value as LoreConfidence })} style={selStyle}>
            {CONFIDENCES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
      </div>
      <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
        <input
          placeholder="Title"
          value={form.title}
          onChange={(e) => setForm({ ...form, title: e.target.value })}
          style={{ ...txtStyle, fontSize: 13 }}
          autoFocus
        />
        <textarea
          placeholder="Description (optional)"
          value={form.description || ''}
          onChange={(e) => setForm({ ...form, description: e.target.value })}
          style={{ ...txtStyle, minHeight: 60, resize: 'vertical', fontFamily: 'inherit' }}
        />
      </div>
      {err && <div style={{ color: '#ef4444', fontSize: 11, marginTop: 6 }}>{err}</div>}
      <div style={{ marginTop: 10, display: 'flex', gap: 8 }}>
        <button type="button" onClick={submit} disabled={saving} style={btnStyle('#22c55e')}>
          {saving ? 'Saving…' : 'Create event'}
        </button>
        <button type="button" onClick={onCancel} disabled={saving} style={btnStyle('#9fb0d4')}>Cancel</button>
      </div>
    </section>
  )
}
