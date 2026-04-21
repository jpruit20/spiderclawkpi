import { useEffect, useState } from 'react'
import { ComposedChart, Line, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, CartesianGrid, Legend } from 'recharts'
import { motion, AnimatePresence } from 'framer-motion'
import { api, ApiError } from '../lib/api'
import type { CookTimelineResponse } from '../lib/types'

type Props = {
  /** Pass a MAC directly, OR pass a hashed device_id and we'll resolve it. */
  mac?: string
  deviceId?: string
  lookbackHours?: number
  /** When true, renders as a full-screen modal with backdrop + close button. When false, renders inline. */
  modal?: boolean
  onClose?: () => void
  height?: number
}

function fmtTime(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric',
    hour: 'numeric', minute: '2-digit',
  })
}

function fmtDuration(startIso: string | null, endIso: string | null): string {
  if (!startIso || !endIso) return '—'
  const ms = new Date(endIso).getTime() - new Date(startIso).getTime()
  if (ms < 0) return '—'
  const mins = Math.round(ms / 60000)
  if (mins < 60) return `${mins}m`
  const h = Math.floor(mins / 60)
  const m = mins % 60
  return m ? `${h}h ${m}m` : `${h}h`
}

export function CookTimelineChart({ mac: macProp, deviceId, lookbackHours = 24, modal = false, onClose, height = 340 }: Props) {
  const [data, setData] = useState<CookTimelineResponse | null>(null)
  const [resolvedMac, setResolvedMac] = useState<string | null>(macProp ?? null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // If called with deviceId instead of mac, resolve device_id → mac first.
  useEffect(() => {
    if (macProp) { setResolvedMac(macProp); return }
    if (!deviceId) return
    let cancelled = false
    api.firmwareDeviceIdResolveMac(deviceId)
      .then(r => { if (!cancelled) setResolvedMac(r.mac) })
      .catch(e => { if (!cancelled) setError(e instanceof ApiError ? e.message : 'Failed to resolve device id') })
    return () => { cancelled = true }
  }, [macProp, deviceId])

  useEffect(() => {
    if (!resolvedMac) return
    let cancelled = false
    setLoading(true)
    setError(null)
    api.firmwareDeviceCookTimeline(resolvedMac, lookbackHours)
      .then(r => { if (!cancelled) setData(r) })
      .catch(e => { if (!cancelled) setError(e instanceof ApiError ? e.message : 'Failed to load cook timeline') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [resolvedMac, lookbackHours])

  const chartData = (data?.points || []).map(p => ({
    ts: p.ts ? new Date(p.ts).getTime() : 0,
    label: p.ts ? new Date(p.ts).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' }) : '',
    current_temp: p.current_temp,
    target_temp: p.target_temp,
    intensity: p.intensity,
  }))

  const inner = (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10 }}>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.8, fontWeight: 600 }}>
            Cook timeline · {resolvedMac ? `MAC ${resolvedMac}` : deviceId ? `device ${deviceId.slice(0, 10)}…` : ''}
          </div>
          <div style={{ fontSize: 13, marginTop: 4 }}>
            {!resolvedMac && deviceId ? 'Resolving device…' :
             loading ? 'Loading…' : error ? <span style={{ color: 'var(--red, #ef4444)' }}>Error: {error}</span> :
              data && data.cook_start_ts ? (
                <span>
                  {data.is_active ? <strong style={{ color: '#10b981' }}>● Active cook</strong> : <span style={{ color: 'var(--muted)' }}>Completed</span>}
                  {' · '}
                  Started {fmtTime(data.cook_start_ts)}
                  {' · '}
                  Duration {fmtDuration(data.cook_start_ts, data.cook_end_ts)}
                  {data.target_set_at ? ` · Target last set ${fmtTime(data.target_set_at)}` : ''}
                </span>
              ) : (
                <span style={{ color: 'var(--muted)' }}>No cook detected in the last {lookbackHours}h (no samples crossed {data?.live_fire_threshold_f ?? 140}°F)</span>
              )
            }
          </div>
        </div>
        {modal && onClose ? (
          <button onClick={onClose} style={{
            padding: '6px 12px', fontSize: 12, background: 'transparent',
            border: '1px solid var(--border)', borderRadius: 6, cursor: 'pointer', color: 'var(--fg)',
          }}>Close</button>
        ) : null}
      </div>

      {chartData.length > 1 ? (
        <div style={{ marginTop: 12, width: '100%', height }}>
          <ResponsiveContainer>
            <ComposedChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
              <XAxis dataKey="label" tick={{ fontSize: 10, fill: 'var(--muted)' }} />
              <YAxis yAxisId="temp" orientation="left" tick={{ fontSize: 10, fill: 'var(--muted)' }} domain={['auto', 'auto']} label={{ value: '°F', position: 'insideLeft', offset: 10, fill: 'var(--muted)', fontSize: 10 }} />
              <YAxis yAxisId="fan"  orientation="right" tick={{ fontSize: 10, fill: 'var(--muted)' }} domain={[0, 100]} label={{ value: 'fan %', position: 'insideRight', offset: 10, fill: 'var(--muted)', fontSize: 10 }} />
              <Tooltip
                contentStyle={{ background: 'var(--bg-elevated, #0f172a)', border: '1px solid var(--border)', fontSize: 12 }}
                formatter={(val: unknown, name: string) => {
                  if (val == null) return '—'
                  if (name === 'intensity') return [`${Number(val).toFixed(0)}%`, 'Fan']
                  return [`${Number(val).toFixed(0)}°F`, name === 'current_temp' ? 'Pit' : 'Target']
                }}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} iconSize={10} />
              <ReferenceLine yAxisId="temp" y={data?.live_fire_threshold_f ?? 140} stroke="#f59e0b" strokeDasharray="4 4" label={{ value: 'fire ≥140°F', fontSize: 9, fill: '#f59e0b', position: 'insideTopRight' }} />
              <Area yAxisId="fan" type="monotone" dataKey="intensity" name="intensity" stroke="#64748b" fill="#64748b" fillOpacity={0.15} strokeWidth={1} />
              <Line yAxisId="temp" type="monotone" dataKey="target_temp" name="target_temp" stroke="#3b82f6" strokeDasharray="4 4" strokeWidth={1.5} dot={false} />
              <Line yAxisId="temp" type="monotone" dataKey="current_temp" name="current_temp" stroke="#ef4444" strokeWidth={2} dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      ) : loading ? null : (
        <div style={{ marginTop: 12, fontSize: 12, color: 'var(--muted)', padding: 40, textAlign: 'center', border: '1px dashed var(--border)', borderRadius: 8 }}>
          Not enough samples to render a chart.
        </div>
      )}
    </div>
  )

  if (!modal) return <section className="card">{inner}</section>

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        onClick={onClose}
        style={{
          position: 'fixed', inset: 0, zIndex: 1000,
          background: 'rgba(0,0,0,0.65)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          padding: 20,
        }}
      >
        <motion.div
          initial={{ y: 24, opacity: 0, scale: 0.98 }} animate={{ y: 0, opacity: 1, scale: 1 }} exit={{ y: 20, opacity: 0 }}
          transition={{ type: 'spring', stiffness: 240, damping: 26 }}
          onClick={e => e.stopPropagation()}
          style={{
            width: '100%', maxWidth: 860,
            background: 'var(--bg-elevated, #0f172a)',
            border: '1px solid var(--border)',
            borderRadius: 12, padding: 20,
          }}
        >
          {inner}
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}
