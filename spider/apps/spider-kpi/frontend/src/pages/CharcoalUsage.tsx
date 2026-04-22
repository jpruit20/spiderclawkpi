import { FormEvent, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Bar, BarChart, CartesianGrid, Legend, Line, ComposedChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { ApiError, api } from '../lib/api'
import type {
  CharcoalDeviceSessionsResponse, CharcoalFleetAggregateResponse, CharcoalFleetFilters,
  CharcoalJITListResponse, CharcoalJITSubscription,
  CharcoalPartnerProduct, CharcoalPartnerProductsResponse,
} from '../lib/api'
import { fmtInt } from '../lib/format'
import {
  DEFAULT_FUEL_PARAMS,
  estimateAmbientTempF,
  estimateSessionFuel,
  forecastShipments,
  predictFuelType,
  rollingBurnRate,
  rollupFuel,
  thermalDemandBtuPerHr,
  type CookFuelEstimate,
  type FuelParams,
  type FuelType,
  type FuelTypePrediction,
} from '../lib/charcoalModel'

type Tab = 'device' | 'fleet' | 'jit' | 'enrollment'

const TABS: Array<{ key: Tab; label: string; desc: string }> = [
  { key: 'device', label: 'Per device', desc: 'MAC lookup → burn history' },
  { key: 'fleet', label: 'Fleet', desc: 'Date range + cohort filters' },
  { key: 'jit', label: 'JIT program', desc: 'Auto-ship forecast' },
  { key: 'enrollment', label: 'Program enrollment', desc: 'Subscribe a device to auto-ship' },
]

/* ═══════════════════════════════════════════════════════════════════
   ASSUMPTIONS PANEL — live-tunable model parameters
   ═══════════════════════════════════════════════════════════════════ */

function AssumptionsPanel({
  params, setParams,
}: { params: FuelParams; setParams: (p: FuelParams) => void }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <section className="card" style={{ borderLeft: '3px solid var(--muted)' }}>
      <div className="venom-panel-head" style={{ alignItems: 'center' }}>
        <div>
          <strong>Model assumptions</strong>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            Lump {params.fuelEnergy.lump.toLocaleString()} BTU/lb · briquette {params.fuelEnergy.briquette.toLocaleString()} BTU/lb · combustion efficiency {(params.combustionEfficiency * 100).toFixed(0)}%
          </div>
        </div>
        <button
          type="button"
          onClick={() => setExpanded(x => !x)}
          style={{
            fontSize: 11, padding: '4px 10px', background: 'transparent',
            border: '1px solid var(--border)', borderRadius: 6,
            color: 'var(--muted)', cursor: 'pointer',
          }}
        >
          {expanded ? 'Hide ▲' : 'Tune ▼'}
        </button>
      </div>
      {expanded ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, marginTop: 10 }}>
          <div>
            <label style={{ fontSize: 11, color: 'var(--muted)' }}>Lump BTU/lb</label>
            <input
              type="number" value={params.fuelEnergy.lump}
              onChange={e => setParams({
                ...params,
                fuelEnergy: { ...params.fuelEnergy, lump: Number(e.target.value) || 0 },
              })}
              className="deci-input" style={{ width: '100%', fontSize: 12 }}
            />
            <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 2 }}>
              Oak 8,800 · hickory 9,200 · median 9,000
            </div>
          </div>
          <div>
            <label style={{ fontSize: 11, color: 'var(--muted)' }}>Briquette BTU/lb</label>
            <input
              type="number" value={params.fuelEnergy.briquette}
              onChange={e => setParams({
                ...params,
                fuelEnergy: { ...params.fuelEnergy, briquette: Number(e.target.value) || 0 },
              })}
              className="deci-input" style={{ width: '100%', fontSize: 12 }}
            />
            <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 2 }}>
              Kingsford Original ≈ 6,200 · premium natural ≈ 7,000
            </div>
          </div>
          <div>
            <label style={{ fontSize: 11, color: 'var(--muted)' }}>Combustion efficiency</label>
            <input
              type="number" step="0.05" min="0.1" max="1"
              value={params.combustionEfficiency}
              onChange={e => setParams({
                ...params,
                combustionEfficiency: Math.max(0.1, Math.min(1, Number(e.target.value) || 0.6)),
              })}
              className="deci-input" style={{ width: '100%', fontSize: 12 }}
            />
            <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 2 }}>
              Weber kettle 0.55–0.65 · kamado 0.75–0.85
            </div>
          </div>
        </div>
      ) : null}
    </section>
  )
}

/* ═══════════════════════════════════════════════════════════════════
   TAB 1 — PER-DEVICE
   ═══════════════════════════════════════════════════════════════════ */

function DeviceTab({ params }: { params: FuelParams }) {
  const [macInput, setMacInput] = useState('fcb467f9b456')
  const [submittedMac, setSubmittedMac] = useState<string | null>(null)
  const [data, setData] = useState<CharcoalDeviceSessionsResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [assumedFuel, setAssumedFuel] = useState<FuelType>('lump')

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setSubmittedMac(macInput.trim())
  }

  useEffect(() => {
    if (!submittedMac) return
    const ctl = new AbortController()
    setLoading(true)
    setError(null)
    api.charcoalDeviceSessions(submittedMac, 730, ctl.signal)
      .then(r => { setData(r); setError(null) })
      .catch(e => { if (e.name !== 'AbortError') setError(e instanceof ApiError ? e.message : String(e)) })
      .finally(() => setLoading(false))
    return () => ctl.abort()
  }, [submittedMac])

  const estimates = useMemo<CookFuelEstimate[]>(() => {
    if (!data) return []
    return data.sessions
      .map(s => estimateSessionFuel(s, params))
      .filter((e): e is CookFuelEstimate => e != null)
      .sort((a, b) => (a.session_start || '').localeCompare(b.session_start || ''))
  }, [data, params])

  const rollup = useMemo(() => rollupFuel(estimates), [estimates])
  const burn = useMemo(() => rollingBurnRate(estimates, 90), [estimates])

  // Fuel-type prediction aggregated across all this device's cooks.
  // We don't have per-session time-series on the /sessions response
  // yet (actual_temp_time_series would balloon the payload), so the
  // heuristic runs on duration + target temp alone. Confidence stays
  // capped at 'medium'; extending the endpoint to return the series
  // would bump it to 'high' for cooks where we have live samples.
  const fuelPredictionRollup = useMemo(() => {
    if (!data || data.sessions.length === 0) return null
    const preds: FuelTypePrediction[] = data.sessions.map(s => predictFuelType(s))
    // Weight each prediction by cook duration — long cooks count more.
    const totalHours = data.sessions.reduce((s, x) => s + x.duration_hours, 0)
    if (totalHours === 0) return null
    const wLump = data.sessions.reduce((s, x, i) => s + preds[i].p_lump * x.duration_hours, 0) / totalHours
    const cooksHighConf = preds.filter(p => p.confidence === 'high').length
    return {
      p_lump: wLump,
      p_briquette: 1 - wLump,
      cooks_scored: preds.length,
      cooks_high_conf: cooksHighConf,
    }
  }, [data])

  // Ambient estimate for the most recent cook (display only — the
  // thermal model can optionally apply it when we enable the tax).
  const recentAmbient = useMemo(() => {
    if (!data || data.sessions.length === 0) return null
    return estimateAmbientTempF(data.sessions[0].session_start)
  }, [data])

  const chartData = estimates.map(e => ({
    session_start: e.session_start,
    date: e.session_start ? e.session_start.slice(0, 10) : '',
    avg_temp: e.avg_temp_f,
    lump: Number(e.lump_lb.toFixed(2)),
    briquette: Number(e.briquette_lb.toFixed(2)),
    hours: Number(e.duration_hours.toFixed(1)),
  }))

  return (
    <>
      <section className="card">
        <form onSubmit={submit} style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <label style={{ flex: '1 1 300px' }}>
            <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>MAC address</div>
            <input
              type="text" value={macInput}
              onChange={e => setMacInput(e.target.value)}
              placeholder="fcb467f9b456 or fc:b4:67:f9:b4:56"
              className="deci-input"
              style={{ width: '100%', fontSize: 13, fontFamily: 'ui-monospace, monospace' }}
            />
          </label>
          <div>
            <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>Assumed fuel</div>
            <select
              value={assumedFuel}
              onChange={e => setAssumedFuel(e.target.value as FuelType)}
              className="deci-input" style={{ fontSize: 13 }}
            >
              <option value="lump">Lump hardwood</option>
              <option value="briquette">Briquettes</option>
            </select>
          </div>
          <button type="submit" className="range-button active" disabled={loading}>
            {loading ? 'Looking up…' : 'Analyze'}
          </button>
        </form>
        <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 8 }}>
          Tip: the office grill is <code>fcb467f9b456</code>. We estimate both lump + briquette per cook; the dropdown picks which point value to headline.
        </div>
      </section>

      {error ? <section className="card"><div className="state-message error">{error}</div></section> : null}

      {data && data.sessions.length === 0 ? (
        <section className="card">
          <div className="state-message">{data.note || 'No cook sessions found in the last 2 years.'}</div>
        </section>
      ) : null}

      {data && data.sessions.length > 0 ? (
        <>
          {/* Headline tiles */}
          <section className="card">
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10 }}>
              <Tile label="Cooks (2y)" value={fmtInt(rollup.cooks)} sub={`${rollup.total_hours.toFixed(0)} cook hours`} />
              <Tile
                label={`Total ${assumedFuel} (est.)`}
                value={`${(assumedFuel === 'lump' ? rollup.total_lump_lb : rollup.total_briquette_lb).toFixed(1)} lb`}
                sub={`range: ${rollup.total_briquette_lb.toFixed(0)} – ${rollup.total_lump_lb.toFixed(0)} lb`}
              />
              <Tile
                label="Avg cook temp"
                value={rollup.weighted_avg_temp_f != null ? `${rollup.weighted_avg_temp_f.toFixed(0)}°F` : '—'}
                sub="time-weighted across cooks"
              />
              <Tile
                label={`Burn rate (90d, ${assumedFuel})`}
                value={`${(assumedFuel === 'lump' ? burn.lump_lb_per_week : burn.briquette_lb_per_week).toFixed(2)} lb/wk`}
                sub={`${burn.cooks_per_week.toFixed(1)} cooks/week`}
                state="info"
              />
            </div>
            <BagPreview
              lbPerWeek={assumedFuel === 'lump' ? burn.lump_lb_per_week : burn.briquette_lb_per_week}
              fuel={assumedFuel}
            />
          </section>

          {/* Fuel-type prediction + ambient estimate */}
          {(fuelPredictionRollup || recentAmbient) ? (
            <section className="card">
              <div className="venom-panel-head">
                <div>
                  <strong>Model inferences</strong>
                  <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
                    What the thermal model *thinks* about this device, without ground truth.
                    Replace with labelled data once the in-app fuel-type survey lands.
                  </div>
                </div>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10 }}>
                {fuelPredictionRollup ? (
                  <div style={{
                    padding: '10px 12px', border: '1px solid var(--border)', borderRadius: 8,
                    background: fuelPredictionRollup.p_lump >= 0.6
                      ? 'rgba(255, 178, 87, 0.06)'
                      : fuelPredictionRollup.p_lump <= 0.4
                        ? 'rgba(110, 168, 255, 0.06)'
                        : 'rgba(255,255,255,0.02)',
                    borderLeft: `3px solid ${fuelPredictionRollup.p_lump >= 0.6 ? 'var(--orange)' : fuelPredictionRollup.p_lump <= 0.4 ? 'var(--blue)' : 'var(--muted)'}`,
                  }}>
                    <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
                      Predicted fuel (cook-weighted)
                    </div>
                    <div style={{ fontSize: 18, fontWeight: 700, marginTop: 2 }}>
                      {fuelPredictionRollup.p_lump >= 0.6
                        ? <span style={{ color: 'var(--orange)' }}>Lump — {Math.round(fuelPredictionRollup.p_lump * 100)}%</span>
                        : fuelPredictionRollup.p_lump <= 0.4
                          ? <span style={{ color: 'var(--blue)' }}>Briquette — {Math.round(fuelPredictionRollup.p_briquette * 100)}%</span>
                          : <span style={{ color: 'var(--muted)' }}>Mixed / unclear — {Math.round(fuelPredictionRollup.p_lump * 100)}/{Math.round(fuelPredictionRollup.p_briquette * 100)}</span>}
                    </div>
                    <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 4 }}>
                      Heuristic (duration + target temp). {fuelPredictionRollup.cooks_scored} cooks scored
                      {fuelPredictionRollup.cooks_high_conf > 0 ? `, ${fuelPredictionRollup.cooks_high_conf} high-confidence` : ''}.
                    </div>
                  </div>
                ) : null}
                {recentAmbient ? (
                  <div style={{
                    padding: '10px 12px', border: '1px solid var(--border)', borderRadius: 8,
                    background: 'rgba(0,0,0,0.2)',
                  }}>
                    <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
                      Last-cook ambient (est.)
                    </div>
                    <div style={{ fontSize: 18, fontWeight: 700, marginTop: 2 }}>
                      {recentAmbient.ambient_f}°F
                    </div>
                    <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 4 }}>
                      {recentAmbient.note}
                    </div>
                  </div>
                ) : null}
              </div>
              <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 10, lineHeight: 1.5 }}>
                <strong>How the fuel prediction works:</strong> we score each cook by temp profile —
                very long cooks at low temp lean briquette; high-temp sears and highly-variable temp profiles lean lump.
                We don't have ground truth yet, so call these directional hints, not facts.
                Once beta testers start logging actual fuel per cook, we'll retrain the scorer against labelled data
                and bump confidence accordingly.
              </div>
            </section>
          ) : null}

          {/* Per-cook chart */}
          <section className="card">
            <div className="venom-panel-head">
              <div>
                <strong>Per-cook fuel use · {assumedFuel}</strong>
                <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
                  Each bar is one cook session. Line overlay = avg pit temp during that cook.
                </div>
              </div>
            </div>
            <div style={{ height: 260 }}>
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={chartData} margin={{ top: 10, right: 30, left: 0, bottom: 20 }}>
                  <CartesianGrid stroke="rgba(255,255,255,0.05)" strokeDasharray="3 3" />
                  <XAxis dataKey="date" tick={{ fontSize: 10 }} stroke="var(--muted)" />
                  <YAxis yAxisId="lb" tick={{ fontSize: 10 }} stroke="var(--muted)" label={{ value: 'lb', angle: -90, offset: 10, position: 'insideLeft', fill: 'var(--muted)', fontSize: 10 }} />
                  <YAxis yAxisId="temp" orientation="right" tick={{ fontSize: 10 }} stroke="var(--muted)" label={{ value: '°F', angle: 90, offset: 10, position: 'insideRight', fill: 'var(--muted)', fontSize: 10 }} />
                  <Tooltip contentStyle={{ background: '#111', border: '1px solid #333', fontSize: 12 }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Bar yAxisId="lb" dataKey={assumedFuel} fill={assumedFuel === 'lump' ? 'var(--orange)' : '#6ea8ff'} name={`${assumedFuel} lb`} />
                  <Line yAxisId="temp" type="monotone" dataKey="avg_temp" stroke="var(--red)" dot={false} name="avg pit temp °F" strokeWidth={2} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </section>
        </>
      ) : null}
    </>
  )
}

function BagPreview({ lbPerWeek, fuel }: { lbPerWeek: number; fuel: FuelType }) {
  const bagSizes = [10, 20, 40]
  if (lbPerWeek <= 0) return null
  return (
    <div style={{
      marginTop: 12, padding: '10px 12px',
      background: 'rgba(255, 178, 87, 0.06)',
      borderLeft: '3px solid var(--orange)', borderRadius: 6,
      fontSize: 12, color: 'var(--text)',
    }}>
      <strong>At this rate, one bag lasts:</strong>
      <div style={{ marginTop: 6, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        {bagSizes.map(bag => (
          <span key={bag} style={{ color: 'var(--muted)' }}>
            {bag} lb {fuel} → <strong style={{ color: 'var(--orange)' }}>{(bag / lbPerWeek).toFixed(1)} weeks</strong>
          </span>
        ))}
      </div>
    </div>
  )
}

function Tile({ label, value, sub, state }: { label: string; value: string; sub?: string; state?: 'good' | 'warn' | 'info' }) {
  const color = state === 'good' ? 'var(--green)' : state === 'warn' ? 'var(--orange)' : state === 'info' ? 'var(--blue)' : 'var(--text)'
  return (
    <div style={{ padding: '10px 12px', border: '1px solid var(--border)', borderRadius: 8, background: 'rgba(0,0,0,0.2)' }}>
      <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color, lineHeight: 1.1 }}>{value}</div>
      {sub ? <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 2 }}>{sub}</div> : null}
    </div>
  )
}

/* ═══════════════════════════════════════════════════════════════════
   TAB 2 — FLEET
   ═══════════════════════════════════════════════════════════════════ */

function FleetTab({ params }: { params: FuelParams }) {
  const today = new Date().toISOString().slice(0, 10)
  const ninetyAgo = new Date(Date.now() - 90 * 86400000).toISOString().slice(0, 10)
  const [start, setStart] = useState(ninetyAgo)
  const [end, setEnd] = useState(today)
  const [grillType, setGrillType] = useState('')
  const [firmware, setFirmware] = useState('')
  const [family, setFamily] = useState('')
  const [assumedFuel, setAssumedFuel] = useState<FuelType>('lump')
  const [filters, setFilters] = useState<CharcoalFleetFilters | null>(null)
  const [data, setData] = useState<CharcoalFleetAggregateResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const ctl = new AbortController()
    api.charcoalFleetFilters(ctl.signal).then(setFilters).catch(() => {/* silent */})
    return () => ctl.abort()
  }, [])

  useEffect(() => {
    const ctl = new AbortController()
    setLoading(true)
    api.charcoalFleetAggregate({
      start, end,
      grill_type: grillType || undefined,
      firmware_version: firmware || undefined,
      product_family: family || undefined,
    }, ctl.signal)
      .then(r => { setData(r); setError(null) })
      .catch(e => { if (e.name !== 'AbortError') setError(e instanceof ApiError ? e.message : String(e)) })
      .finally(() => setLoading(false))
    return () => ctl.abort()
  }, [start, end, grillType, firmware, family])

  // For each device, build a synthetic CookFuelEstimate stand-in using its
  // aggregate hours + avg temp. Gives a fleet-level fuel estimate.
  const perDeviceFuel = useMemo(() => {
    if (!data) return []
    return data.per_device.map(d => {
      const avgTemp = d.avg_cook_temp_f ?? d.avg_target_temp_f ?? 250
      const deliveredBtu = thermalDemandBtuPerHr(avgTemp) * d.cook_hours
      const fuelEnergyBtu = deliveredBtu / params.combustionEfficiency
      return {
        device_id: d.device_id,
        sessions: d.sessions,
        cook_hours: d.cook_hours,
        avg_temp_f: avgTemp,
        product_family: d.product_family,
        firmware: d.firmware_version,
        last_seen: d.last_session_at,
        lump_lb: fuelEnergyBtu / params.fuelEnergy.lump,
        briquette_lb: fuelEnergyBtu / params.fuelEnergy.briquette,
      }
    })
  }, [data, params])

  const fleetFuel = useMemo(() => {
    const total_lump = perDeviceFuel.reduce((s, d) => s + d.lump_lb, 0)
    const total_briq = perDeviceFuel.reduce((s, d) => s + d.briquette_lb, 0)
    const total_hours = perDeviceFuel.reduce((s, d) => s + d.cook_hours, 0)
    return { total_lump, total_briq, total_hours }
  }, [perDeviceFuel])

  // Distribution: bucket per-device fuel by lb range
  const histogram = useMemo(() => {
    const field = assumedFuel === 'lump' ? 'lump_lb' : 'briquette_lb'
    const buckets = [
      { label: '0-1', min: 0, max: 1 },
      { label: '1-5', min: 1, max: 5 },
      { label: '5-10', min: 5, max: 10 },
      { label: '10-25', min: 10, max: 25 },
      { label: '25-50', min: 25, max: 50 },
      { label: '50-100', min: 50, max: 100 },
      { label: '100+', min: 100, max: Infinity },
    ]
    return buckets.map(b => ({
      bucket: b.label,
      devices: perDeviceFuel.filter(d => (d[field] as number) >= b.min && (d[field] as number) < b.max).length,
    }))
  }, [perDeviceFuel, assumedFuel])

  // Heavy users: top 5% by burn
  const heavyUsers = useMemo(() => {
    const field = assumedFuel === 'lump' ? 'lump_lb' : 'briquette_lb'
    const sorted = [...perDeviceFuel].sort((a, b) => (b[field] as number) - (a[field] as number))
    const topCount = Math.max(1, Math.ceil(sorted.length * 0.05))
    const top = sorted.slice(0, topCount)
    const topTotal = top.reduce((s, d) => s + (d[field] as number), 0)
    const allTotal = sorted.reduce((s, d) => s + (d[field] as number), 0)
    return {
      topCount,
      pct_of_fleet: allTotal > 0 ? topTotal / allTotal : 0,
      top,
    }
  }, [perDeviceFuel, assumedFuel])

  return (
    <>
      <section className="card">
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <div>
            <div style={{ fontSize: 11, color: 'var(--muted)' }}>From</div>
            <input type="date" value={start} onChange={e => setStart(e.target.value)} className="deci-input" style={{ fontSize: 12 }} />
          </div>
          <div>
            <div style={{ fontSize: 11, color: 'var(--muted)' }}>To</div>
            <input type="date" value={end} onChange={e => setEnd(e.target.value)} className="deci-input" style={{ fontSize: 12 }} />
          </div>
          <div>
            <div style={{ fontSize: 11, color: 'var(--muted)' }}>Product family</div>
            <select value={family} onChange={e => setFamily(e.target.value)} className="deci-input" style={{ fontSize: 12 }}>
              <option value="">All</option>
              {(filters?.product_families || []).map(f => <option key={f} value={f}>{f}</option>)}
            </select>
          </div>
          <div>
            <div style={{ fontSize: 11, color: 'var(--muted)' }}>Firmware</div>
            <select value={firmware} onChange={e => setFirmware(e.target.value)} className="deci-input" style={{ fontSize: 12 }}>
              <option value="">All</option>
              {(filters?.firmware_versions || []).slice(0, 40).map(f => (
                <option key={f.value} value={f.value}>{f.value} ({f.devices})</option>
              ))}
            </select>
          </div>
          <div>
            <div style={{ fontSize: 11, color: 'var(--muted)' }}>Grill type</div>
            <select value={grillType} onChange={e => setGrillType(e.target.value)} className="deci-input" style={{ fontSize: 12 }}>
              <option value="">All</option>
              {(filters?.grill_types || []).map(g => (
                <option key={g.value} value={g.value}>{g.value} ({g.devices})</option>
              ))}
            </select>
          </div>
          <div>
            <div style={{ fontSize: 11, color: 'var(--muted)' }}>Assumed fuel</div>
            <select value={assumedFuel} onChange={e => setAssumedFuel(e.target.value as FuelType)} className="deci-input" style={{ fontSize: 12 }}>
              <option value="lump">Lump</option>
              <option value="briquette">Briquettes</option>
            </select>
          </div>
          {loading ? <span style={{ fontSize: 11, color: 'var(--muted)' }}>Loading…</span> : null}
        </div>
      </section>

      {error ? <section className="card"><div className="state-message error">{error}</div></section> : null}

      {data && (
        <>
          <section className="card">
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10 }}>
              <Tile label="Active devices" value={fmtInt(data.fleet_totals.unique_devices)} sub="that cooked in window" />
              <Tile label="Total sessions" value={fmtInt(data.fleet_totals.total_sessions)} />
              <Tile label="Total cook hours" value={fmtInt(data.fleet_totals.total_cook_hours)} />
              <Tile
                label={`Fleet ${assumedFuel} (est.)`}
                value={`${((assumedFuel === 'lump' ? fleetFuel.total_lump : fleetFuel.total_briq) / 1000).toFixed(1)}k lb`}
                sub={`${fleetFuel.total_hours.toFixed(0)} hours burned`}
                state="info"
              />
            </div>
          </section>

          <section className="card">
            <div className="venom-panel-head">
              <strong>Per-device burn distribution · {assumedFuel}</strong>
            </div>
            <div style={{ height: 200 }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={histogram} margin={{ top: 10, right: 20, left: 0, bottom: 10 }}>
                  <CartesianGrid stroke="rgba(255,255,255,0.05)" strokeDasharray="3 3" />
                  <XAxis dataKey="bucket" tick={{ fontSize: 11 }} stroke="var(--muted)" label={{ value: 'lb per device', position: 'insideBottom', offset: -5, fill: 'var(--muted)', fontSize: 10 }} />
                  <YAxis tick={{ fontSize: 11 }} stroke="var(--muted)" allowDecimals={false} />
                  <Tooltip contentStyle={{ background: '#111', border: '1px solid #333', fontSize: 12 }} />
                  <Bar dataKey="devices" fill="var(--orange)" />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 8, lineHeight: 1.4 }}>
              <strong style={{ color: 'var(--orange)' }}>Top {heavyUsers.topCount} heavy users</strong> consumed
              <strong> {(heavyUsers.pct_of_fleet * 100).toFixed(0)}%</strong> of the fleet's {assumedFuel} burn — a narrow power-user tail.
              These are the highest-value JIT targets.
            </div>
          </section>

          <section className="card">
            <div className="venom-panel-head">
              <strong>Top 10 heaviest-burning devices</strong>
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ textAlign: 'left', color: 'var(--muted)' }}>
                    <th style={{ padding: '6px 8px' }}>Device ID</th>
                    <th>Product</th>
                    <th>Firmware</th>
                    <th>Sessions</th>
                    <th>Hours</th>
                    <th>Avg temp</th>
                    <th>Est. {assumedFuel} lb</th>
                  </tr>
                </thead>
                <tbody>
                  {heavyUsers.top.slice(0, 10).map(d => (
                    <tr key={d.device_id} style={{ borderTop: '1px solid var(--border)' }}>
                      <td style={{ padding: '6px 8px', fontFamily: 'ui-monospace, monospace' }}>{d.device_id.slice(0, 14)}…</td>
                      <td>{d.product_family}</td>
                      <td>{d.firmware || '—'}</td>
                      <td>{d.sessions}</td>
                      <td>{d.cook_hours.toFixed(1)}</td>
                      <td>{d.avg_temp_f.toFixed(0)}°F</td>
                      <td style={{ fontWeight: 600 }}>
                        {(assumedFuel === 'lump' ? d.lump_lb : d.briquette_lb).toFixed(1)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </>
  )
}

/* ═══════════════════════════════════════════════════════════════════
   TAB 3 — JIT PROGRAM
   ═══════════════════════════════════════════════════════════════════ */

function JITTab({ params }: { params: FuelParams }) {
  const [macInput, setMacInput] = useState('fcb467f9b456')
  const [submittedMac, setSubmittedMac] = useState<string | null>(null)
  const [fuel, setFuel] = useState<FuelType>('lump')
  const [bagLb, setBagLb] = useState(20)
  const [leadDays, setLeadDays] = useState(5)
  const [safetyDays, setSafetyDays] = useState(7)
  const [data, setData] = useState<CharcoalDeviceSessionsResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setSubmittedMac(macInput.trim())
  }

  useEffect(() => {
    if (!submittedMac) return
    const ctl = new AbortController()
    setLoading(true)
    api.charcoalDeviceSessions(submittedMac, 180, ctl.signal)
      .then(r => { setData(r); setError(null) })
      .catch(e => { if (e.name !== 'AbortError') setError(e instanceof ApiError ? e.message : String(e)) })
      .finally(() => setLoading(false))
    return () => ctl.abort()
  }, [submittedMac])

  const estimates = useMemo<CookFuelEstimate[]>(() => {
    if (!data) return []
    return data.sessions
      .map(s => estimateSessionFuel(s, params))
      .filter((e): e is CookFuelEstimate => e != null)
  }, [data, params])

  const burn = useMemo(() => rollingBurnRate(estimates, 90), [estimates])
  const forecast = useMemo(() => forecastShipments(
    fuel === 'lump' ? burn.lump_lb_per_week : burn.briquette_lb_per_week,
    fuel, bagLb, leadDays, safetyDays,
  ), [burn, fuel, bagLb, leadDays, safetyDays])

  return (
    <>
      <section className="card" style={{ borderLeft: '3px solid var(--orange)' }}>
        <div className="venom-panel-head">
          <div>
            <strong>JIT auto-ship forecast</strong>
            <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
              Uses the last 90 days of cooks to project shipment timing. Lead time = days from trigger to customer doorstep; safety stock = how many cook-days of buffer we aim to hold.
            </div>
          </div>
        </div>
        <form onSubmit={submit} style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10, marginTop: 10 }}>
          <div>
            <div style={{ fontSize: 11, color: 'var(--muted)' }}>Device MAC</div>
            <input
              type="text" value={macInput}
              onChange={e => setMacInput(e.target.value)}
              placeholder="fcb467f9b456"
              className="deci-input"
              style={{ width: '100%', fontSize: 12, fontFamily: 'ui-monospace, monospace' }}
            />
          </div>
          <div>
            <div style={{ fontSize: 11, color: 'var(--muted)' }}>Fuel preference</div>
            <select value={fuel} onChange={e => setFuel(e.target.value as FuelType)} className="deci-input" style={{ fontSize: 12 }}>
              <option value="lump">Lump hardwood</option>
              <option value="briquette">Briquettes</option>
            </select>
          </div>
          <div>
            <div style={{ fontSize: 11, color: 'var(--muted)' }}>Bag size (lb)</div>
            <select value={bagLb} onChange={e => setBagLb(Number(e.target.value))} className="deci-input" style={{ fontSize: 12 }}>
              <option value={10}>10 lb</option>
              <option value={20}>20 lb</option>
              <option value={40}>40 lb</option>
            </select>
          </div>
          <div>
            <div style={{ fontSize: 11, color: 'var(--muted)' }}>Lead time (days)</div>
            <input type="number" min="1" max="30" value={leadDays} onChange={e => setLeadDays(Number(e.target.value))} className="deci-input" style={{ fontSize: 12, width: '100%' }} />
          </div>
          <div>
            <div style={{ fontSize: 11, color: 'var(--muted)' }}>Safety stock (days)</div>
            <input type="number" min="0" max="30" value={safetyDays} onChange={e => setSafetyDays(Number(e.target.value))} className="deci-input" style={{ fontSize: 12, width: '100%' }} />
          </div>
          <div style={{ alignSelf: 'flex-end' }}>
            <button type="submit" className="range-button active" disabled={loading} style={{ width: '100%' }}>
              {loading ? 'Computing…' : 'Forecast'}
            </button>
          </div>
        </form>
      </section>

      {error ? <section className="card"><div className="state-message error">{error}</div></section> : null}

      {data && (
        <section className="card">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10, marginBottom: 14 }}>
            <Tile
              label="Burn rate"
              value={`${forecast.lb_per_week.toFixed(2)} lb/wk`}
              sub={`${fuel}, 90d rolling`}
              state="info"
            />
            <Tile
              label="Days per bag"
              value={`${forecast.days_per_bag}`}
              sub={`at current rate`}
            />
            <Tile
              label="Next ship in"
              value={forecast.next_ship_in_days > 0 ? `${forecast.next_ship_in_days} days` : 'now'}
              sub={`${leadDays}d lead, ${safetyDays}d safety`}
              state={forecast.next_ship_in_days > 0 ? 'good' : 'warn'}
            />
            <Tile
              label="Annual bags"
              value={forecast.lb_per_week > 0 ? `${Math.ceil(forecast.lb_per_week * 52 / bagLb)}` : '—'}
              sub={`${bagLb} lb bags/year`}
            />
          </div>

          <div className="venom-panel-head" style={{ marginTop: 4 }}>
            <strong>Upcoming auto-ship dates</strong>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {forecast.upcoming_ship_dates.map((d, i) => (
              <div key={d} style={{
                padding: '8px 12px',
                border: '1px solid var(--border)', borderRadius: 6,
                background: i === 0 ? 'rgba(245, 158, 11, 0.08)' : 'rgba(0,0,0,0.2)',
                borderLeft: `3px solid ${i === 0 ? 'var(--orange)' : 'var(--border)'}`,
              }}>
                <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase' }}>
                  Ship #{i + 1}
                </div>
                <div style={{ fontSize: 14, fontWeight: 600 }}>{d}</div>
                <div style={{ fontSize: 10, color: 'var(--muted)' }}>{bagLb} lb {fuel}</div>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 10, lineHeight: 1.5 }}>
            <strong>How this works:</strong> we estimate the customer's burn rate from their last 90 days of cooks, divide the bag size by daily burn to find days-per-bag, and schedule shipment so they have <strong>{safetyDays} days of buffer</strong> when the bag arrives. Customer can still order extra bags manually; this just keeps them from running out.
          </div>
        </section>
      )}
    </>
  )
}

/* ═══════════════════════════════════════════════════════════════════
   TAB 4 — PROGRAM ENROLLMENT
   ═══════════════════════════════════════════════════════════════════ */

function EnrollmentTab() {
  const [list, setList] = useState<CharcoalJITListResponse | null>(null)
  const [products, setProducts] = useState<CharcoalPartnerProduct[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [catalogBusy, setCatalogBusy] = useState(false)
  const [catalogMsg, setCatalogMsg] = useState<string | null>(null)

  const [mac, setMac] = useState('')
  const [userKey, setUserKey] = useState('')
  const [partnerProductId, setPartnerProductId] = useState<number | null>(null)
  const [fuel, setFuel] = useState<'lump' | 'briquette'>('lump')
  const [bagLb, setBagLb] = useState(20)
  const [leadDays, setLeadDays] = useState(5)
  const [safetyDays, setSafetyDays] = useState(7)
  const [marginPct, setMarginPct] = useState(10)
  const [zip, setZip] = useState('')
  const [notes, setNotes] = useState('')
  const [statusFilter, setStatusFilter] = useState<'' | 'active' | 'paused' | 'cancelled'>('')

  // When a partner product is picked, auto-pull fuel type + bag size
  // so the form doesn't let you enter inconsistent values.
  useEffect(() => {
    if (partnerProductId == null) return
    const p = products.find(x => x.id === partnerProductId)
    if (p) {
      if (p.fuel_type === 'lump' || p.fuel_type === 'briquette') setFuel(p.fuel_type)
      if (p.bag_size_lb) setBagLb(p.bag_size_lb)
    }
  }, [partnerProductId, products])

  useEffect(() => {
    const ctl = new AbortController()
    api.charcoalPartnerProducts(true, ctl.signal)
      .then(r => setProducts(r.products))
      .catch(e => { if (e.name !== 'AbortError') setError(String(e.message || e)) })
    return () => ctl.abort()
  }, [])

  const refreshCatalog = async () => {
    setCatalogBusy(true)
    setCatalogMsg('Fetching partner prices…')
    try {
      await api.charcoalPartnerRefresh()
      const r = await api.charcoalPartnerProducts(true)
      setProducts(r.products)
      setCatalogMsg(`✓ Refreshed · ${r.count} products`)
      setTimeout(() => setCatalogMsg(null), 4000)
    } catch (err) {
      setCatalogMsg(`✗ ${err instanceof ApiError ? err.message : String(err)}`)
    } finally {
      setCatalogBusy(false)
    }
  }

  const load = () => {
    const ctl = new AbortController()
    api.charcoalJITList(statusFilter || undefined, ctl.signal)
      .then(r => { setList(r); setError(null) })
      .catch(e => { if (e.name !== 'AbortError') setError(e instanceof ApiError ? e.message : String(e)) })
    return ctl
  }

  useEffect(() => {
    const ctl = load()
    return () => ctl.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter])

  const enroll = async (e: FormEvent) => {
    e.preventDefault()
    if (!mac.trim()) return
    setBusy(true)
    setError(null)
    try {
      await api.charcoalJITSubscribe({
        mac: mac.trim(),
        user_key: userKey.trim() || undefined,
        fuel_preference: fuel,
        bag_size_lb: bagLb,
        lead_time_days: leadDays,
        safety_stock_days: safetyDays,
        shipping_zip: zip.trim() || undefined,
        notes: notes.trim() || undefined,
        partner_product_id: partnerProductId ?? undefined,
        margin_pct: marginPct,
      })
      // Clear form + reload
      setMac(''); setUserKey(''); setZip(''); setNotes('')
      load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const patch = async (id: number, changes: Parameters<typeof api.charcoalJITPatch>[1]) => {
    try {
      await api.charcoalJITPatch(id, changes)
      load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    }
  }

  const [forecastBusy, setForecastBusy] = useState(false)
  const [lastForecastRun, setLastForecastRun] = useState<string | null>(null)

  const forecastOne = async (id: number) => {
    try {
      await api.charcoalJITForecastOne(id)
      load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    }
  }

  const forecastAll = async () => {
    if (!confirm('Re-run forecast for every non-cancelled subscription?')) return
    setForecastBusy(true)
    try {
      const r = await api.charcoalJITForecastAll()
      setLastForecastRun(
        `Ran at ${new Date(r.computed_at).toLocaleTimeString()} · ${r.forecasted_ok} ok · ` +
        `${r.no_sessions} no-sessions · ${r.skipped_no_device_id} skipped · ` +
        `${r.shipping_address_backfilled} zips backfilled`
      )
      load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setForecastBusy(false)
    }
  }

  return (
    <>
      {/* Enrollment form */}
      {/* Program-wide financial summary — aggregate the forecasts of
          every active subscription so the whole JIT opportunity can
          be modeled at a glance. */}
      {(() => {
        const active = (list?.subscriptions || []).filter(s => s.status === 'active')
        let annualRevenue = 0
        let annualMargin = 0
        let annualPayout = 0
        let annualShipments = 0
        for (const s of active) {
          const f = (s.last_forecast || {}) as Record<string, unknown>
          const fin = (f.financial || null) as Record<string, unknown> | null
          if (!fin) continue
          annualRevenue += (fin.annual_revenue_usd as number) || 0
          annualMargin += (fin.annual_margin_usd as number) || 0
          annualPayout += (fin.annual_partner_payout_usd as number) || 0
          annualShipments += (fin.shipments_per_year as number) || 0
        }
        const modeledCount = active.filter(s => {
          const f = (s.last_forecast || {}) as Record<string, unknown>
          return (f.financial as unknown) != null
        }).length
        return (
          <section className="card" style={{ borderLeft: '3px solid var(--blue)' }}>
            <div className="venom-panel-head">
              <div>
                <strong>Program P&amp;L snapshot</strong>
                <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
                  Annualized projection across {modeledCount} active subscription{modeledCount === 1 ? '' : 's'} with a linked partner product. Scales linearly with enrollment cadence at current per-user burn rates.
                </div>
              </div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 10 }}>
              <div style={{ padding: '10px 12px', border: '1px solid var(--border)', borderRadius: 8, background: 'rgba(0,0,0,0.2)' }}>
                <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
                  Active subs modeled
                </div>
                <div style={{ fontSize: 24, fontWeight: 700, lineHeight: 1 }}>{modeledCount}</div>
                <div style={{ fontSize: 11, color: 'var(--muted)' }}>
                  of {active.length} active · {annualShipments.toFixed(1)} ships/yr total
                </div>
              </div>
              <div style={{ padding: '10px 12px', border: '1px solid var(--border)', borderLeft: '3px solid var(--orange)', borderRadius: 8, background: 'rgba(255,178,87,0.06)' }}>
                <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
                  Annual revenue
                </div>
                <div style={{ fontSize: 24, fontWeight: 700, lineHeight: 1, color: 'var(--orange)' }}>
                  ${annualRevenue.toLocaleString('en-US', { maximumFractionDigits: 0 })}
                </div>
                <div style={{ fontSize: 11, color: 'var(--muted)' }}>customer billings</div>
              </div>
              <div style={{ padding: '10px 12px', border: '1px solid var(--border)', borderLeft: '3px solid var(--green)', borderRadius: 8, background: 'rgba(57,208,143,0.06)' }}>
                <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
                  Annual margin
                </div>
                <div style={{ fontSize: 24, fontWeight: 700, lineHeight: 1, color: 'var(--green)' }}>
                  ${annualMargin.toLocaleString('en-US', { maximumFractionDigits: 0 })}
                </div>
                <div style={{ fontSize: 11, color: 'var(--muted)' }}>Spider Grills keeps</div>
              </div>
              <div style={{ padding: '10px 12px', border: '1px solid var(--border)', borderLeft: '3px solid var(--blue)', borderRadius: 8, background: 'rgba(110,168,255,0.06)' }}>
                <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
                  Annual payout
                </div>
                <div style={{ fontSize: 24, fontWeight: 700, lineHeight: 1, color: 'var(--blue)' }}>
                  ${annualPayout.toLocaleString('en-US', { maximumFractionDigits: 0 })}
                </div>
                <div style={{ fontSize: 11, color: 'var(--muted)' }}>flowed to partners</div>
              </div>
            </div>
            {active.length > modeledCount ? (
              <div style={{ marginTop: 10, fontSize: 11, color: 'var(--muted)' }}>
                <strong style={{ color: 'var(--orange)' }}>Note:</strong> {active.length - modeledCount} active subscription{active.length - modeledCount === 1 ? ' is' : 's are'} not linked to a partner product yet — those don't contribute to this P&amp;L projection. Edit them to pick an SKU from the catalog above.
              </div>
            ) : null}
          </section>
        )
      })()}

      {/* Partner catalog strip — current Jealous Devil (and future
          Royal Oak / Kingsford) prices. Drives the enrollment form's
          product picker + the financial modeling card below. */}
      <section className="card" style={{ borderLeft: '3px solid #ec4899' }}>
        <div className="venom-panel-head" style={{ alignItems: 'center' }}>
          <div>
            <strong>Partner charcoal catalog</strong>
            <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
              Scraped live from each partner's storefront (daily at 06:30 ET + on demand). Retail = what the customer pays = what Spider Grills bills. Spider Grills' cut is configurable below.
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {catalogMsg ? <span style={{ fontSize: 11, color: 'var(--muted)' }}>{catalogMsg}</span> : null}
            <button className="range-button" onClick={refreshCatalog} disabled={catalogBusy}>
              {catalogBusy ? 'Refreshing…' : 'Refresh prices now'}
            </button>
          </div>
        </div>
        {products.length === 0 ? (
          <div className="state-message">
            No partner products loaded yet. Click "Refresh prices now" to pull the initial catalog.
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 10 }}>
            {products.map(p => (
              <div
                key={p.id}
                style={{
                  padding: 10,
                  border: `1px solid ${partnerProductId === p.id ? 'var(--orange)' : 'var(--border)'}`,
                  borderRadius: 8,
                  background: partnerProductId === p.id ? 'rgba(255,178,87,0.08)' : 'rgba(0,0,0,0.2)',
                  cursor: 'pointer',
                }}
                onClick={() => setPartnerProductId(p.id)}
              >
                <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
                  {p.partner.replace(/_/g, ' ')}
                </div>
                <div style={{ fontSize: 13, fontWeight: 600, marginTop: 2, lineHeight: 1.3 }}>{p.title}</div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6 }}>
                  <span style={{ fontSize: 11, color: 'var(--muted)' }}>
                    {p.bag_size_lb ? `${p.bag_size_lb} lb` : 'size unknown'} · {p.fuel_type || '—'}
                  </span>
                  <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--orange)' }}>
                    ${p.retail_price_usd.toFixed(2)}
                  </span>
                </div>
                <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 4 }}>
                  {p.available ? '✓ in stock' : '⚠ sold out'}
                  {p.last_fetched_at ? ` · ${new Date(p.last_fetched_at).toLocaleDateString()}` : ''}
                  {p.source_url ? ' · ' : ''}
                  {p.source_url ? (
                    <a href={p.source_url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--blue)' }}>
                      view
                    </a>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="card" style={{ borderLeft: '3px solid var(--green)' }}>
        <div className="venom-panel-head">
          <div>
            <strong>Enroll a device in Charcoal JIT</strong>
            <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
              Click a partner product above first — fuel type + bag size auto-fill from the catalog, price flows through to the financial model. Sign-up is idempotent; nothing ships automatically.
            </div>
          </div>
        </div>
        <form onSubmit={enroll} style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 10, marginTop: 10 }}>
          <div>
            <label style={{ fontSize: 11, color: 'var(--muted)' }}>Device MAC <span style={{ color: 'var(--red)' }}>*</span></label>
            <input
              type="text" value={mac} onChange={e => setMac(e.target.value)}
              placeholder="fcb467f9b456"
              className="deci-input"
              required
              style={{ width: '100%', fontSize: 12, fontFamily: 'ui-monospace, monospace' }}
            />
          </div>
          <div>
            <label style={{ fontSize: 11, color: 'var(--muted)' }}>User key (optional)</label>
            <input
              type="text" value={userKey} onChange={e => setUserKey(e.target.value)}
              placeholder="email or user_id"
              className="deci-input"
              style={{ width: '100%', fontSize: 12 }}
            />
          </div>
          <div>
            <label style={{ fontSize: 11, color: 'var(--muted)' }}>Partner product</label>
            <select
              value={partnerProductId ?? ''}
              onChange={e => setPartnerProductId(e.target.value ? Number(e.target.value) : null)}
              className="deci-input" style={{ width: '100%', fontSize: 12 }}
            >
              <option value="">— none (manual bag size) —</option>
              {products.map(p => (
                <option key={p.id} value={p.id}>
                  {p.title} · ${p.retail_price_usd.toFixed(2)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label style={{ fontSize: 11, color: 'var(--muted)' }}>Fuel preference</label>
            <select value={fuel} onChange={e => setFuel(e.target.value as 'lump' | 'briquette')} className="deci-input" style={{ width: '100%', fontSize: 12 }}>
              <option value="lump">Lump hardwood</option>
              <option value="briquette">Briquettes</option>
            </select>
          </div>
          <div>
            <label style={{ fontSize: 11, color: 'var(--muted)' }}>Bag size (lb)</label>
            <input
              type="number" min={5} max={100} value={bagLb}
              onChange={e => setBagLb(Number(e.target.value) || 20)}
              className="deci-input"
              style={{ width: '100%', fontSize: 12 }}
              title={partnerProductId != null ? 'Set from partner product; edit to override' : undefined}
            />
          </div>
          <div>
            <label style={{ fontSize: 11, color: 'var(--muted)' }}>Lead time (days)</label>
            <input type="number" min={1} max={30} value={leadDays} onChange={e => setLeadDays(Number(e.target.value) || 5)} className="deci-input" style={{ width: '100%', fontSize: 12 }} />
          </div>
          <div>
            <label style={{ fontSize: 11, color: 'var(--muted)' }}>Safety stock (days)</label>
            <input type="number" min={0} max={30} value={safetyDays} onChange={e => setSafetyDays(Number(e.target.value) || 7)} className="deci-input" style={{ width: '100%', fontSize: 12 }} />
          </div>
          <div>
            <label style={{ fontSize: 11, color: 'var(--muted)' }}>Spider Grills margin %</label>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <input
                type="range" min={0} max={40} step={0.5} value={marginPct}
                onChange={e => setMarginPct(Number(e.target.value))}
                style={{ flex: 1 }}
              />
              <input
                type="number" min={0} max={100} step={0.5} value={marginPct}
                onChange={e => setMarginPct(Number(e.target.value) || 0)}
                className="deci-input" style={{ width: 60, fontSize: 12 }}
              />
              <span style={{ fontSize: 11, color: 'var(--muted)' }}>%</span>
            </div>
          </div>
          <div>
            <label style={{ fontSize: 11, color: 'var(--muted)' }}>Shipping ZIP</label>
            <input
              type="text" value={zip} onChange={e => setZip(e.target.value)}
              placeholder="10001"
              className="deci-input"
              style={{ width: '100%', fontSize: 12 }}
            />
          </div>
          <div style={{ gridColumn: '1 / -1' }}>
            <label style={{ fontSize: 11, color: 'var(--muted)' }}>Notes (optional)</label>
            <input
              type="text" value={notes} onChange={e => setNotes(e.target.value)}
              placeholder="e.g. beta tester cohort, bulk-charcoal pilot"
              className="deci-input"
              style={{ width: '100%', fontSize: 12 }}
            />
          </div>
          <div style={{ alignSelf: 'flex-end' }}>
            <button type="submit" className="range-button active" disabled={busy || !mac.trim()}>
              {busy ? 'Saving…' : 'Enroll device'}
            </button>
          </div>
        </form>
        {/* Per-shipment price preview when a partner product is selected */}
        {partnerProductId != null ? (() => {
          const p = products.find(x => x.id === partnerProductId)
          if (!p) return null
          const retail = p.retail_price_usd
          const margin = retail * marginPct / 100
          const payout = retail - margin
          return (
            <div style={{
              marginTop: 12, padding: '10px 12px',
              background: 'rgba(245, 158, 11, 0.06)',
              borderLeft: '3px solid var(--orange)', borderRadius: 6,
              display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10,
              fontSize: 12,
            }}>
              <div>
                <div style={{ fontSize: 10, color: 'var(--muted)' }}>Customer pays</div>
                <div style={{ fontSize: 18, fontWeight: 700 }}>${retail.toFixed(2)}</div>
              </div>
              <div>
                <div style={{ fontSize: 10, color: 'var(--muted)' }}>Spider Grills keeps</div>
                <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--green)' }}>${margin.toFixed(2)}</div>
              </div>
              <div>
                <div style={{ fontSize: 10, color: 'var(--muted)' }}>Paid to {p.partner.replace(/_/g, ' ')}</div>
                <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--blue)' }}>${payout.toFixed(2)}</div>
              </div>
              <div>
                <div style={{ fontSize: 10, color: 'var(--muted)' }}>Margin rate</div>
                <div style={{ fontSize: 18, fontWeight: 700 }}>{marginPct.toFixed(1)}%</div>
              </div>
            </div>
          )
        })() : null}
        {error ? <div style={{ marginTop: 10, color: 'var(--red)', fontSize: 12 }}>{error}</div> : null}
      </section>

      {/* Subscription list */}
      <section className="card">
        <div className="venom-panel-head" style={{ alignItems: 'center' }}>
          <div>
            <strong>Current subscriptions ({list?.count ?? 0})</strong>
            {list ? (
              <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
                By status: {Object.entries(list.by_status).map(([s, n]) => `${s}=${n}`).join(' · ') || '—'} ·
                By fuel: {Object.entries(list.by_fuel).map(([f, n]) => `${f}=${n}`).join(' · ') || '—'}
              </div>
            ) : null}
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            {lastForecastRun ? <span style={{ fontSize: 10, color: 'var(--muted)' }}>{lastForecastRun}</span> : null}
            <button
              className="range-button"
              onClick={forecastAll}
              disabled={forecastBusy}
              title="Re-run the forecast model across every active subscription. Safe — no Shopify orders fire."
            >
              {forecastBusy ? 'Forecasting…' : 'Run forecast now'}
            </button>
            <select value={statusFilter} onChange={e => setStatusFilter(e.target.value as typeof statusFilter)} className="deci-input" style={{ fontSize: 12 }}>
              <option value="">All statuses</option>
              <option value="active">Active only</option>
              <option value="paused">Paused only</option>
              <option value="cancelled">Cancelled only</option>
            </select>
          </div>
        </div>

        {!list ? (
          <div className="state-message">Loading subscriptions…</div>
        ) : list.subscriptions.length === 0 ? (
          <div style={{ fontSize: 13, color: 'var(--muted)', padding: '8px 0' }}>
            No subscriptions yet. Use the form above to enroll your first device.
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse', minWidth: 900 }}>
              <thead>
                <tr style={{ textAlign: 'left', color: 'var(--muted)' }}>
                  <th style={{ padding: '6px 8px' }}>MAC / user</th>
                  <th>Product · price</th>
                  <th>Margin</th>
                  <th>Burn rate</th>
                  <th>Next ship</th>
                  <th>Annual margin</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {list.subscriptions.map(sub => {
                  const fc = (sub.last_forecast || {}) as Record<string, unknown>
                  const burnRate = typeof fc.lb_per_week === 'number' ? (fc.lb_per_week as number) : null
                  const fcStatus = (fc.status as string) || null
                  const nextShip = sub.next_ship_after ? new Date(sub.next_ship_after) : null
                  const daysUntil = nextShip
                    ? Math.max(0, Math.round((nextShip.getTime() - Date.now()) / 86400000))
                    : null
                  const product = sub.partner_product_id != null
                    ? products.find(x => x.id === sub.partner_product_id)
                    : null
                  const financial = (fc.financial || null) as Record<string, unknown> | null
                  const annualMargin = financial && typeof financial.annual_margin_usd === 'number'
                    ? (financial.annual_margin_usd as number)
                    : null
                  const perShip = financial && typeof financial.per_ship_margin_usd === 'number'
                    ? (financial.per_ship_margin_usd as number)
                    : null
                  return (
                    <tr key={sub.id} style={{
                      borderTop: '1px solid var(--border)',
                      opacity: sub.status === 'cancelled' ? 0.55 : 1,
                    }}>
                      <td style={{ padding: '6px 8px' }}>
                        <div style={{ fontFamily: 'ui-monospace, monospace' }}>{sub.mac || '—'}</div>
                        {sub.user_key ? <div style={{ fontSize: 10, color: 'var(--muted)' }}>{sub.user_key}</div> : null}
                      </td>
                      <td>
                        {product ? (
                          <>
                            <div style={{ fontSize: 12, fontWeight: 600 }}>{product.title.slice(0, 40)}{product.title.length > 40 ? '…' : ''}</div>
                            <div style={{ fontSize: 10, color: 'var(--muted)' }}>
                              {product.bag_size_lb} lb · ${product.retail_price_usd.toFixed(2)} · {sub.fuel_preference}
                            </div>
                          </>
                        ) : (
                          <>
                            <span className={`badge ${sub.fuel_preference === 'lump' ? 'badge-warn' : 'badge-neutral'}`}>
                              {sub.fuel_preference}
                            </span>
                            <div style={{ fontSize: 10, color: 'var(--muted)' }}>{sub.bag_size_lb} lb · no partner SKU</div>
                          </>
                        )}
                      </td>
                      <td>
                        <div style={{ fontWeight: 600 }}>{sub.margin_pct.toFixed(1)}%</div>
                        {perShip != null ? (
                          <div style={{ fontSize: 10, color: 'var(--muted)' }}>${perShip.toFixed(2)}/ship</div>
                        ) : null}
                      </td>
                      <td>
                        {burnRate != null ? (
                          <>
                            <div style={{ fontWeight: 600 }}>{burnRate.toFixed(2)} lb/wk</div>
                            {typeof fc.cooks_in_window === 'number' ? (
                              <div style={{ fontSize: 10, color: 'var(--muted)' }}>
                                n={fc.cooks_in_window as number} cooks
                              </div>
                            ) : null}
                          </>
                        ) : fcStatus ? (
                          <span style={{ fontSize: 10, color: 'var(--muted)' }}>{fcStatus.replace(/_/g, ' ')}</span>
                        ) : (
                          <span style={{ fontSize: 10, color: 'var(--muted)' }}>—</span>
                        )}
                      </td>
                      <td>
                        {nextShip ? (
                          <>
                            <div style={{ fontWeight: 600 }}>{nextShip.toISOString().slice(0, 10)}</div>
                            <div style={{ fontSize: 10, color: daysUntil != null && daysUntil <= 3 ? 'var(--orange)' : 'var(--muted)' }}>
                              {daysUntil != null ? `in ${daysUntil}d` : '—'}
                            </div>
                          </>
                        ) : (
                          <span style={{ fontSize: 10, color: 'var(--muted)' }}>—</span>
                        )}
                      </td>
                      <td>
                        {annualMargin != null ? (
                          <>
                            <div style={{ fontWeight: 600, color: 'var(--green)' }}>${annualMargin.toFixed(0)}</div>
                            {typeof financial?.shipments_per_year === 'number' ? (
                              <div style={{ fontSize: 10, color: 'var(--muted)' }}>
                                {(financial.shipments_per_year as number).toFixed(1)} ships/yr
                              </div>
                            ) : null}
                          </>
                        ) : (
                          <span style={{ fontSize: 10, color: 'var(--muted)' }}>—</span>
                        )}
                      </td>
                      <td>
                        <span className={`badge ${sub.status === 'active' ? 'badge-good' : sub.status === 'paused' ? 'badge-warn' : 'badge-muted'}`}>
                          {sub.status}
                        </span>
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        <div style={{ display: 'inline-flex', gap: 4 }}>
                          <button
                            className="range-button" style={{ fontSize: 10, padding: '2px 8px' }}
                            onClick={() => forecastOne(sub.id)}
                            title="Re-run this subscription's forecast"
                          >Forecast</button>
                          {sub.status === 'active' ? (
                            <button
                              className="range-button" style={{ fontSize: 10, padding: '2px 8px' }}
                              onClick={() => patch(sub.id, { status: 'paused' })}
                            >Pause</button>
                          ) : sub.status === 'paused' ? (
                            <button
                              className="range-button" style={{ fontSize: 10, padding: '2px 8px' }}
                              onClick={() => patch(sub.id, { status: 'active' })}
                            >Resume</button>
                          ) : null}
                          {sub.status !== 'cancelled' ? (
                            <button
                              className="range-button" style={{ fontSize: 10, padding: '2px 8px', color: 'var(--red)' }}
                              onClick={() => {
                                if (confirm(`Cancel JIT for MAC ${sub.mac}?`)) patch(sub.id, { status: 'cancelled' })
                              }}
                            >Cancel</button>
                          ) : (
                            <button
                              className="range-button" style={{ fontSize: 10, padding: '2px 8px' }}
                              onClick={() => patch(sub.id, { status: 'active' })}
                            >Reactivate</button>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card" style={{ fontSize: 11, color: 'var(--muted)', lineHeight: 1.6 }}>
        <strong style={{ color: 'var(--text)' }}>What happens next (not live yet):</strong>
        <ol style={{ marginTop: 6, paddingLeft: 20 }}>
          <li>A scheduler reads active subscriptions every morning, pulls the device's 90-day burn from TelemetrySession, and writes a fresh <code>next_ship_after</code> timestamp using the forecast model.</li>
          <li>When <code>NOW() &gt; next_ship_after − lead_time_days</code>, the scheduler creates a Shopify draft order against the user's saved address and emails the user a "we're sending you {'{'}bag_size{'}'} lb of {'{'}fuel{'}'} on {'{'}date{'}'}; reply to change" confirmation.</li>
          <li>If the user replies / clicks through within 48 hours to change qty or fuel, the draft updates. Otherwise it converts to a real order automatically.</li>
          <li>Shopify webhook on fulfillment writes back <code>last_shipped_at</code>, and the cycle restarts.</li>
        </ol>
        <div style={{ marginTop: 8 }}>
          The enrollment record above is the prerequisite for all of this. Collect enrollments → run the scheduler dry to watch predictions → flip the shipment trigger live when we're confident.
        </div>
      </section>
    </>
  )
}


/* ═══════════════════════════════════════════════════════════════════
   PAGE SHELL
   ═══════════════════════════════════════════════════════════════════ */

export function CharcoalUsage() {
  const [tab, setTab] = useState<Tab>('device')
  const [params, setParams] = useState<FuelParams>(DEFAULT_FUEL_PARAMS)

  return (
    <div className="page-grid">
      <section className="card" style={{ borderLeft: '3px solid var(--orange)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <div style={{ fontSize: 10, color: 'var(--orange)', textTransform: 'uppercase', letterSpacing: 1.2, fontWeight: 600 }}>
            Product Engineering · Charcoal usage
          </div>
          <div className="card-title" style={{ marginBottom: 2 }}>Charcoal JIT analytics</div>
          <div style={{ fontSize: 12, color: 'var(--muted)' }}>
            Per-device burn rate · fleet cohort analysis · auto-ship forecast. Data flows from the thermal model in <code>charcoalModel.ts</code> against the TelemetrySession history. This is the foundation for the JIT auto-ship program — we're collecting + modeling now, shipping later.
          </div>
        </div>
        <Link to="/division/product-engineering" className="range-button" style={{ textDecoration: 'none' }}>
          ← Back to Product Engineering
        </Link>
      </section>

      {/* Tabs */}
      <section className="card" style={{ padding: '8px 10px' }}>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {TABS.map(t => (
            <button
              key={t.key}
              className={`range-button${tab === t.key ? ' active' : ''}`}
              onClick={() => setTab(t.key)}
              title={t.desc}
            >
              {t.label}
            </button>
          ))}
        </div>
      </section>

      <AssumptionsPanel params={params} setParams={setParams} />

      {tab === 'device' ? <DeviceTab params={params} /> : null}
      {tab === 'fleet' ? <FleetTab params={params} /> : null}
      {tab === 'jit' ? <JITTab params={params} /> : null}
      {tab === 'enrollment' ? <EnrollmentTab /> : null}
    </div>
  )
}
