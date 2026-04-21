import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { ApiError, api } from '../lib/api'
import { currency, fmtInt, fmtPct, formatFreshness } from '../lib/format'
import { HeroGauge } from './HeroGauges'
import { RadialGauge } from './RadialGauge'
import { useAuth } from './AuthGate'
import type { MorningBriefResponse, WeeklyGaugeResponse, WeeklyGauge } from '../lib/types'

const OWNER_EMAIL = 'joseph@spidergrills.com'
const ACCENT = '#6ea8ff'
const ACCENT_SOFT = '#39d08f'

/**
 * Unified Command Center hero — combines:
 *
 *   1) THREE ANCHOR GAUGES, always visible (never change week-over-week):
 *        • Primary: trailing 7d revenue vs prior 7d (North Star, large)
 *        • Flanking: fleet active now, cook success rate
 *      These are the executive vital signs — leadership sees them every
 *      time they open the dashboard. Having them fixed means Opus's
 *      curated slots aren't burned on the same metrics week after week.
 *
 *   2) FIVE OPUS-CURATED GAUGES, rotated weekly by Claude Opus 4.7:
 *        Picked every Monday based on what matters most this week —
 *        active DECI decisions, recent incidents, 28-day momentum. Opus
 *        is explicitly told the anchor keys and must not duplicate them.
 *        Rationale modal, regenerate button, and drill-through behavior
 *        are preserved from the original WeeklyGaugeCluster.
 *
 * One hero section, one architectural rhythm, two layers of information.
 */
export function CommandCenterHero({ data }: { data: MorningBriefResponse }) {
  const [gauges, setGauges] = useState<WeeklyGaugeResponse | null>(null)
  const [focused, setFocused] = useState<WeeklyGauge | null>(null)
  const [regenerating, setRegenerating] = useState(false)
  const [regenMsg, setRegenMsg] = useState<string | null>(null)
  const navigate = useNavigate()
  const { user } = useAuth()
  const isOwner = (user?.email ?? '').toLowerCase() === OWNER_EMAIL

  useEffect(() => {
    let cancelled = false
    const pull = async () => {
      try {
        const d = await api.weeklyGauges()
        if (!cancelled) setGauges(d)
      } catch {
        /* silent — hero still renders with anchors alone */
      }
    }
    pull()
    const t = window.setInterval(pull, 30_000)
    return () => { cancelled = true; window.clearInterval(t) }
  }, [])

  const handleRegenerate = async () => {
    if (!confirm('Re-run Opus 4.7 to pick a fresh set of weekly gauges? Pinned gauges are preserved.')) return
    setRegenerating(true)
    setRegenMsg('Opus is thinking…')
    try {
      const r = await api.regenerateWeeklyGauges()
      if (r.ok) {
        setRegenMsg(`✓ Regenerated ${r.generated} gauges in ${Math.round((r.duration_ms ?? 0) / 1000)}s`)
        const fresh = await api.weeklyGauges()
        setGauges(fresh)
        setTimeout(() => setRegenMsg(null), 4000)
      } else {
        setRegenMsg('✗ Regenerate failed')
      }
    } catch (e) {
      setRegenMsg(`✗ ${e instanceof ApiError ? e.message : 'Failed'}`)
    } finally {
      setRegenerating(false)
    }
  }

  // ── anchor data from morning brief ──────────────────────────────────
  const wow = data.revenue.wow_pct
  const progress = data.revenue.prior_7 > 0 ? data.revenue.trailing_7 / data.revenue.prior_7 : 0
  const revState: 'good' | 'warn' | 'bad' | 'neutral' =
    wow == null ? 'neutral' : wow >= 5 ? 'good' : wow >= -5 ? 'warn' : 'bad'
  const successRate = data.telemetry?.cook_success_rate
  const successState: 'good' | 'warn' | 'bad' | 'neutral' =
    successRate == null ? 'neutral'
    : successRate >= 0.69 ? 'good'
    : successRate >= 0.55 ? 'warn'
    : 'bad'

  const weekLabel = gauges?.week_start
    ? new Date(gauges.week_start + 'T00:00:00Z').toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
    : null

  return (
    <section
      style={{
        position: 'relative',
        border: '1px solid var(--border)',
        borderRadius: 14,
        padding: 18,
        background: `
          radial-gradient(ellipse at 0% 0%, ${ACCENT}14, transparent 55%),
          radial-gradient(ellipse at 100% 100%, ${ACCENT_SOFT}0c, transparent 60%),
          var(--panel)
        `,
        boxShadow: `inset 4px 0 0 0 ${ACCENT}`,
        overflow: 'hidden',
        marginBottom: 12,
      }}
    >
      {/* Header row */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
        gap: 16, flexWrap: 'wrap', marginBottom: 14,
      }}>
        <div>
          <div style={{
            fontSize: 10, color: ACCENT, textTransform: 'uppercase',
            letterSpacing: 1.2, fontWeight: 600, marginBottom: 2,
          }}>
            Division
          </div>
          <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--text)', lineHeight: 1.1 }}>
            Command Center
          </div>
          <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4, maxWidth: 640 }}>
            Executive cockpit — three always-on vital signs plus a weekly Opus 4.7 curation of what most needs attention this week.
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap' }}>
          <div style={{ fontSize: 11, color: 'var(--muted)', textAlign: 'right' }}>
            <div>Updated {formatFreshness(data.generated_at)}</div>
            <div>Business date {data.business_date}</div>
          </div>
        </div>
      </div>

      {/* ── ANCHOR ROW — primary + 2 flanking, always visible ─────────── */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(280px, 1.4fr) minmax(160px, 1fr) minmax(160px, 1fr)',
        gap: 12,
        marginBottom: 14,
      }}>
        {/* Primary — revenue North Star */}
        <HeroGauge
          signature="northStar"
          accentColor={ACCENT}
          accentColorSoft={ACCENT_SOFT}
          data={{
            label: 'Trailing 7-day revenue vs prior 7-day',
            value: currency(data.revenue.trailing_7),
            sublabel: `vs ${currency(data.revenue.prior_7)} prior 7d · ${
              wow != null ? `${wow >= 0 ? '+' : ''}${wow.toFixed(0)}% WoW` : 'WoW n/a'
            }`,
            state: revState,
            progress,
            extra: { targetLabel: 'Prior 7d' },
          }}
        />
        {/* Anchor flanking card 1 — fleet active */}
        <AnchorCard
          label="Fleet active now"
          value={data.telemetry ? fmtInt(data.telemetry.active_devices) : '—'}
          sublabel={data.telemetry ? `${fmtInt(data.telemetry.engaged_devices)} cooking yesterday` : 'telemetry offline'}
          state={data.telemetry ? 'good' : 'neutral'}
        />
        {/* Anchor flanking card 2 — cook success */}
        <AnchorCard
          label="Cook success rate"
          value={successRate != null ? fmtPct(successRate) : '—'}
          sublabel={data.telemetry?.error_rate != null ? `err rate ${fmtPct(data.telemetry.error_rate)}` : undefined}
          state={successState}
          progress={successRate ?? undefined}
        />
      </div>

      {/* ── OPUS CURATED ROW — 5 weekly gauges ────────────────────────── */}
      {gauges && gauges.gauges.length > 0 ? (
        <div>
          <div style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
            gap: 10, flexWrap: 'wrap', marginBottom: 8, paddingTop: 10,
            borderTop: '1px solid var(--border)',
          }}>
            <div>
              <div style={{
                fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase',
                letterSpacing: 1.2, fontWeight: 600,
              }}>
                Weekly priority gauges · Opus 4.7
                {weekLabel ? ` · week of ${weekLabel}` : ''}
                {gauges.fell_back_to_prior_week ? ' · carried over' : ''}
              </div>
              {gauges.overall_theme ? (
                <motion.div
                  initial={{ opacity: 0, y: 2 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.5 }}
                  style={{ fontSize: 12, color: 'var(--text)', marginTop: 4, maxWidth: 880, lineHeight: 1.4 }}
                >
                  {gauges.overall_theme}
                </motion.div>
              ) : null}
            </div>
            {isOwner ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {regenMsg ? <span style={{ fontSize: 11, color: 'var(--muted)' }}>{regenMsg}</span> : null}
                <button
                  type="button"
                  onClick={handleRegenerate}
                  disabled={regenerating}
                  style={{
                    padding: '5px 10px', fontSize: 10, fontWeight: 600, letterSpacing: 0.3,
                    textTransform: 'uppercase', color: regenerating ? 'var(--muted)' : 'var(--text)',
                    background: 'transparent', border: '1px solid var(--border)', borderRadius: 6,
                    cursor: regenerating ? 'wait' : 'pointer',
                  }}
                >
                  {regenerating ? 'Regenerating…' : 'Regenerate'}
                </button>
              </div>
            ) : null}
          </div>
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))',
            gap: 10,
          }}>
            {gauges.gauges.map(g => (
              <motion.div
                key={g.metric_key}
                layout
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.35, delay: Math.min(g.rank, 5) * 0.04 }}
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
                  onHover={() => {/* reserved */}}
                />
              </motion.div>
            ))}
          </div>
        </div>
      ) : null}

      {/* Detail sheet — Opus rationale modal, preserved from the original WeeklyGaugeCluster. */}
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
                color: 'var(--text)',
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

      {/* Bottom accent gradient. */}
      <div aria-hidden style={{
        position: 'absolute', left: 0, right: 0, bottom: 0, height: 2,
        background: `linear-gradient(90deg, ${ACCENT} 0%, ${ACCENT_SOFT} 70%, transparent 100%)`,
        opacity: 0.7,
      }} />
    </section>
  )
}

/* ── small anchor card (matches the HeroFlanking look inside DivisionHero) ── */

function AnchorCard({
  label, value, sublabel, state, progress,
}: {
  label: string
  value: string
  sublabel?: string
  state?: 'good' | 'warn' | 'bad' | 'neutral'
  progress?: number
}) {
  const color = state === 'good' ? 'var(--green)' : state === 'warn' ? 'var(--orange)' : state === 'bad' ? 'var(--red)' : 'var(--muted)'
  return (
    <div style={{
      padding: 14,
      border: '1px solid var(--border)',
      borderRadius: 12,
      background: 'rgba(0,0,0,0.25)',
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'space-between',
      minHeight: 180,
    }}>
      <div>
        <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 1 }}>
          Anchor
        </div>
        <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 2 }}>{label}</div>
      </div>
      <div>
        <div style={{ fontSize: 36, fontWeight: 700, color, lineHeight: 1, letterSpacing: -0.5 }}>
          {value}
        </div>
        {sublabel ? (
          <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 6 }}>{sublabel}</div>
        ) : null}
        {progress != null ? (
          <div style={{ height: 4, background: 'rgba(255,255,255,0.06)', borderRadius: 2, overflow: 'hidden', marginTop: 10 }}>
            <div style={{
              height: '100%',
              width: `${Math.max(0, Math.min(1, progress)) * 100}%`,
              background: color,
              transition: 'width 500ms ease-out',
            }} />
          </div>
        ) : null}
      </div>
    </div>
  )
}
