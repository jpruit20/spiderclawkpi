import { useEffect, useMemo, useRef, useState } from 'react'

import { api } from '../lib/api'
import type { LoreEvent, LoreConfidence } from '../lib/types'

/**
 * EventTimelineStrip — a thin horizontal band of event pins that sits
 * under any time-series chart and shares its x-axis. Hovering a pin
 * shows the event title, description, and span; clicking calls
 * onSelectEvent so the page can open an edit drawer.
 *
 * Why a separate strip (vs. drawing ReferenceAreas inside the chart):
 *   - Works on top of every chart library, not just the ones we already
 *     use ComposedChart with
 *   - Doesn't get clipped by ResponsiveContainer weirdness
 *   - Lets multiple events stack without colliding with gridlines
 *
 * Usage:
 *   <EventTimelineStrip start="2026-01-01" end="2026-04-19" division="marketing" />
 */

type Props = {
  start: string
  end: string
  /** Filter by division. Pass "company" for company-wide only, undefined
   *  for everything that overlaps the range regardless of division. */
  division?: string
  /** Height of the strip in px. Default 36 — enough for single-row stack. */
  height?: number
  /** Called when the user clicks a pin. */
  onSelectEvent?: (event: LoreEvent) => void
  /** Render an explicit "Loading…" and empty-state label. Default true. */
  showStates?: boolean
}

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

const CONFIDENCE_OPACITY: Record<LoreConfidence, number> = {
  confirmed: 1,
  inferred:  0.7,
  rumored:   0.45,
}

function dayMs(): number {
  return 1000 * 60 * 60 * 24
}

function toMs(d: string): number {
  // YYYY-MM-DD interpreted at UTC midnight to avoid TZ drift in %-math.
  return new Date(d + 'T00:00:00Z').getTime()
}

function fmtDateRange(e: LoreEvent): string {
  if (!e.end_date || e.end_date === e.start_date) return e.start_date
  return `${e.start_date} → ${e.end_date}`
}

export function EventTimelineStrip({
  start,
  end,
  division,
  height = 36,
  onSelectEvent,
  showStates = true,
}: Props) {
  const [events, setEvents] = useState<LoreEvent[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setLoading(true)
    setError(null)
    api.loreEvents({ start, end, division, limit: 500 }, ctrl.signal)
      .then((res) => {
        setEvents(res.events)
        setLoading(false)
      })
      .catch((e) => {
        if (ctrl.signal.aborted) return
        setError(e?.message || 'Failed to load events')
        setLoading(false)
      })
    return () => ctrl.abort()
  }, [start, end, division])

  const rangeMs = useMemo(() => {
    const s = toMs(start)
    const e = toMs(end)
    return { s, e, span: Math.max(1, e - s) }
  }, [start, end])

  if (loading && showStates) {
    return <div className="state-message" style={{ fontSize: 11, color: 'var(--muted)' }}>Loading events…</div>
  }
  if (error && showStates) {
    return <div className="state-message error" style={{ fontSize: 11 }}>{error}</div>
  }
  if (!events || events.length === 0) {
    if (!showStates) return null
    return (
      <div style={{ fontSize: 11, color: 'var(--muted)', padding: '4px 0' }}>
        No events recorded in this range.
      </div>
    )
  }

  // Clamp each event to the visible window, compute left/width as %.
  const pins = events.map((ev) => {
    const s = Math.max(toMs(ev.start_date), rangeMs.s)
    const e = Math.min(
      ev.end_date ? toMs(ev.end_date) + dayMs() : toMs(ev.start_date) + dayMs(),
      rangeMs.e + dayMs(),
    )
    const leftPct = ((s - rangeMs.s) / rangeMs.span) * 100
    const widthPct = Math.max(0.6, ((e - s) / rangeMs.span) * 100)
    const color = EVENT_TYPE_COLOR[ev.event_type] || EVENT_TYPE_COLOR.other
    const opacity = CONFIDENCE_OPACITY[ev.confidence as LoreConfidence] ?? 1
    return { ev, leftPct, widthPct, color, opacity }
  })

  return (
    <div
      style={{
        position: 'relative',
        height,
        width: '100%',
        background: 'rgba(255,255,255,0.02)',
        border: '1px solid rgba(255,255,255,0.05)',
        borderRadius: 4,
        overflow: 'hidden',
      }}
    >
      {pins.map(({ ev, leftPct, widthPct, color, opacity }) => {
        const isPoint = widthPct < 1.2
        const title = [
          `${ev.title}`,
          fmtDateRange(ev),
          ev.description ? `\n${ev.description}` : '',
          `\n${ev.event_type} · ${ev.confidence}${ev.division ? ` · ${ev.division}` : ''}`,
        ].join('\n').trim()

        return (
          <button
            key={ev.id}
            type="button"
            title={title}
            onClick={() => onSelectEvent?.(ev)}
            style={{
              position: 'absolute',
              left: `${leftPct}%`,
              width: isPoint ? 3 : `${widthPct}%`,
              top: 4,
              bottom: 4,
              background: isPoint ? color : `${color}55`,
              border: `1px solid ${color}`,
              borderRadius: isPoint ? 2 : 3,
              opacity,
              cursor: onSelectEvent ? 'pointer' : 'default',
              padding: 0,
              fontSize: 10,
              color: '#fff',
              textAlign: 'left',
              overflow: 'hidden',
              whiteSpace: 'nowrap',
              textOverflow: 'ellipsis',
              paddingLeft: isPoint ? 0 : 4,
              lineHeight: `${height - 10}px`,
            }}
          >
            {!isPoint && <span style={{ fontWeight: 500 }}>{ev.title}</span>}
          </button>
        )
      })}
    </div>
  )
}
