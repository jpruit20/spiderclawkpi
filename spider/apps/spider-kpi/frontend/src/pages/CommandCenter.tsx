import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, api } from '../lib/api'
import { currency, fmtInt, fmtPct, formatDateTimeET, formatFreshness } from '../lib/format'
import {
  AnomalyBar, DivisionTile, MetricTile, SparklineHero, StatusLight, TileGrid,
} from '../components/tiles'
import type { MorningBriefResponse, TelemetryAnomaly } from '../lib/types'
import type { StatusLightDetail, TileState } from '../components/tiles'

/* ─── Severity taxonomy ──────────────────────────────────────────────────
 *
 * The Command Center is a triage surface. A red pulsing dot should mean
 * "something broken or business-impacting is happening right now" — not
 * "a metric moved this week." We split signals into three tiers:
 *
 *   CRITICAL (bad)  — outage, urgent overdue DECI, critical IssueSignals,
 *                     WISMO spike, error-rate spike on an impact metric.
 *   WARN (warn)     — draft backlog, moderate z-scores on impact metrics,
 *                     revenue WoW drop >5%.
 *   INFO (info)     — interesting drift on a non-impact metric
 *                     (active_devices, cook_temp, cook_count seasonality).
 *                     Useful to glance at, not something to alert on.
 *
 * The IMPACT_METRICS allowlist is the single knob controlling this. Any
 * telemetry anomaly on a metric *not* in this list caps at `info` —
 * regardless of z-score magnitude — so cook-temp drift and device-count
 * wiggles stop masquerading as critical alerts.
 */
const IMPACT_METRICS = new Set<string>([
  'revenue',
  'orders',
  'aov',
  'cart_conversion',
  'support_tickets_created',
  'wismo_tickets_created',
  'error_rate',
  'cook_failure_rate',
  'cook_success_rate',
])

function calibratedAnomalySeverity(a: TelemetryAnomaly): TileState {
  const isImpact = IMPACT_METRICS.has(a.metric)
  if (!isImpact) return 'info'
  if (a.severity === 'critical') return 'bad'
  if (a.severity === 'warn') return 'warn'
  return 'info'
}

/** Prettify metric slug for one-line display in popovers. */
function prettyMetric(metric: string): string {
  return metric.replace(/_/g, ' ')
}

/**
 * Executive cockpit — the "coffee in hand, 8am" landing view.
 *
 * Design intent: at-a-glance visuals first, novel-length detail only
 * on drill-down. Every panel points somewhere deeper (either a
 * division page or an expanded in-context view). Reader should be
 * able to scan the page in 5-10 seconds and know whether today
 * needs attention.
 *
 * Layout (top → bottom):
 *   1) Warning lights row — 4 status lights, always visible
 *   2) Business + Fleet heroes — two big visual cards side by side
 *   3) AI Insights & Telemetry Anomalies — compact visuals that
 *      click through to deep pages
 *   4) Division tiles — 6 big navigate-to-page tiles with live state
 *   5) Today's 3 things — compact triage
 */
export function CommandCenter() {
  const [data, setData] = useState<MorningBriefResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api.morningBrief()
      .then(r => { if (!cancelled) setData(r) })
      .catch(err => { if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load morning brief') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  // NOTE: every hook must run on every render — keep all useMemo/useEffect
  // calls above the loading/error early returns below. React error #310
  // ("Rendered more hooks than during the previous render") fires if a
  // hook sits below an early return, because the first render (loading=true)
  // skips it and the second render (loading=false) runs it.
  const greeting = useMemo(() => {
    const nowET = new Date(new Date().toLocaleString('en-US', { timeZone: 'America/New_York' }))
    const hour = nowET.getHours()
    if (hour >= 5 && hour < 12) return "Good morning — here's what needs you"
    if (hour >= 12 && hour < 17) return "Good afternoon — here's where things stand"
    if (hour >= 17 && hour < 22) return "Good evening — here's the wrap-up"
    return "Burning the midnight oil — here's the state of things"
  }, [data?.generated_at])

  if (loading) return <div className="page-grid"><section className="card"><div className="state-message">Loading…</div></section></div>
  if (error || !data) return <div className="page-grid"><section className="card"><div className="state-message error">{error || 'No data'}</div></section></div>

  const h = data.headline
  const revSparkline = (data.revenue.sparkline || []).map(p => p.revenue)

  // Derive division status from morning brief data.
  const pe = derivePEStatus(data)
  const cx = deriveCXStatus(data)
  const mkt = deriveMarketingStatus(data)
  const ops = deriveOpsStatus()

  // ── Severity-calibrated counts & paraphrases for the top status lights.
  // Telemetry anomalies: only those on impact metrics count toward the
  // "alert" number; info-tier drift (cook_temp, active_devices) still
  // shows up in the popover but doesn't trigger red/warn color.
  const calibratedAnomalies = (data.anomalies || []).map(a => ({
    a, tier: calibratedAnomalySeverity(a),
  }))
  const alertingAnomalies = calibratedAnomalies.filter(x => x.tier === 'bad' || x.tier === 'warn')
  const infoAnomalies     = calibratedAnomalies.filter(x => x.tier === 'info')
  const anomaliesAlertState: TileState =
    alertingAnomalies.some(x => x.tier === 'bad') ? 'bad'
    : alertingAnomalies.length > 0 ? 'warn'
    : 'info' // all remaining are info-tier drift — blue, not red

  // Build the popover rows for each StatusLight.
  const critDetails: StatusLightDetail[] = (data.critical_signals || []).slice(0, 5).map(s => ({
    key: String(s.id),
    title: (s.title || s.signal_type || 'critical signal').slice(0, 80),
    meta: s.source || s.signal_type || undefined,
  }))
  const anomalyDetails: StatusLightDetail[] = [
    ...alertingAnomalies,
    ...infoAnomalies, // still show info drift in the popover, just uncolored
  ].slice(0, 5).map(({ a, tier }) => ({
    key: String(a.id),
    title: `${prettyMetric(a.metric)} ${a.direction} · z=${a.modified_z_score >= 0 ? '+' : ''}${a.modified_z_score.toFixed(1)}`,
    meta: tier === 'info' ? 'informational' : `${a.severity} · ${a.business_date}`,
  }))
  const wismoDetails: StatusLightDetail[] = h.wismo_last_7 > 0
    ? [{
        key: 'wismo-summary',
        title: `${h.wismo_last_7} "where is my order" ticket${h.wismo_last_7 === 1 ? '' : 's'} (7d)`,
        meta: `${h.wismo_wow_delta >= 0 ? '+' : ''}${h.wismo_wow_delta} vs prior 7d · target 0`,
      }]
    : []
  const draftDetails: StatusLightDetail[] = (data.drafts || []).slice(0, 5).map(d => ({
    key: String(d.id),
    title: d.title.slice(0, 80),
    meta: d.priority ? `${d.priority}${d.department ? ` · ${d.department}` : ''}` : d.department || undefined,
  }))

  return (
    <div className="page-grid">
      <div className="page-head" style={{ marginBottom: 2 }}>
        <h2 style={{ marginBottom: 2 }}>{greeting}</h2>
        <p style={{ margin: 0, fontSize: 12, color: 'var(--muted)' }}>
          As of {formatDateTimeET(data.generated_at)} · {data.business_date}
        </p>
      </div>

      {/* ── ROW 1 · WARNING LIGHTS ─────────────────────────────────────
          4 status lights: glanceable health scan. Always visible
          regardless of data volume. */}
      <TileGrid cols={4}>
        <StatusLight
          label="Critical signals"
          count={h.critical_signals_24h}
          alertState="bad"
          sublabel="last 24 hours · Issue Radar"
          icon="🚨"
          href="/issues"
          details={critDetails}
          viewAllHref="/issues"
          viewAllLabel="Open Issue Radar"
        />
        <StatusLight
          label="Telemetry anomalies"
          count={h.anomalies_count}
          alertState={anomaliesAlertState}
          sublabel={
            alertingAnomalies.length === 0
              ? `${infoAnomalies.length} informational${infoAnomalies.length === 1 ? '' : ''} · no impact alerts`
              : `${alertingAnomalies.length} on impact metrics`
          }
          icon="📉"
          href="/division/product-engineering"
          details={anomalyDetails}
          viewAllHref="/division/product-engineering"
          viewAllLabel="Open Product Engineering"
        />
        <StatusLight
          label="WISMO (7d, target 0)"
          count={h.wismo_last_7}
          alertState={h.wismo_last_7 > 3 ? 'bad' : 'warn'}
          sublabel={h.wismo_last_7 === 0 ? 'nobody chasing their order' : `${h.wismo_wow_delta >= 0 ? '+' : ''}${h.wismo_wow_delta} vs prior 7d`}
          icon="📦"
          href="/division/customer-experience"
          details={wismoDetails}
          viewAllHref="/division/customer-experience"
          viewAllLabel="Open Customer Experience"
        />
        <StatusLight
          label="Drafts to review"
          count={h.drafts_awaiting_review}
          alertState="info"
          sublabel="DECI awaiting decision"
          icon="📝"
          href="/deci"
          details={draftDetails}
          viewAllHref="/deci"
          viewAllLabel="Open DECI"
        />
      </TileGrid>

      {/* ── ROW 2 · BUSINESS + FLEET HEROES ────────────────────────────
          Two big visual cards that dominate the fold. Sparklines,
          gauge arcs, trend arrows. Click → deep page. */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))',
          gap: 10,
        }}
      >
        <SparklineHero
          title="Revenue · trailing 7d"
          primaryValue={currency(data.revenue.trailing_7)}
          secondaryValue={`vs ${currency(data.revenue.prior_7)} prior 7d`}
          delta={
            data.revenue.wow_pct != null
              ? `${data.revenue.wow_pct >= 0 ? '+' : ''}${data.revenue.wow_pct.toFixed(0)}%`
              : undefined
          }
          deltaDir={
            data.revenue.wow_delta > 0 ? 'up' : data.revenue.wow_delta < 0 ? 'down' : 'flat'
          }
          upIsGood
          values={revSparkline}
          state={
            data.revenue.wow_pct == null ? 'neutral'
            : data.revenue.wow_pct >= 5 ? 'good'
            : data.revenue.wow_pct >= -5 ? 'neutral'
            : 'bad'
          }
          icon="💰"
          href="/revenue"
        />
        {data.telemetry ? (
          <SparklineHero
            title="Fleet · active right now"
            primaryValue={fmtInt(data.telemetry.active_devices)}
            secondaryValue={`active devices (last 15m) · ${fmtInt(data.telemetry.engaged_devices)} cooking yesterday`}
            delta={
              data.telemetry.cook_success_rate != null
                ? `${fmtPct(data.telemetry.cook_success_rate)} success`
                : undefined
            }
            deltaDir={
              data.telemetry.cook_success_rate != null && data.telemetry.cook_success_rate >= 0.69
                ? 'up'
                : 'down'
            }
            upIsGood
            values={[]}
            state={
              data.telemetry.cook_success_rate == null ? 'neutral'
              : data.telemetry.cook_success_rate >= 0.69 ? 'good'
              : data.telemetry.cook_success_rate >= 0.55 ? 'warn'
              : 'bad'
            }
            subtitle={
              data.telemetry.error_rate != null
                ? `err rate ${fmtPct(data.telemetry.error_rate)}`
                : undefined
            }
            icon="🔥"
            href="/division/product-engineering"
          />
        ) : (
          <SparklineHero
            title="Fleet · telemetry"
            primaryValue="—"
            secondaryValue="waiting on latest materializer run"
            values={[]}
            state="neutral"
            icon="🔥"
            href="/division/product-engineering"
          />
        )}
      </div>

      {/* ── ROW 3 · ANOMALIES + INSIGHTS ───────────────────────────────
          Anomalies as centered-baseline z-score bars (no prose).
          Insights condensed to a card with click-to-expand-on-page. */}
      {(data.anomalies?.length ?? 0) > 0 && (() => {
        // Re-sort so impact-metric anomalies (warn/bad) rise to the top —
        // non-impact drift (cook_temp, active_devices) is informational
        // and shouldn't dominate the fold.
        const priorityRank: Record<TileState, number> = {
          bad: 0, warn: 1, info: 2, neutral: 3, good: 4,
        }
        const sorted = [...data.anomalies]
          .map(a => ({ a, tier: calibratedAnomalySeverity(a) }))
          .sort((x, y) => priorityRank[x.tier] - priorityRank[y.tier])
        const top = sorted.slice(0, 4)
        const anyAlerting = sorted.some(x => x.tier === 'bad' || x.tier === 'warn')
        const accent = anyAlerting ? 'var(--orange)' : '#4a7aff'
        return (
          <section className="card" style={{ borderLeft: `3px solid ${accent}` }}>
            <div className="venom-panel-head">
              <strong>Telemetry anomalies</strong>
              <Link to="/division/product-engineering" className="analysis-link">
                Product Engineering →
              </Link>
            </div>
            <div style={{ display: 'grid', gap: 6 }}>
              {top.map(({ a, tier }) => (
                <AnomalyBar
                  key={a.id}
                  metric={a.metric}
                  direction={a.direction}
                  severity={tier}
                  zScore={a.modified_z_score}
                  businessDate={a.business_date}
                  summary={a.summary || (tier === 'info' ? 'non-impact metric — informational only' : undefined)}
                  href="/division/product-engineering"
                />
              ))}
            </div>
            {sorted.length > 4 && (
              <p style={{ fontSize: 11, color: 'var(--muted)', margin: '8px 0 0', textAlign: 'right' }}>
                + {sorted.length - 4} more — click through to see all
              </p>
            )}
          </section>
        )
      })()}

      {(data.insights?.length ?? 0) > 0 && (
        <InsightsPanel insights={data.insights} highCount={h.insights_high_urgency} />
      )}

      {/* ── ROW 4 · DIVISION TILES ─────────────────────────────────────
          Each tile = a page. Status dot + 1-2 key numbers give the
          at-a-glance health; click = navigation to deep detail. */}
      <div>
        <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 8 }}>
          Jump to a division
        </div>
        <TileGrid cols={3}>
          <DivisionTile
            name="Product / Engineering"
            icon="⚙"
            href="/division/product-engineering"
            state={pe.state}
            primary={pe.primary}
            secondary={pe.secondary}
          />
          <DivisionTile
            name="Customer Experience"
            icon="☎"
            href="/division/customer-experience"
            state={cx.state}
            primary={cx.primary}
            secondary={cx.secondary}
          />
          <DivisionTile
            name="Marketing"
            icon="📣"
            href="/division/marketing"
            state={mkt.state}
            primary={mkt.primary}
            secondary={mkt.secondary}
          />
          <DivisionTile
            name="Operations"
            icon="📦"
            href="/division/operations"
            state={ops.state}
            primary={ops.primary}
            secondary={ops.secondary}
          />
          <DivisionTile
            name="DECI"
            icon="✓"
            href="/deci"
            state={h.drafts_awaiting_review > 0 ? 'info' : 'neutral'}
            primary={`${h.drafts_awaiting_review} drafts`}
            secondary="awaiting review"
          />
          <DivisionTile
            name="Issue Radar"
            icon="⚠"
            href="/issues"
            state={h.critical_signals_24h > 0 ? 'bad' : 'good'}
            primary={`${h.critical_signals_24h} critical`}
            secondary="cross-source signals · 24h"
          />
        </TileGrid>
      </div>

      {/* ── ROW 5 · COMPACT SECONDARY DETAIL ───────────────────────────
          Things that are useful but shouldn't occupy primary real estate:
          top drafts, critical signals, hot Slack thread. Shown as very
          compact rows rather than bulky cards. */}
      <SecondaryDetail data={data} />
    </div>
  )
}

/* ─── Helper sub-components ─────────────────────────────────────────── */

function InsightsPanel({
  insights,
  highCount,
}: {
  insights: MorningBriefResponse['insights']
  highCount: number
}) {
  const [expanded, setExpanded] = useState(false)
  if (!insights || insights.length === 0) return null
  const accent = highCount > 0 ? '#ef4444' : '#b88bff'

  return (
    <section className="card" style={{ borderLeft: `3px solid ${accent}` }}>
      <button
        type="button"
        onClick={() => setExpanded(x => !x)}
        style={{ background: 'none', border: 'none', padding: 0, width: '100%', cursor: 'pointer', color: 'inherit', font: 'inherit', textAlign: 'left' }}
      >
        <div className="venom-panel-head">
          <div>
            <strong>AI cross-source insights</strong>{' '}
            <span style={{ fontSize: 11, color: 'var(--muted)' }}>
              · {insights.length} observation{insights.length === 1 ? '' : 's'}
              {highCount > 0 && <span style={{ color: '#ef4444' }}> · {highCount} high-urgency</span>}
            </span>
          </div>
          <span style={{ fontSize: 12, color: 'var(--muted)' }}>{expanded ? 'hide ▴' : 'show ▾'}</span>
        </div>
      </button>
      {/* Summary view when collapsed: one-line per insight, urgency-colored dot. */}
      {!expanded && (
        <div style={{ display: 'grid', gap: 4, marginTop: 6 }}>
          {insights.map(ins => (
            <div key={ins.id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, lineHeight: 1.4 }}>
              <span
                style={{
                  display: 'inline-block',
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: ins.urgency === 'high' ? '#ef4444' : ins.urgency === 'medium' ? '#f59e0b' : '#9ca3af',
                  flexShrink: 0,
                }}
              />
              <span style={{ flex: 1 }}>{ins.title}</span>
              <span style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.3 }}>{ins.category}</span>
            </div>
          ))}
        </div>
      )}
      {/* Full detail when expanded. */}
      {expanded && (
        <div className="stack-list compact" style={{ marginTop: 8 }}>
          {insights.map(ins => (
            <div
              key={ins.id}
              className={`list-item ${ins.urgency === 'high' ? 'status-bad' : ins.urgency === 'medium' ? 'status-warn' : 'status-neutral'}`}
            >
              <div className="item-head">
                <strong style={{ fontSize: 13 }}>{ins.title}</strong>
                <div className="inline-badges">
                  <span className={`badge ${ins.urgency === 'high' ? 'badge-bad' : ins.urgency === 'medium' ? 'badge-warn' : 'badge-muted'}`} style={{ fontSize: 10 }}>
                    {ins.urgency}
                  </span>
                  <span className="badge badge-muted" style={{ fontSize: 10 }}>
                    {Math.round(ins.confidence * 100)}%
                  </span>
                </div>
              </div>
              <p style={{ fontSize: 12 }}>{ins.observation}</p>
              {ins.suggested_action && (
                <p style={{ fontSize: 11, color: 'var(--blue)', marginTop: 4 }}>
                  <strong>Suggested:</strong> {ins.suggested_action}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function SecondaryDetail({ data }: { data: MorningBriefResponse }) {
  const drafts = data.drafts || []
  const crits = data.critical_signals || []
  const stale = data.stale_tasks || []
  const slackHot = data.slack_hot
  if (!drafts.length && !crits.length && !stale.length && !slackHot) return null

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
        gap: 10,
      }}
    >
      {drafts.length > 0 && (
        <MiniListCard
          title="Drafts awaiting review"
          count={drafts.length}
          accentColor="#4a7aff"
          href="/deci"
          items={drafts.slice(0, 3).map(d => ({
            key: String(d.id),
            title: d.title,
            meta: d.priority,
          }))}
        />
      )}
      {crits.length > 0 && (
        <MiniListCard
          title="Critical signals · 24h"
          count={crits.length}
          accentColor="#ef4444"
          href="/issues"
          items={crits.slice(0, 3).map(s => ({
            key: String(s.id),
            title: (s.title || '').slice(0, 80),
            meta: s.source || '',
          }))}
        />
      )}
      {stale.length > 0 && (
        <MiniListCard
          title="Overdue tasks"
          count={stale.length}
          accentColor="#f59e0b"
          href="/division/product-engineering"
          items={stale.slice(0, 3).map(t => ({
            key: t.task_id,
            title: (t.name || '').slice(0, 80),
            meta: `${t.days_overdue}d overdue`,
          }))}
        />
      )}
      {slackHot && (
        <section className="card" style={{ borderLeft: '3px solid #4a154b' }}>
          <div className="venom-panel-head">
            <strong>Hottest Slack thread</strong>
            <span className="venom-panel-hint">{slackHot.reactions} reactions</span>
          </div>
          <p style={{ fontSize: 12, margin: '6px 0 4px' }}>
            <strong>{slackHot.user_name || '?'}</strong>
            {slackHot.ts_dt && <span style={{ color: 'var(--muted)', marginLeft: 6, fontSize: 11 }}>· {formatFreshness(slackHot.ts_dt)}</span>}
          </p>
          <p style={{ fontSize: 12, color: 'var(--muted)', margin: 0, lineHeight: 1.45 }}>
            {(slackHot.text || '').slice(0, 180)}
          </p>
        </section>
      )}
    </div>
  )
}

function MiniListCard({
  title,
  count,
  accentColor,
  items,
  href,
}: {
  title: string
  count: number
  accentColor: string
  items: { key: string; title: string; meta: string }[]
  href: string
}) {
  return (
    <section className="card" style={{ borderLeft: `3px solid ${accentColor}`, padding: '10px 14px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
        <strong style={{ fontSize: 12 }}>{title}</strong>
        <Link to={href} className="analysis-link" style={{ fontSize: 11 }}>
          {count} total →
        </Link>
      </div>
      <div style={{ display: 'grid', gap: 3 }}>
        {items.map(item => (
          <div key={item.key} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 12 }}>
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.title}</span>
            <span style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.3, flexShrink: 0 }}>
              {item.meta}
            </span>
          </div>
        ))}
      </div>
    </section>
  )
}

/* ─── Division-status derivation ────────────────────────────────────── */

type DivStatus = {
  state: 'good' | 'warn' | 'bad' | 'info' | 'neutral'
  primary: string
  secondary: string
}

function derivePEStatus(data: MorningBriefResponse): DivStatus {
  const tel = data.telemetry
  if (!tel) return { state: 'neutral', primary: '—', secondary: 'awaiting next materializer' }
  const cs = tel.cook_success_rate
  // Cook success is a true impact metric, so it can go bad; but the tile's
  // *primary* number is active-device count, which is drift-informational —
  // keep the color driven by cs only.
  const state: DivStatus['state'] =
    cs == null ? 'neutral'
    : cs >= 0.69 ? 'good'
    : cs >= 0.55 ? 'warn'
    : 'bad'
  return {
    state,
    primary: `${fmtInt(tel.active_devices)} active`,
    secondary: cs != null ? `cook success ${fmtPct(cs)}` : 'no session data yet',
  }
}

function deriveCXStatus(data: MorningBriefResponse): DivStatus {
  const h = data.headline
  const w = h.wismo_last_7
  const state: DivStatus['state'] =
    w > 3 ? 'bad'
    : w > 0 ? 'warn'
    : 'good'
  return {
    state,
    primary: `${w} WISMO`,
    secondary: `${h.wismo_wow_delta >= 0 ? '+' : ''}${h.wismo_wow_delta} vs prior 7d · target 0`,
  }
}

function deriveMarketingStatus(data: MorningBriefResponse): DivStatus {
  const wow = data.revenue.wow_pct
  // Revenue is an impact metric, so large drops earn warn/bad colors, but
  // a modest week-over-week wiggle is informational, not an alert.
  const state: DivStatus['state'] =
    wow == null ? 'neutral'
    : wow >= 5 ? 'good'
    : wow >= -10 ? 'neutral'
    : wow >= -25 ? 'warn'
    : 'bad'
  return {
    state,
    primary: currency(data.revenue.trailing_7),
    secondary: wow == null
      ? 'last 7d · no prior baseline'
      : `last 7d · ${wow >= 0 ? '+' : ''}${wow.toFixed(0)}% WoW`,
  }
}

function deriveOpsStatus(): DivStatus {
  return {
    state: 'neutral',
    primary: 'Coming soon',
    secondary: 'late-ship risk · order aging · inventory',
  }
}
