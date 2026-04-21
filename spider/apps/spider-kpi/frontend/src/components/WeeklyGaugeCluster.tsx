import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { ApiError, api } from '../lib/api'
import type { WeeklyGaugeResponse, WeeklyGauge } from '../lib/types'
import { RadialGauge } from './RadialGauge'
import { useAuth } from './AuthGate'

const OWNER_EMAIL = 'joseph@spidergrills.com'

/**
 * Weekly Priority Gauges — the Command Center top strip.
 *
 * 8 gauges selected by Opus 4.7 every Monday based on what matters most
 * for the coming week (active DECI decisions, recent incidents, 28-day
 * KPI momentum). Same 8 stay visible all week; values update live on a
 * 30-second poll. Click a gauge to drill into its home division. Hover
 * to read Opus's rationale for why THIS gauge made the cut this week.
 */
export function WeeklyGaugeCluster() {
  const [data, setData] = useState<WeeklyGaugeResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [focused, setFocused] = useState<WeeklyGauge | null>(null)
  const [regenerating, setRegenerating] = useState(false)
  const [regenMsg, setRegenMsg] = useState<string | null>(null)
  const navigate = useNavigate()
  const { user } = useAuth()
  const isOwner = (user?.email ?? '').toLowerCase() === OWNER_EMAIL

  const handleRegenerate = async () => {
    if (!confirm('Re-run Opus 4.7 to pick a fresh set of 8 weekly gauges? Pinned gauges are preserved.')) return
    setRegenerating(true)
    setRegenMsg('Opus is thinking…')
    try {
      const r = await api.regenerateWeeklyGauges()
      if (r.ok) {
        setRegenMsg(`✓ Regenerated ${r.generated} gauges in ${Math.round((r.duration_ms ?? 0) / 1000)}s. Reloading…`)
        const fresh = await api.weeklyGauges()
        setData(fresh)
        setTimeout(() => setRegenMsg(null), 4000)
      } else {
        setRegenMsg('✗ Regenerate failed — see backend logs')
      }
    } catch (e) {
      setRegenMsg(`✗ ${e instanceof ApiError ? e.message : 'Failed'}`)
    } finally {
      setRegenerating(false)
    }
  }

  useEffect(() => {
    let cancelled = false
    const pull = async () => {
      try {
        const d = await api.weeklyGauges()
        if (!cancelled) { setData(d); setError(null) }
      } catch (e) {
        if (!cancelled) setError(e instanceof ApiError ? e.message : 'Failed to load gauges')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    pull()
    const t = window.setInterval(pull, 30_000)
    return () => { cancelled = true; window.clearInterval(t) }
  }, [])

  if (loading && !data) {
    return (
      <section style={{
        background: 'linear-gradient(180deg, rgba(255,255,255,0.03) 0%, rgba(255,255,255,0.01) 100%)',
        border: '1px solid var(--border)',
        borderRadius: 16,
        padding: 16,
      }}>
        <div style={{ fontSize: 12, color: 'var(--muted)' }}>Loading weekly gauges…</div>
      </section>
    )
  }
  if (error && !data) {
    return (
      <section className="card">
        <div className="state-message" style={{ color: 'var(--red)' }}>Weekly gauges error: {error}</div>
      </section>
    )
  }
  if (!data || data.gauges.length === 0) return null

  const weekLabel = new Date(data.week_start + 'T00:00:00Z').toLocaleDateString(undefined, {
    month: 'short', day: 'numeric',
  })

  return (
    <section style={{
      position: 'relative',
      background: 'linear-gradient(180deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0.01) 100%)',
      border: '1px solid var(--border)',
      borderRadius: 16,
      padding: '16px 18px 14px',
      overflow: 'hidden',
    }}>
      {/* Ambient accent bar */}
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0, height: 3,
        background: 'linear-gradient(90deg, #10b981, #3b82f6, #8b5cf6, #ec4899, #f59e0b)',
        opacity: 0.55,
      }} />

      <header style={{
        display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
        gap: 12, marginBottom: 14, flexWrap: 'wrap',
      }}>
        <div>
          <div style={{
            fontSize: 10, color: 'var(--muted)',
            textTransform: 'uppercase', letterSpacing: 1.2, fontWeight: 600,
          }}>
            Weekly priority gauges · Opus 4.7 · week of {weekLabel}
            {data.fell_back_to_prior_week ? ' · carried over' : ''}
          </div>
          {data.overall_theme ? (
            <motion.div
              initial={{ opacity: 0, y: 2 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5 }}
              style={{ fontSize: 13, color: 'var(--fg)', marginTop: 4, maxWidth: 880, lineHeight: 1.4 }}
            >
              {data.overall_theme}
            </motion.div>
          ) : null}
        </div>
        {isOwner ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {regenMsg ? (
              <span style={{ fontSize: 11, color: 'var(--muted)' }}>{regenMsg}</span>
            ) : null}
            <button
              type="button"
              onClick={handleRegenerate}
              disabled={regenerating}
              style={{
                padding: '6px 12px',
                fontSize: 11,
                fontWeight: 600,
                letterSpacing: 0.3,
                textTransform: 'uppercase',
                color: regenerating ? 'var(--muted)' : 'var(--fg)',
                background: 'transparent',
                border: '1px solid var(--border)',
                borderRadius: 6,
                cursor: regenerating ? 'wait' : 'pointer',
              }}
              title="Owner only — re-runs Opus 4.7 to pick a fresh set of 8 gauges for this week. Pinned gauges are preserved."
            >
              {regenerating ? 'Regenerating…' : 'Regenerate'}
            </button>
          </div>
        ) : null}
      </header>

      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
        gap: 12,
      }}>
        {data.gauges.map(g => (
          <motion.div
            key={g.metric_key}
            layout
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, delay: Math.min(g.rank, 8) * 0.04 }}
          >
            <RadialGauge
              label={g.label}
              displayValue={g.display_value ?? '—'}
              value={g.value ?? null}
              sparkline={g.sparkline ?? []}
              direction={g.direction}
              target={g.target_value}
              healthyLow={g.healthy_band_low}
              healthyHigh={g.healthy_band_high}
              changePct={g.change_pct}
              rationale={g.rationale}
              category={g.category}
              unit={g.unit}
              onClick={() => setFocused(g)}
              onHover={() => { /* reserved */ }}
            />
          </motion.div>
        ))}
      </div>

      {/* Detail sheet — opens on gauge click */}
      <AnimatePresence>
        {focused ? (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setFocused(null)}
            style={{
              position: 'fixed', inset: 0, zIndex: 100,
              background: 'rgba(0,0,0,0.55)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              padding: 20,
            }}
          >
            <motion.div
              onClick={(e) => e.stopPropagation()}
              initial={{ y: 24, scale: 0.98, opacity: 0 }}
              animate={{ y: 0, scale: 1, opacity: 1 }}
              exit={{ y: 20, opacity: 0 }}
              transition={{ type: 'spring', stiffness: 240, damping: 26 }}
              style={{
                maxWidth: 520, width: '100%',
                background: 'var(--bg-elevated, #0f172a)',
                border: '1px solid var(--border)',
                borderRadius: 14,
                padding: 20,
                color: 'var(--fg)',
              }}
            >
              <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 1, fontWeight: 600 }}>
                Rank #{focused.rank} · {focused.category}
              </div>
              <div style={{ fontSize: 22, fontWeight: 600, marginTop: 4 }}>
                {focused.label} · {focused.display_value ?? '—'}
              </div>
              {focused.change_pct != null ? (
                <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 2 }}>
                  {focused.change_pct >= 0 ? '+' : ''}{focused.change_pct.toFixed(1)}% vs prior 7d
                </div>
              ) : null}

              <div style={{ marginTop: 14, fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 1 }}>
                Why this, this week
              </div>
              <div style={{ fontSize: 14, marginTop: 4, lineHeight: 1.5 }}>
                {focused.rationale}
              </div>

              <div style={{ marginTop: 14, fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 1 }}>
                What it measures
              </div>
              <div style={{ fontSize: 13, marginTop: 4, lineHeight: 1.5, color: 'var(--muted)' }}>
                {focused.description}
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 20, gap: 10, flexWrap: 'wrap' }}>
                <div style={{ fontSize: 11, color: 'var(--muted)' }}>
                  Selected by {focused.selected_by} · {focused.selected_at ? new Date(focused.selected_at).toLocaleDateString() : '—'}
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button onClick={() => setFocused(null)} style={{ padding: '6px 12px', fontSize: 12 }}>
                    Close
                  </button>
                  {focused.drill_href ? (
                    <button
                      onClick={() => { const href = focused.drill_href!; setFocused(null); navigate(href) }}
                      style={{
                        padding: '6px 14px', fontSize: 12, fontWeight: 600,
                        background: 'var(--orange)', color: '#fff', border: 'none', borderRadius: 6,
                      }}
                    >
                      Open division →
                    </button>
                  ) : null}
                </div>
              </div>
            </motion.div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </section>
  )
}
