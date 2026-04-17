import { useEffect, useMemo, useState } from 'react'
import {
  CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { ApiError, api } from '../lib/api'
import type { ClickUpTimelineEvent } from '../lib/types'

/**
 * Overlays ClickUp task events (campaign launch dates, firmware releases,
 * engineering task completions) as vertical reference lines on a primary
 * business-metric series.
 *
 * Use cases:
 *   Marketing         → revenue line + ClickUp Marketing-space due dates
 *   Product/Engineering → cook success rate + firmware-keyword completions
 *   Customer Experience → ticket creation rate + CX-related task completions
 *
 * The caller passes the primary series it already has; this component only
 * fetches the ClickUp timeline.
 */
export type PrimaryPoint = { date: string; value: number }

type Props = {
  title: string
  subtitle?: string
  primarySeries: PrimaryPoint[]
  primaryLabel: string
  primaryColor?: string
  clickupFilter: {
    space_id?: string
    keyword?: string
    event_types?: 'due' | 'completed' | 'due,completed'
    priorities?: string  // csv, e.g. "urgent,high"
    division?: string           // exact custom-field match, e.g. "Marketing"
    customer_impact?: string    // exact custom-field match, e.g. "Direct"
    category?: string           // exact custom-field match, e.g. "Firmware"
    days?: number
  }
  /** Color for reference lines when an event color isn't priority-derived. */
  eventColor?: string
  height?: number
  /** Optional horizontal benchmark line (e.g. cook-success median). */
  benchmarkValue?: number
  benchmarkLabel?: string
  benchmarkColor?: string
}

const PRIORITY_COLOR: Record<string, string> = {
  urgent: '#ef4444',
  high: '#f59e0b',
  normal: '#6b7280',
  low: '#9ca3af',
}

function eventColor(ev: ClickUpTimelineEvent, fallback: string): string {
  const p = (ev.priority || '').toLowerCase()
  return PRIORITY_COLOR[p] || fallback
}

export function ClickUpOverlayChart({
  title,
  subtitle,
  primarySeries,
  primaryLabel,
  primaryColor = 'var(--blue)',
  clickupFilter,
  eventColor: fallbackEventColor = 'var(--orange)',
  height = 180,
  benchmarkValue,
  benchmarkLabel,
  benchmarkColor = 'rgba(148, 163, 184, 0.55)',
}: Props) {
  const [events, setEvents] = useState<ClickUpTimelineEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api.clickupTimeline(clickupFilter)
      .then(r => { if (!cancelled) setEvents(r.events) })
      .catch(err => { if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load ClickUp timeline') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(clickupFilter)])

  const chartData = useMemo(() => {
    return primarySeries.map(p => ({ date: p.date, value: p.value }))
  }, [primarySeries])

  // Align ClickUp events to dates that exist in the primary series so recharts
  // can place the ReferenceLine at the correct x. Drop events outside window.
  const primaryDateSet = useMemo(() => new Set(primarySeries.map(p => p.date)), [primarySeries])
  const overlayEvents = useMemo(() => {
    return events
      .filter(e => primaryDateSet.has(e.business_date))
      .map(e => ({ ...e, x: e.business_date }))
  }, [events, primaryDateSet])

  const eventsOutOfWindow = events.length - overlayEvents.length

  return (
    <section className="card">
      <div className="venom-panel-head">
        <strong>{title}</strong>
        <span className="venom-panel-hint">
          {loading ? 'loading events…' : `${overlayEvents.length} ClickUp events in window`}
        </span>
      </div>

      {subtitle && (
        <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>{subtitle}</p>
      )}

      {error && <div className="state-message error">{error}</div>}

      {chartData.length === 0 && !loading && !error && (
        <div className="state-message">No primary-metric data in window.</div>
      )}

      {chartData.length > 0 && (
        <>
          <ResponsiveContainer width="100%" height={height}>
            <ComposedChart data={chartData} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
              <CartesianGrid stroke="rgba(255,255,255,0.04)" strokeDasharray="3 3" />
              <XAxis dataKey="date" tick={{ fontSize: 10 }} stroke="var(--muted)" tickFormatter={(d: string) => (d || '').slice(5)} />
              <YAxis tick={{ fontSize: 10 }} stroke="var(--muted)" />
              <Tooltip
                contentStyle={{ background: '#111', border: '1px solid #333', fontSize: 12 }}
                formatter={(value: number) => [value, primaryLabel]}
              />
              {overlayEvents.map((ev, i) => (
                <ReferenceLine
                  key={`${ev.task_id}-${i}`}
                  x={ev.x}
                  stroke={eventColor(ev, fallbackEventColor)}
                  strokeDasharray="2 2"
                  strokeOpacity={0.7}
                  strokeWidth={1}
                />
              ))}
              {benchmarkValue != null && (
                <ReferenceLine
                  y={benchmarkValue}
                  stroke={benchmarkColor}
                  strokeDasharray="4 3"
                  strokeWidth={1}
                  label={benchmarkLabel ? { value: benchmarkLabel, position: 'insideTopLeft', fill: benchmarkColor, fontSize: 10 } : undefined}
                />
              )}
              <Line
                type="monotone"
                dataKey="value"
                stroke={primaryColor}
                strokeWidth={2}
                dot={false}
                name={primaryLabel}
              />
            </ComposedChart>
          </ResponsiveContainer>

          {overlayEvents.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>
                Event markers (hover on the chart line to align):
              </div>
              <div className="stack-list compact" style={{ maxHeight: 160, overflowY: 'auto' }}>
                {overlayEvents.slice().reverse().slice(0, 12).map((ev) => {
                  const color = eventColor(ev, fallbackEventColor)
                  const content = (
                    <>
                      <div className="item-head">
                        <strong style={{ fontSize: 11 }}>
                          <span style={{ color, marginRight: 6 }}>
                            {ev.event_type === 'completed' ? '✓' : '●'}
                          </span>
                          {(ev.title || '').slice(0, 90)}
                        </strong>
                        <span style={{ fontSize: 10, color: 'var(--muted)' }}>{ev.business_date}</span>
                      </div>
                      <p style={{ fontSize: 10, color: 'var(--muted)' }}>
                        {[ev.space_name, ev.list_name].filter(Boolean).join(' · ')}
                        {ev.priority && ` · ${ev.priority}`}
                        {ev.status && ` · ${ev.status}`}
                        {` · ${ev.event_type}`}
                      </p>
                    </>
                  )
                  if (ev.url) {
                    return (
                      <a
                        key={ev.task_id}
                        href={ev.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="list-item status-muted"
                        style={{ textDecoration: 'none', color: 'inherit', borderLeft: `3px solid ${color}` }}
                      >
                        {content}
                      </a>
                    )
                  }
                  return (
                    <div key={ev.task_id} className="list-item status-muted" style={{ borderLeft: `3px solid ${color}` }}>
                      {content}
                    </div>
                  )
                })}
              </div>
              {eventsOutOfWindow > 0 && (
                <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 4 }}>
                  {eventsOutOfWindow} event(s) fell outside the primary-metric window
                </div>
              )}
            </div>
          )}
        </>
      )}
    </section>
  )
}
