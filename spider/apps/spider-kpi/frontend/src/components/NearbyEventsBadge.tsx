import { useEffect, useState } from 'react'

import { api } from '../lib/api'
import type { LoreEvent } from '../lib/types'

/**
 * NearbyEventsBadge — renders "near event: X" annotations for a given
 * (date, division) pair. Fetches lore events within ±`windowDays` and
 * matching either `division` or company-wide (division IS NULL).
 *
 * Intended as an inline suffix on Anomaly / IssueSignal / insight cards:
 *
 *   <AnomalyBar metric="revenue" businessDate="2026-04-12" ... />
 *   <NearbyEventsBadge businessDate="2026-04-12" division="marketing" />
 *
 * The whole point of building the event timeline was to contextualize
 * the anomaly surface — "revenue dropped z=-3.1 on Apr 12" is a lot
 * less mysterious when paired with "near: Huntsman shipment delayed
 * Apr 7-9".
 */

type Props = {
  businessDate: string
  division?: string | null
  windowDays?: number
  /** Max pins to display inline. Extras collapse into "+N more". Default 2. */
  maxInline?: number
}

function addDays(iso: string, days: number): string {
  const d = new Date(iso + 'T00:00:00Z')
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

// Convert any date-ish string (YYYY-MM-DD or full ISO timestamp) to YYYY-MM-DD.
function toBusinessDate(s: string): string {
  return s.length >= 10 ? s.slice(0, 10) : s
}

// Normalize heterogeneous division strings (dashboard slugs, DECI free-form,
// DB snake_case) to the lore-events DB taxonomy. Lore uses: marketing,
// commercial, support, product_engineering, executive, (NULL = company-wide).
function normalizeDivision(raw: string | null | undefined): string | null {
  if (!raw) return null
  const k = raw.toLowerCase().trim()
    .replace(/[\s/_-]+/g, '_') // unify separators
  if (k === 'customer_experience' || k === 'cx' || k === 'support') return 'support'
  if (k === 'product_engineering' || k === 'product' || k === 'engineering') return 'product_engineering'
  if (k === 'marketing') return 'marketing'
  if (k === 'commercial' || k === 'revenue' || k === 'finance') return 'commercial'
  if (k === 'executive' || k === 'exec') return 'executive'
  if (k === 'operations') return 'operations'
  if (k === 'production_manufacturing' || k === 'production' || k === 'manufacturing') return 'production_manufacturing'
  return k
}

const TYPE_COLOR: Record<string, string> = {
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

export function NearbyEventsBadge({ businessDate, division, windowDays = 3, maxInline = 2 }: Props) {
  const [events, setEvents] = useState<LoreEvent[] | null>(null)
  const [hoverOpen, setHoverOpen] = useState(false)

  const normDivision = normalizeDivision(division)
  const bizDate = toBusinessDate(businessDate)

  useEffect(() => {
    let cancel = false
    const ctrl = new AbortController()
    const start = addDays(bizDate, -windowDays)
    const end = addDays(bizDate, windowDays)
    // Query everything in the window; we'll client-side filter for
    // same-division OR company-wide (division IS NULL). A single call
    // without the `division` filter returns both, which is what we want —
    // the backend filter would exclude company-wide events when a
    // division is passed.
    api.loreEvents({ start, end, limit: 50 }, ctrl.signal)
      .then((r) => {
        if (cancel) return
        const filtered = r.events.filter((ev) => {
          if (!normDivision) return true
          return ev.division === normDivision || ev.division == null
        })
        setEvents(filtered)
      })
      .catch(() => { if (!cancel) setEvents([]) })
    return () => { cancel = true; ctrl.abort() }
  }, [bizDate, normDivision, windowDays])

  if (!events || events.length === 0) return null

  const inline = events.slice(0, maxInline)
  const extra = events.length - inline.length

  return (
    <span
      style={{ display: 'inline-flex', gap: 4, alignItems: 'center', flexWrap: 'wrap', position: 'relative' }}
      onMouseEnter={() => setHoverOpen(true)}
      onMouseLeave={() => setHoverOpen(false)}
    >
      <span style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.3 }}>
        near:
      </span>
      {inline.map((ev) => {
        const color = TYPE_COLOR[ev.event_type] || TYPE_COLOR.other
        return (
          <span
            key={ev.id}
            title={`${ev.title} · ${ev.event_type} · ${ev.start_date}${ev.end_date && ev.end_date !== ev.start_date ? ` → ${ev.end_date}` : ''}${ev.division ? ` · ${ev.division}` : ''}`}
            style={{
              fontSize: 11,
              padding: '1px 6px',
              borderRadius: 3,
              background: `${color}22`,
              color,
              border: `1px solid ${color}55`,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              maxWidth: 220,
              display: 'inline-block',
            }}
          >
            {ev.title.length > 40 ? `${ev.title.slice(0, 37)}…` : ev.title}
          </span>
        )
      })}
      {extra > 0 && (
        <span style={{ fontSize: 10, color: 'var(--muted)' }}>
          +{extra} more
        </span>
      )}
      {hoverOpen && events.length > inline.length && (
        <div
          style={{
            position: 'absolute',
            top: 'calc(100% + 2px)',
            left: 0,
            zIndex: 40,
            minWidth: 260,
            maxWidth: 380,
            background: 'var(--bg-elevated, #1a1d24)',
            border: '1px solid rgba(255,255,255,0.1)',
            borderRadius: 6,
            padding: 8,
            display: 'grid',
            gap: 6,
            boxShadow: '0 8px 24px rgba(0,0,0,0.35)',
          }}
        >
          {events.slice(0, 8).map((ev) => {
            const color = TYPE_COLOR[ev.event_type] || TYPE_COLOR.other
            return (
              <div key={ev.id} style={{ display: 'flex', gap: 6, alignItems: 'baseline', fontSize: 11 }}>
                <span style={{
                  width: 6, height: 6, borderRadius: '50%', background: color, flexShrink: 0,
                  marginTop: 4,
                }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ color: 'var(--text)' }}>{ev.title}</div>
                  <div style={{ fontSize: 10, color: 'var(--muted)' }}>
                    {ev.start_date}{ev.end_date && ev.end_date !== ev.start_date ? ` → ${ev.end_date}` : ''}
                    {' · '}{ev.event_type}
                    {ev.division ? ` · ${ev.division}` : ''}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </span>
  )
}
