import { useEffect, useState } from 'react'
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, Cell } from 'recharts'
import { api } from '../lib/api'
import type { KlaviyoCookReconciliation } from '../lib/api'

/**
 * App-vs-telemetry cook reconciliation.
 *
 * Two questions this card answers at a glance:
 *
 *   1. Are the two streams agreeing?
 *      App-side count (Klaviyo `Cook Completed` events) vs the
 *      telemetry-derived count (sum of `cook_styles_json` values from
 *      `telemetry_history_daily`). A persistent gap in either direction
 *      is actionable:
 *        positive gap = telemetry sees cooks the app missed firing
 *                       (app-side bug or the app was offline when the
 *                       cook ended)
 *        negative gap = app reports cooks telemetry didn't classify
 *                       (classifier under-counting; investigate the
 *                       cook_styles taxonomy)
 *
 *   2. What does the app know that telemetry can't?
 *      `completed_normally` rate splits user-aborted cooks from
 *      finished ones, target_temp histogram shows what bands users
 *      actually cook in. These are app-only signals.
 *
 * Note on first launch: Agustín shipped these events on 2026-04-28.
 * Days before that show `app_cooks: 0` against real telemetry counts —
 * not a bug, just the events weren't firing yet. We render an
 * "events started flowing on …" note so that's clear.
 */

type View = 'reconciliation' | 'duration' | 'temp'

function _fmt_duration(seconds: number | null): string {
  if (seconds == null) return '—'
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  const hours = seconds / 3600
  if (hours < 10) return `${hours.toFixed(1)}h`
  return `${Math.round(hours)}h`
}

export function CookReconciliationCard({ days = 30 }: { days?: number }) {
  const [data, setData] = useState<KlaviyoCookReconciliation | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<View>('reconciliation')

  useEffect(() => {
    const ctl = new AbortController()
    api.klaviyoCookReconciliation(days, ctl.signal)
      .then(setData)
      .catch(err => { if (!ctl.signal.aborted) setError(err instanceof Error ? err.message : String(err)) })
    return () => ctl.abort()
  }, [days])

  if (error) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>Cook reconciliation</strong></div>
        <div className="state-message error">{error}</div>
      </section>
    )
  }
  if (!data) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>Cook reconciliation</strong></div>
        <div className="state-message">Loading…</div>
      </section>
    )
  }

  // Trim daily series to the data-bearing window. If app events only
  // started firing N days ago, showing 30 days of zero in the bar
  // chart is just noise — start from the first day either source has
  // data (or, if app is brand-new, from a few days before its first
  // event so the gap is visible).
  const firstSeenDate = data.events_first_seen_at?.slice(0, 10) ?? null
  const dailyTrimmed = firstSeenDate
    ? data.daily.filter(d => d.business_date >= firstSeenDate)
    : data.daily.slice(-14)
  // If trimming left fewer than 4 points, show a wider window so the
  // chart isn't a single bar.
  const series = dailyTrimmed.length >= 4 ? dailyTrimmed : data.daily.slice(-14)

  // Banner message for the events-first-seen note.
  let firstSeenNote: string | null = null
  if (firstSeenDate) {
    const daysSince = Math.floor((Date.now() - new Date(firstSeenDate).getTime()) / 86400000)
    if (daysSince < 14) {
      firstSeenNote = `App-side Cook Completed events started flowing ${daysSince === 0 ? 'today' : `${daysSince}d ago`} (${firstSeenDate}). Pre-launch days don't show app counts — telemetry is the only source for those.`
    }
  } else {
    firstSeenNote = 'App-side Cook Completed events have not fired yet. Once the first event lands, the reconciliation chart populates retroactively.'
  }

  const totals = data.totals
  const tempBands = data.target_temp_bands
  const tempTotal = tempBands.low_below_250 + tempBands.mid_250_to_350 + tempBands.high_350_plus + tempBands.unknown
  const tempData = [
    { band: 'Low (<250°F)', n: tempBands.low_below_250, color: '#6ea8ff' },
    { band: 'Mid (250-350)', n: tempBands.mid_250_to_350, color: '#39d08f' },
    { band: 'High (350+)', n: tempBands.high_350_plus, color: '#ff6d7a' },
    { band: 'Unknown', n: tempBands.unknown, color: '#888' },
  ].filter(d => d.n > 0)

  return (
    <section className="card">
      <div className="venom-panel-head">
        <strong>Cook reconciliation · app vs telemetry</strong>
        <div style={{ display: 'flex', gap: 6 }}>
          <button className={`range-button${view === 'reconciliation' ? ' active' : ''}`} onClick={() => setView('reconciliation')} style={{ fontSize: 11 }}>Daily gap</button>
          <button className={`range-button${view === 'duration' ? ' active' : ''}`} onClick={() => setView('duration')} style={{ fontSize: 11 }}>Duration</button>
          <button className={`range-button${view === 'temp' ? ' active' : ''}`} onClick={() => setView('temp')} style={{ fontSize: 11 }}>Target temp</button>
        </div>
      </div>

      {firstSeenNote ? (
        <div style={{ fontSize: 11, color: 'var(--muted)', padding: '4px 8px', background: 'rgba(110,168,255,0.06)', borderLeft: '2px solid var(--blue)', marginBottom: 10, lineHeight: 1.4 }}>
          ℹ {firstSeenNote}
        </div>
      ) : null}

      {/* Headline KPIs */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10, marginBottom: 14 }}>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)' }}>App cooks</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--blue)' }}>{totals.app_cooks.toLocaleString()}</div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)' }}>Telemetry cooks</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--green)' }}>{totals.telemetry_cooks.toLocaleString()}</div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)' }}>Gap (tele − app)</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: totals.gap > 0 ? 'var(--orange)' : totals.gap < 0 ? 'var(--blue)' : 'var(--muted)' }}>
            {totals.gap > 0 ? '+' : ''}{totals.gap.toLocaleString()}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)' }}>Completed normally</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--green)' }}>
            {totals.completed_normally_pct != null ? `${totals.completed_normally_pct}%` : '—'}
            {totals.completed_normally_n > 0 ? <span style={{ fontSize: 11, color: 'var(--muted)', marginLeft: 4 }}>· {totals.completed_normally_n}</span> : null}
          </div>
        </div>
      </div>

      {view === 'reconciliation' ? (
        <div className="chart-wrap-short">
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={series} margin={{ top: 4, right: 12, bottom: 4, left: -10 }}>
              <CartesianGrid stroke="rgba(255,255,255,0.06)" />
              <XAxis dataKey="business_date" stroke="#9fb0d4" tick={{ fontSize: 10 }} tickFormatter={(d: string) => d.slice(5)} />
              <YAxis stroke="#9fb0d4" tick={{ fontSize: 10 }} />
              <Tooltip
                contentStyle={{ background: 'var(--panel)', border: '1px solid rgba(255,255,255,0.1)' }}
                labelFormatter={(label: string) => label}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar name="App (Klaviyo)" dataKey="app_cooks" fill="var(--blue)" />
              <Bar name="Telemetry" dataKey="telemetry_cooks" fill="var(--green)" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      ) : view === 'duration' ? (
        <div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 10 }}>
            <div>
              <div style={{ fontSize: 11, color: 'var(--muted)' }}>Median (p50)</div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{_fmt_duration(totals.duration_p50_seconds)}</div>
            </div>
            <div>
              <div style={{ fontSize: 11, color: 'var(--muted)' }}>p75</div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{_fmt_duration(totals.duration_p75_seconds)}</div>
            </div>
            <div>
              <div style={{ fontSize: 11, color: 'var(--muted)' }}>p95</div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{_fmt_duration(totals.duration_p95_seconds)}</div>
            </div>
            <div>
              <div style={{ fontSize: 11, color: 'var(--muted)' }}>Anomalies (&gt;24h)</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: totals.long_cook_anomaly_count > 0 ? 'var(--orange)' : 'var(--muted)' }}>
                {totals.long_cook_anomaly_count}
              </div>
            </div>
          </div>
          <small style={{ color: 'var(--muted)', fontSize: 11, marginTop: 8, display: 'block' }}>
            Percentiles exclude cooks &gt; 24h (forgotten/never-ended sessions).
            Anomaly count surfaces those separately — usually means someone left the app open or the cook never got marked done.
          </small>
        </div>
      ) : (
        <div>
          {tempTotal > 0 ? (
            <div className="chart-wrap-short">
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={tempData} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 8 }}>
                  <CartesianGrid stroke="rgba(255,255,255,0.06)" />
                  <XAxis type="number" stroke="#9fb0d4" tick={{ fontSize: 10 }} />
                  <YAxis type="category" dataKey="band" stroke="#9fb0d4" tick={{ fontSize: 11 }} width={120} />
                  <Tooltip contentStyle={{ background: 'var(--panel)', border: '1px solid rgba(255,255,255,0.1)' }} />
                  <Bar dataKey="n" name="Cooks">
                    {tempData.map((d, i) => <Cell key={i} fill={d.color} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : <div className="state-message">No target_temp data yet — fires once Cook Completed events accumulate.</div>}
          <small style={{ color: 'var(--muted)', fontSize: 11, marginTop: 8, display: 'block' }}>
            Bands: Low &lt;250°F (smoking, low-and-slow) · Mid 250-350°F (typical roast) · High 350°F+ (sear, fast-cook).
          </small>
        </div>
      )}
    </section>
  )
}
