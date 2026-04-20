import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { currency } from '../lib/format'
import type {
  MarketingChannelTrendsResponse,
  MarketingChannelTrendRow,
  MarketingPacingResponse,
  MarketingMerHealthResponse,
} from '../lib/types'
import { TruthBadge } from './TruthBadge'

// Shared with ChannelMixCard so the same channel gets the same color
// across both cards — reduces cognitive load when scanning.
const CHANNEL_COLORS: Record<string, string> = {
  facebook_spend: '#1877F2',
  google_spend: '#EA4335',
  tiktok_spend: '#FF0050',
  amazon_ads_spend: '#FF9900',
  pinterest_spend: '#E60023',
  snapchat_spend: '#FFFC00',
  bing_spend: '#008373',
  twitter_spend: '#1DA1F2',
  reddit_spend: '#FF4500',
  linkedin_spend: '#0A66C2',
  smsbump_spend: '#7C3AED',
  omnisend_spend: '#FB923C',
  postscript_spend: '#22C55E',
  taboola_spend: '#0EA5E9',
  outbrain_spend: '#F97316',
  stackadapt_spend: '#14B8A6',
  adroll_spend: '#EAB308',
  impact_spend: '#8B5CF6',
  custom_spend: '#64748B',
}

function deltaClass(d: number | null, reversed = false): string {
  if (d == null) return 'badge-neutral'
  const up = reversed ? 'badge-bad' : 'badge-good'
  const down = reversed ? 'badge-good' : 'badge-bad'
  if (d > 10) return up
  if (d < -10) return down
  return 'badge-neutral'
}

function fmtDelta(d: number | null): string {
  if (d == null) return '—'
  const sign = d > 0 ? '+' : ''
  return `${sign}${d.toFixed(1)}%`
}

// ─── Sparkline ───────────────────────────────────────────────────────
// Lightweight SVG sparkline. No recharts import — keeps the bundle
// lean and these render inside dense rows where axes would be noise.
function Sparkline({ data, color, width = 120, height = 28 }: {
  data: number[]; color: string; width?: number; height?: number
}) {
  if (!data.length) return null
  const max = Math.max(...data, 1)
  const stepX = width / Math.max(data.length - 1, 1)
  const points = data.map((v, i) => {
    const x = i * stepX
    const y = height - (v / max) * (height - 2) - 1
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
  return (
    <svg width={width} height={height} style={{ display: 'block' }} aria-hidden="true">
      <polyline fill="none" stroke={color} strokeWidth={1.5} points={points} />
    </svg>
  )
}

// ─── 1. Channel Trends Card ──────────────────────────────────────────

export function ChannelTrendsCard({ days = 30 }: { days?: number }) {
  const [data, setData] = useState<MarketingChannelTrendsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    api.marketingChannelTrends({ days }, controller.signal)
      .then(r => setData(r))
      .catch(err => {
        if (err?.name === 'AbortError') return
        setError(err?.message || 'failed to load channel trends')
      })
      .finally(() => setLoading(false))
    return () => controller.abort()
  }, [days])

  return (
    <section className="card">
      <div className="venom-panel-head">
        <strong>Channel spend trends — {days}d</strong>
        <TruthBadge state="canonical" />
        <span className="venom-panel-hint">per-channel daily spend, ranked by total</span>
      </div>
      {loading && <div className="state-message">Loading…</div>}
      {error && <div className="state-message error">{error}</div>}
      {!loading && !error && data && (
        <>
          <div className="venom-breakdown-list">
            {data.channels.map((ch: MarketingChannelTrendRow) => {
              const color = CHANNEL_COLORS[ch.column] || '#64748b'
              return (
                <div key={ch.column} className="venom-breakdown-row" style={{ gap: 10 }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 110 }}>
                    <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2, background: color }} />
                    {ch.label}
                  </span>
                  <Sparkline data={ch.daily} color={color} />
                  <span className="venom-breakdown-val">{currency(ch.total_spend)}</span>
                  <span
                    className={`badge ${deltaClass(ch.recent_7d_delta_pct)}`}
                    title={`Last 7d vs prior 7d. First-half avg: ${currency(ch.first_half_avg)}/d, second-half avg: ${currency(ch.second_half_avg)}/d (trend ${fmtDelta(ch.trend_pct)}).`}
                  >
                    7d {fmtDelta(ch.recent_7d_delta_pct)}
                  </span>
                </div>
              )
            })}
            {data.channels.length === 0 && (
              <div className="state-message">No channels above the spend floor in the window.</div>
            )}
          </div>
          <small className="venom-panel-footer">
            Sparkline covers {data.window.start} → {data.window.end}. Channel delta compares the
            most-recent 7 days to the 7 days before that.
          </small>
        </>
      )}
    </section>
  )
}

// ─── 2. Pacing Card ──────────────────────────────────────────────────

export function MarketingPacingCard() {
  const [data, setData] = useState<MarketingPacingResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    api.marketingPacing(controller.signal)
      .then(r => setData(r))
      .catch(err => {
        if (err?.name === 'AbortError') return
        setError(err?.message || 'failed to load pacing')
      })
      .finally(() => setLoading(false))
    return () => controller.abort()
  }, [])

  const pacingBadge = (() => {
    if (!data || data.pacing_delta_pct == null) return 'badge-neutral'
    if (data.pacing_delta_pct > 20) return 'badge-bad'   // overspending heavily
    if (data.pacing_delta_pct < -20) return 'badge-bad'  // starved — unintended pause
    if (Math.abs(data.pacing_delta_pct) < 5) return 'badge-good'
    return 'badge-neutral'
  })()

  return (
    <section className="card">
      <div className="venom-panel-head">
        <strong>Weekly pacing</strong>
        <TruthBadge state="canonical" />
        <span className="venom-panel-hint">
          {data ? `this week vs trailing ${data.baseline_window.weeks}-week avg` : '\u2014'}
        </span>
      </div>
      {loading && <div className="state-message">Loading…</div>}
      {error && <div className="state-message error">{error}</div>}
      {!loading && !error && data && (
        <>
          <div className="venom-breakdown-list" style={{ marginBottom: 8 }}>
            <div className="venom-breakdown-row">
              <span>This week so far ({data.window.days_present}d)</span>
              <span className="venom-breakdown-val">{currency(data.this_week_spend)}</span>
            </div>
            <div className="venom-breakdown-row">
              <span>Projected week-end</span>
              <span className="venom-breakdown-val">{currency(data.projected_week_end)}</span>
              <span className={`badge ${pacingBadge}`} title="Projection vs trailing 4-week weekly average">
                {fmtDelta(data.pacing_delta_pct)}
              </span>
            </div>
            <div className="venom-breakdown-row">
              <span>Baseline weekly avg</span>
              <span className="venom-breakdown-val">{currency(data.baseline_weekly_avg)}</span>
            </div>
          </div>

          {data.dormant_channels.length > 0 && (
            <>
              <div className="venom-panel-head" style={{ marginTop: 12 }}>
                <strong style={{ fontSize: 12 }}>Dormant channels</strong>
                <span className="venom-panel-hint">active historically, $0 this week</span>
              </div>
              <div className="venom-breakdown-list">
                {data.dormant_channels.map(c => (
                  <div key={c.column} className="venom-breakdown-row">
                    <span>{c.label}</span>
                    <span className="venom-breakdown-val">{currency(c.baseline_weekly_spend)}/wk</span>
                    <span className="badge badge-bad">paused</span>
                  </div>
                ))}
              </div>
            </>
          )}

          <small className="venom-panel-footer">
            Projection = daily avg across days with any spend × 7. Dormant flag fires when a
            channel averaged ≥$100/wk over the past 4 weeks but has $0 this week.
          </small>
        </>
      )}
    </section>
  )
}

// ─── 3. MER Health Card ──────────────────────────────────────────────

export function MerHealthCard({ days = 90 }: { days?: number }) {
  const [data, setData] = useState<MarketingMerHealthResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    api.marketingMerHealth({ days }, controller.signal)
      .then(r => setData(r))
      .catch(err => {
        if (err?.name === 'AbortError') return
        setError(err?.message || 'failed to load MER health')
      })
      .finally(() => setLoading(false))
    return () => controller.abort()
  }, [days])

  const stateLabel: Record<string, { label: string; className: string }> = {
    above_band: { label: 'Running hot (above p90)', className: 'badge-good' },
    below_band: { label: 'Running cold (below p10)', className: 'badge-bad' },
    in_band: { label: 'Within p10–p90 band', className: 'badge-neutral' },
    unknown: { label: '—', className: 'badge-neutral' },
  }

  return (
    <section className="card">
      <div className="venom-panel-head">
        <strong>Blended MER health</strong>
        <TruthBadge state="canonical" />
        <span className="venom-panel-hint">
          {data ? `${days}d band · ${data.observations} days observed` : '\u2014'}
        </span>
      </div>
      {loading && <div className="state-message">Loading…</div>}
      {error && <div className="state-message error">{error}</div>}
      {!loading && !error && data && (
        <>
          <div className="venom-breakdown-list" style={{ marginBottom: 8 }}>
            <div className="venom-breakdown-row">
              <span>Latest daily MER</span>
              <span className="venom-breakdown-val">
                {data.latest ? `${data.latest.mer.toFixed(2)}×` : '—'}
              </span>
              <span className={`badge ${stateLabel[data.latest_band_state].className}`}>
                {stateLabel[data.latest_band_state].label}
              </span>
            </div>
            <div className="venom-breakdown-row">
              <span>Trailing 7d MER</span>
              <span className="venom-breakdown-val">
                {data.trailing_7d_mer != null ? `${data.trailing_7d_mer.toFixed(2)}×` : '—'}
              </span>
            </div>
            <div className="venom-breakdown-row">
              <span>p10 · p50 · p90</span>
              <span className="venom-breakdown-val">
                {data.band.p10?.toFixed(2) ?? '—'} · {data.band.p50?.toFixed(2) ?? '—'} · {data.band.p90?.toFixed(2) ?? '—'}
              </span>
            </div>
          </div>
          <Sparkline
            data={data.daily.map(d => d.mer)}
            color="#22c55e"
            width={360}
            height={40}
          />
          <small className="venom-panel-footer">
            MER = KPIDaily.revenue ÷ TW.ad_spend per day. Band excludes days with zero spend or
            zero revenue. "Running cold" is a signal, not a diagnosis — could be weak creative,
            wrong channel mix, or site UX friction.
          </small>
        </>
      )}
    </section>
  )
}
