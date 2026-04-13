import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { VenomKpiStrip, KpiCardDef } from '../components/VenomKpiStrip'
import { ApiError, api } from '../lib/api'
import { currency, deltaPct, deltaDirection, fmtPct, fmtInt } from '../lib/format'
import {
  IssueRadarResponse, KPIDaily, OverviewResponse, SourceHealthItem,
  SupportOverviewResponse, SocialPulse, MarketIntelligence,
  DeciOverview, YouTubePerformance,
} from '../lib/types'
import {
  ResponsiveContainer, AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, Cell,
} from 'recharts'

function sum(rows: KPIDaily[], key: keyof KPIDaily) {
  return rows.reduce((s, r) => s + (Number(r[key]) || 0), 0)
}
function avg(rows: KPIDaily[], key: keyof KPIDaily) {
  if (!rows.length) return 0
  return rows.reduce((s, r) => s + (Number(r[key]) || 0), 0) / rows.length
}

function sentimentLabel(score: number): { text: string; badge: string } {
  if (score >= 0.6) return { text: 'Very Positive', badge: 'badge-good' }
  if (score >= 0.3) return { text: 'Positive', badge: 'badge-good' }
  if (score >= -0.1) return { text: 'Neutral', badge: 'badge-neutral' }
  if (score >= -0.4) return { text: 'Negative', badge: 'badge-bad' }
  return { text: 'Very Negative', badge: 'badge-bad' }
}

function hoursToLabel(hours: number | null): string {
  if (hours == null || isNaN(hours)) return '\u2014'
  if (hours < 24) return `${Math.round(hours)}h`
  const days = Math.round(hours / 24)
  return `${days}d`
}

export function CommandCenter() {
  const [overview, setOverview] = useState<OverviewResponse | null>(null)
  const [support, setSupport] = useState<SupportOverviewResponse | null>(null)
  const [issues, setIssues] = useState<IssueRadarResponse | null>(null)
  const [pulse, setPulse] = useState<SocialPulse | null>(null)
  const [market, setMarket] = useState<MarketIntelligence | null>(null)
  const [deci, setDeci] = useState<DeciOverview | null>(null)
  const [youtube, setYoutube] = useState<YouTubePerformance | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const [o, s, i, p, m, d, yt] = await Promise.all([
          api.overview(),
          api.supportOverview(),
          api.issues(),
          api.socialPulse(30).catch(() => null),
          api.marketIntelligence(30).catch(() => null),
          api.deciOverview().catch(() => null),
          api.youtubePerformance(30).catch(() => null),
        ])
        if (cancelled) return
        setOverview(o)
        setSupport(s)
        setIssues(i)
        setPulse(p)
        setMarket(m)
        setDeci(d)
        setYoutube(yt)
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load dashboard')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => { cancelled = true }
  }, [])

  // --- Core KPI computations ---
  const rows = overview?.daily_series || []
  const last7 = rows.slice(-7)
  const prior7 = rows.slice(-14, -7)
  const last30 = rows.slice(-30)
  const rev7 = sum(last7, 'revenue')
  const revPrior7 = sum(prior7, 'revenue')
  const ord7 = sum(last7, 'orders')
  const ordPrior7 = sum(prior7, 'orders')
  const sess7 = sum(last7, 'sessions')
  const sessPrior7 = sum(prior7, 'sessions')
  const conv7 = last7.length ? avg(last7, 'conversion_rate') : 0
  const convPrior7 = prior7.length ? avg(prior7, 'conversion_rate') : 0
  const aov7 = ord7 > 0 ? rev7 / ord7 : 0
  const aovPrior7 = ordPrior7 > 0 ? revPrior7 / ordPrior7 : 0
  const adSpend7 = sum(last7, 'ad_spend')
  const mer7 = adSpend7 > 0 ? rev7 / adSpend7 : 0
  const adSpendPrior7 = sum(prior7, 'ad_spend')
  const merPrior7 = adSpendPrior7 > 0 ? revPrior7 / adSpendPrior7 : 0

  // --- Support ---
  const supportRows = (support?.rows || []) as KPIDaily[]
  const latestSupport = supportRows.length ? supportRows[supportRows.length - 1] : null
  const openBacklog = latestSupport?.open_backlog ?? 0
  const csat = latestSupport?.csat ?? null
  const firstResponseTime = latestSupport?.first_response_time ?? null

  // --- Telemetry ---
  const telemetry = overview?.telemetry || null
  const fleetReliability = telemetry?.latest?.session_reliability_score ?? null
  const activeDevices = telemetry?.collection_metadata?.active_devices_last_24h ?? null

  // --- Sources ---
  const sourceHealth = overview?.source_health || []
  const degradedSources = sourceHealth.filter((s: SourceHealthItem) => s.derived_status === 'unhealthy' || s.derived_status === 'stale')

  // --- Issues ---
  const topCluster = issues?.highest_business_risk?.[0] || issues?.clusters?.[0] || null

  // --- Social/Market ---
  const sentimentScore = pulse?.avg_sentiment_score ?? null
  const brandMentions = pulse?.brand_mentions ?? 0
  const totalMentions = pulse?.total_mentions ?? 0
  const sov = market?.competitive_landscape?.brand_share_of_voice ?? null
  const competitors = market?.competitive_landscape?.competitors || []
  const topCompetitor = competitors.length ? competitors.reduce((a, b) => a.share_of_voice > b.share_of_voice ? a : b) : null

  // --- DECI ---
  const deciVelocity = deci?.velocity || null
  const bottleneckCount = deci ? ((deci.bottlenecks?.no_driver?.length ?? 0) + (deci.bottlenecks?.stale?.length ?? 0)) : 0
  const escalationCount = deci?.escalation_warnings?.length || 0
  const criticalDecisions = deci?.critical_feed?.slice(0, 5) || []

  // --- YouTube ---
  const ytViews = youtube?.total_views ?? 0
  const ytVideos = youtube?.total_videos ?? 0
  const ytEngagement = youtube?.avg_engagement_rate ?? 0

  // --- KPI Strip (6 cards) ---
  const kpiCards = useMemo<KpiCardDef[]>(() => [
    {
      label: 'Revenue (7d)',
      value: currency(rev7),
      sub: `${fmtInt(ord7)} orders`,
      truthState: 'canonical',
      delta: { text: deltaPct(rev7, revPrior7) + ' WoW', direction: deltaDirection(rev7, revPrior7) },
    },
    {
      label: 'AOV',
      value: currency(aov7),
      sub: '7-day avg',
      truthState: 'canonical',
      delta: { text: deltaPct(aov7, aovPrior7) + ' WoW', direction: deltaDirection(aov7, aovPrior7) },
    },
    {
      label: 'Conversion',
      value: fmtPct(conv7 / 100, 2),
      sub: `${fmtInt(sess7)} sessions`,
      truthState: 'canonical',
      delta: { text: deltaPct(conv7, convPrior7) + ' WoW', direction: deltaDirection(conv7, convPrior7) },
    },
    {
      label: 'Support Queue',
      value: fmtInt(openBacklog),
      sub: csat != null ? `CSAT ${(csat * 100).toFixed(0)}%` : 'open tickets',
      truthState: 'canonical',
      delta: openBacklog > 150 ? { text: 'Over capacity', direction: 'down' as const } : openBacklog < 80 ? { text: 'Healthy', direction: 'up' as const } : { text: 'Elevated', direction: 'flat' as const },
    },
    {
      label: 'Brand Sentiment',
      value: sentimentScore != null ? `${(sentimentScore * 100).toFixed(0)}%` : '\u2014',
      sub: `${fmtInt(brandMentions)} mentions (30d)`,
      truthState: pulse ? 'canonical' : 'unavailable',
      delta: sentimentScore != null ? { text: sentimentLabel(sentimentScore).text, direction: sentimentScore >= 0.2 ? 'up' as const : sentimentScore <= -0.1 ? 'down' as const : 'flat' as const } : undefined,
    },
    {
      label: 'Fleet Health',
      value: fleetReliability != null ? fmtPct(fleetReliability) : '\u2014',
      sub: activeDevices != null ? `${fmtInt(activeDevices)} devices (24h)` : '',
      truthState: telemetry ? 'proxy' : 'unavailable',
    },
  ], [rev7, revPrior7, ord7, ordPrior7, aov7, aovPrior7, conv7, convPrior7, sess7, openBacklog, csat, sentimentScore, brandMentions, fleetReliability, activeDevices, telemetry, pulse])

  // --- Chart data ---
  const revenueChartRows = useMemo(() => {
    return last30.map((r) => ({
      date: r.business_date.slice(5),
      revenue: Math.round(r.revenue),
      orders: r.orders,
    }))
  }, [last30])

  const sovChartData = useMemo(() => {
    if (!market?.competitive_landscape) return []
    const data: { name: string; sov: number; color: string }[] = [
      { name: 'Spider', sov: Math.round((market.competitive_landscape.brand_share_of_voice || 0) * 100), color: '#60a5fa' },
    ]
    for (const c of competitors.slice(0, 5)) {
      data.push({ name: c.competitor || 'Unknown', sov: Math.round((c.share_of_voice || 0) * 100), color: '#4b5563' })
    }
    return data.sort((a, b) => b.sov - a.sov)
  }, [market, competitors])

  // --- Division tiles ---
  const divisions = [
    { path: '/division/customer-experience', label: 'Customer Experience', owner: 'Jeremiah', metric: `${fmtInt(openBacklog)} tickets`, health: openBacklog > 150 ? 'bad' : openBacklog > 80 ? 'warn' : 'good' },
    { path: '/division/marketing', label: 'Marketing', owner: 'Bailey', metric: `Conv ${fmtPct(conv7 / 100, 2)}`, health: deltaDirection(conv7, convPrior7) === 'up' ? 'good' : deltaDirection(conv7, convPrior7) === 'down' ? 'warn' : 'good' },
    { path: '/division/product-engineering', label: 'Product & Engineering', owner: 'Kyle', metric: fleetReliability != null ? `Fleet ${fmtPct(fleetReliability)}` : 'Loading', health: fleetReliability != null && fleetReliability >= 0.9 ? 'good' : 'warn' },
    { path: '/division/operations', label: 'Operations', owner: 'Conor', metric: degradedSources.length ? `${degradedSources.length} degraded` : 'All systems go', health: degradedSources.length > 0 ? 'warn' : 'good' },
    { path: '/division/production-manufacturing', label: 'Manufacturing', owner: 'David', metric: 'Production', health: 'good' },
    { path: '/social', label: 'Social Intelligence', owner: 'Bailey', metric: `${fmtInt(totalMentions)} mentions`, health: sentimentScore != null && sentimentScore >= 0.2 ? 'good' : sentimentScore != null && sentimentScore < 0 ? 'bad' : 'good' },
    { path: '/revenue', label: 'Revenue Engine', owner: 'Finance', metric: currency(rev7), health: deltaDirection(rev7, revPrior7) === 'down' ? 'warn' : 'good' },
    { path: '/deci', label: 'DECI Framework', owner: 'Joseph', metric: bottleneckCount > 0 ? `${bottleneckCount} bottleneck${bottleneckCount !== 1 ? 's' : ''}` : 'On track', health: bottleneckCount > 3 ? 'warn' : 'good' },
    { path: '/issues', label: 'Issue Radar', owner: 'Cross-team', metric: `${issues?.clusters?.length || 0} clusters`, health: topCluster?.severity === 'high' ? 'bad' : 'good' },
    { path: '/system-health', label: 'System Health', owner: 'Ops', metric: degradedSources.length ? `${degradedSources.length} degraded` : 'All healthy', health: degradedSources.length > 0 ? 'warn' : 'good' },
  ]

  const healthDot = (h: string) => h === 'good' ? '#34d399' : h === 'warn' ? '#fbbf24' : '#f87171'

  return (
    <div className="page-grid venom-page">
      <div className="venom-header">
        <div>
          <h2 className="venom-title">Spider Command Center</h2>
          <p className="venom-subtitle">Executive overview &mdash; {new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })}</p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {degradedSources.length > 0 ? (
            <span className="badge badge-warn">{degradedSources.length} degraded source{degradedSources.length > 1 ? 's' : ''}</span>
          ) : (
            <span className="badge badge-good">All sources healthy</span>
          )}
          {bottleneckCount > 0 ? (
            <span className="badge badge-warn">{bottleneckCount} DECI bottleneck{bottleneckCount !== 1 ? 's' : ''}</span>
          ) : null}
        </div>
      </div>

      {loading ? <Card title="Loading"><div className="state-message">Loading command center…</div></Card> : null}
      {error ? <Card title="Error"><div className="state-message error">{error}</div></Card> : null}

      {!loading && !error ? (
        <>
          <VenomKpiStrip cards={kpiCards} />

          {/* Week-over-week performance badges */}
          <div className="scope-note" style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
            <span style={{ fontSize: 11, color: 'var(--muted)', fontWeight: 600 }}>7d vs prior:</span>
            <span className={`badge ${deltaDirection(rev7, revPrior7) === 'up' ? 'badge-good' : deltaDirection(rev7, revPrior7) === 'down' ? 'badge-bad' : 'badge-neutral'}`}>Revenue {deltaPct(rev7, revPrior7)}</span>
            <span className={`badge ${deltaDirection(ord7, ordPrior7) === 'up' ? 'badge-good' : deltaDirection(ord7, ordPrior7) === 'down' ? 'badge-bad' : 'badge-neutral'}`}>Orders {deltaPct(ord7, ordPrior7)}</span>
            <span className={`badge ${deltaDirection(sess7, sessPrior7) === 'up' ? 'badge-good' : deltaDirection(sess7, sessPrior7) === 'down' ? 'badge-bad' : 'badge-neutral'}`}>Sessions {deltaPct(sess7, sessPrior7)}</span>
            {adSpend7 > 0 ? <span className={`badge ${deltaDirection(mer7, merPrior7) === 'up' ? 'badge-good' : deltaDirection(mer7, merPrior7) === 'down' ? 'badge-bad' : 'badge-neutral'}`}>MER {mer7.toFixed(1)}x</span> : null}
          </div>

          {/* ═══════════════════════════════════════════════════════ */}
          {/* EXECUTIVE BRIEFING                                      */}
          {/* ═══════════════════════════════════════════════════════ */}
          <section className="card">
            <div className="venom-panel-head">
              <strong>Executive Briefing</strong>
              <span className="venom-panel-hint">{new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' })}</span>
            </div>
            <div className="stack-list compact">
              {/* Revenue Headline */}
              <div className={`list-item status-${deltaDirection(rev7, revPrior7) === 'up' ? 'good' : deltaDirection(rev7, revPrior7) === 'down' ? 'bad' : 'muted'}`}>
                <div className="item-head">
                  <strong>Revenue: {currency(rev7)} this week</strong>
                  <span className={`badge ${deltaDirection(rev7, revPrior7) === 'up' ? 'badge-good' : deltaDirection(rev7, revPrior7) === 'down' ? 'badge-bad' : 'badge-neutral'}`}>{deltaPct(rev7, revPrior7)} WoW</span>
                </div>
                <p>{fmtInt(ord7)} orders at {currency(aov7)} AOV.{adSpend7 > 0 ? ` Ad spend ${currency(adSpend7)}, MER ${mer7.toFixed(1)}x.` : ''}</p>
              </div>

              {/* Top Issue */}
              {topCluster ? (
                <div className={`list-item status-${topCluster.severity === 'high' ? 'bad' : 'warn'}`}>
                  <div className="item-head">
                    <strong>#1 Issue: {topCluster.title}</strong>
                    <div className="inline-badges">
                      <span className={`badge ${topCluster.severity === 'high' ? 'severity-high' : 'severity-medium'}`}>{topCluster.severity}</span>
                      {topCluster.owner_team ? <span className="badge badge-muted">{topCluster.owner_team}</span> : null}
                    </div>
                  </div>
                  <p>{(topCluster.details_json as Record<string, unknown>)?.priority_reason_summary as string || 'Review escalation queue for details'}</p>
                </div>
              ) : (
                <div className="list-item status-good">
                  <strong>No high-priority issues detected</strong>
                  <p>Issue radar is clear — focus on growth initiatives.</p>
                </div>
              )}

              {/* Support Status */}
              <div className={`list-item status-${openBacklog > 150 ? 'bad' : openBacklog > 80 ? 'warn' : 'good'}`}>
                <div className="item-head">
                  <strong>Support: {fmtInt(openBacklog)} open tickets</strong>
                  <div className="inline-badges">
                    <span className={`badge ${openBacklog > 150 ? 'badge-bad' : openBacklog > 80 ? 'badge-warn' : 'badge-good'}`}>{openBacklog > 150 ? 'Over capacity' : openBacklog > 80 ? 'Elevated' : 'Healthy'}</span>
                    {csat != null ? <span className="badge badge-neutral">CSAT {(csat * 100).toFixed(0)}%</span> : null}
                    {firstResponseTime != null ? <span className="badge badge-muted">FRT {Math.round(firstResponseTime / 60)}m</span> : null}
                  </div>
                </div>
              </div>

              {/* Brand Health */}
              {pulse ? (
                <div className={`list-item status-${sentimentScore != null && sentimentScore >= 0.2 ? 'good' : sentimentScore != null && sentimentScore < 0 ? 'bad' : 'muted'}`}>
                  <div className="item-head">
                    <strong>Brand: {sentimentLabel(sentimentScore ?? 0).text} sentiment</strong>
                    <div className="inline-badges">
                      <span className={`badge ${sentimentLabel(sentimentScore ?? 0).badge}`}>{sentimentScore != null ? `${(sentimentScore * 100).toFixed(0)}%` : '\u2014'}</span>
                      <span className="badge badge-neutral">{fmtInt(brandMentions)} mentions</span>
                      {sov != null ? <span className="badge badge-muted">SOV {(sov * 100).toFixed(0)}%</span> : null}
                    </div>
                  </div>
                  {topCompetitor ? <p>Top competitor: {topCompetitor.competitor} at {((topCompetitor.share_of_voice ?? 0) * 100).toFixed(0)}% SOV with {fmtInt(topCompetitor.mentions)} mentions.</p> : null}
                </div>
              ) : null}

              {/* DECI Bottlenecks */}
              {deci && bottleneckCount > 0 ? (
                <div className="list-item status-warn">
                  <div className="item-head">
                    <strong>Decisions: {bottleneckCount} bottleneck{bottleneckCount !== 1 ? 's' : ''}</strong>
                    <div className="inline-badges">
                      {(deci.bottlenecks?.no_driver?.length ?? 0) > 0 ? <span className="badge badge-bad">{deci.bottlenecks.no_driver.length} no driver</span> : null}
                      {(deci.bottlenecks?.stale?.length ?? 0) > 0 ? <span className="badge badge-warn">{deci.bottlenecks.stale.length} stale</span> : null}
                      {escalationCount > 0 ? <span className="badge badge-bad">{escalationCount} escalation{escalationCount !== 1 ? 's' : ''}</span> : null}
                    </div>
                  </div>
                </div>
              ) : deci ? (
                <div className="list-item status-good">
                  <div className="item-head">
                    <strong>Decisions: All on track</strong>
                    {deciVelocity ? <span className="badge badge-good">{deciVelocity.completed_decisions}/{deciVelocity.total_decisions} complete</span> : null}
                  </div>
                </div>
              ) : null}

              {/* Data Trust */}
              <div className={`list-item status-${degradedSources.length > 0 ? 'warn' : 'muted'}`}>
                <div className="item-head">
                  <strong>Data Trust</strong>
                  <span className={`badge ${degradedSources.length > 0 ? 'badge-warn' : 'badge-good'}`}>{degradedSources.length > 0 ? `${degradedSources.length} degraded` : 'All healthy'}</span>
                </div>
                {degradedSources.length > 0 ? <p>Degraded: {degradedSources.map((s: SourceHealthItem) => s.source).join(', ')}</p> : null}
              </div>
            </div>
          </section>

          {/* ═══════════════════════════════════════════════════════ */}
          {/* REVENUE & COMMERCE                                      */}
          {/* ═══════════════════════════════════════════════════════ */}
          <section className="card">
            <div className="venom-panel-head">
              <div>
                <strong>Revenue &amp; Commerce</strong>
                <p className="venom-chart-sub">{currency(rev7)} trailing 7d &middot; {currency(sum(last30, 'revenue'))} trailing 30d</p>
              </div>
              <Link to="/revenue" className="analysis-link">Full report &#x2197;</Link>
            </div>

            {/* Commerce KPI row */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 10, marginBottom: 16 }}>
              {[
                { label: 'Revenue (7d)', value: currency(rev7), delta: deltaPct(rev7, revPrior7), dir: deltaDirection(rev7, revPrior7) },
                { label: 'Orders (7d)', value: fmtInt(ord7), delta: deltaPct(ord7, ordPrior7), dir: deltaDirection(ord7, ordPrior7) },
                { label: 'AOV', value: currency(aov7), delta: deltaPct(aov7, aovPrior7), dir: deltaDirection(aov7, aovPrior7) },
                { label: 'Sessions (7d)', value: fmtInt(sess7), delta: deltaPct(sess7, sessPrior7), dir: deltaDirection(sess7, sessPrior7) },
                { label: 'Conversion', value: fmtPct(conv7 / 100, 2), delta: deltaPct(conv7, convPrior7), dir: deltaDirection(conv7, convPrior7) },
                ...(adSpend7 > 0 ? [
                  { label: 'Ad Spend (7d)', value: currency(adSpend7), delta: deltaPct(adSpend7, adSpendPrior7), dir: deltaDirection(adSpendPrior7, adSpend7) },
                  { label: 'MER', value: `${mer7.toFixed(1)}x`, delta: deltaPct(mer7, merPrior7), dir: deltaDirection(mer7, merPrior7) },
                ] : []),
              ].map((m) => (
                <div key={m.label} style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 8, padding: '10px 12px' }}>
                  <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 2 }}>{m.label}</div>
                  <div style={{ fontSize: 18, fontWeight: 700, color: '#e2e8f0' }}>{m.value}</div>
                  <div style={{ fontSize: 11, color: m.dir === 'up' ? 'var(--green)' : m.dir === 'down' ? '#f87171' : 'var(--muted)', marginTop: 2 }}>{m.delta} WoW</div>
                </div>
              ))}
            </div>

            {/* Revenue chart — 30 days */}
            {revenueChartRows.length > 0 ? (
              <div className="chart-wrap-short">
                <ResponsiveContainer width="100%" height={200}>
                  <AreaChart data={revenueChartRows}>
                    <CartesianGrid stroke="rgba(255,255,255,0.08)" />
                    <XAxis dataKey="date" stroke="#9fb0d4" tick={{ fontSize: 10 }} interval={Math.max(0, Math.floor(revenueChartRows.length / 8))} />
                    <YAxis stroke="#9fb0d4" tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`} />
                    <Tooltip formatter={(value: number) => [currency(value), 'Revenue']} />
                    <Area type="monotone" dataKey="revenue" fill="rgba(110,168,255,0.15)" stroke="var(--blue)" strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            ) : <div className="state-message">No revenue data available.</div>}
          </section>

          {/* ═══════════════════════════════════════════════════════ */}
          {/* BRAND & MARKET INTELLIGENCE                              */}
          {/* ═══════════════════════════════════════════════════════ */}
          {(pulse || market || youtube) ? (
            <section className="card">
              <div className="venom-panel-head">
                <div>
                  <strong>Brand &amp; Market Intelligence</strong>
                  <p className="venom-chart-sub">30-day social &amp; competitive landscape</p>
                </div>
                <Link to="/social" className="analysis-link">Full report &#x2197;</Link>
              </div>

              {/* Brand metrics row */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 10, marginBottom: 16 }}>
                {pulse ? (
                  <>
                    <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 8, padding: '10px 12px' }}>
                      <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 2 }}>Brand Sentiment</div>
                      <div style={{ fontSize: 18, fontWeight: 700, color: sentimentScore != null && sentimentScore >= 0.2 ? '#34d399' : sentimentScore != null && sentimentScore < 0 ? '#f87171' : '#e2e8f0' }}>
                        {sentimentScore != null ? `${(sentimentScore * 100).toFixed(0)}%` : '\u2014'}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{sentimentLabel(sentimentScore ?? 0).text}</div>
                    </div>
                    <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 8, padding: '10px 12px' }}>
                      <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 2 }}>Total Mentions</div>
                      <div style={{ fontSize: 18, fontWeight: 700, color: '#e2e8f0' }}>{fmtInt(totalMentions)}</div>
                      <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{fmtInt(brandMentions)} brand</div>
                    </div>
                  </>
                ) : null}
                {sov != null ? (
                  <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 8, padding: '10px 12px' }}>
                    <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 2 }}>Share of Voice</div>
                    <div style={{ fontSize: 18, fontWeight: 700, color: '#60a5fa' }}>{(sov * 100).toFixed(0)}%</div>
                    <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>vs {competitors.length} competitors</div>
                  </div>
                ) : null}
                {youtube ? (
                  <>
                    <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 8, padding: '10px 12px' }}>
                      <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 2 }}>YouTube Reach</div>
                      <div style={{ fontSize: 18, fontWeight: 700, color: '#e2e8f0' }}>{fmtInt(ytViews)}</div>
                      <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{ytVideos} videos</div>
                    </div>
                    <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 8, padding: '10px 12px' }}>
                      <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 2 }}>YT Engagement</div>
                      <div style={{ fontSize: 18, fontWeight: 700, color: '#e2e8f0' }}>{(ytEngagement * 100).toFixed(1)}%</div>
                      <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{fmtInt(youtube.total_likes)} likes</div>
                    </div>
                  </>
                ) : null}
                {market?.amazon_positioning?.price ? (
                  <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 8, padding: '10px 12px' }}>
                    <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 2 }}>Amazon Pricing</div>
                    <div style={{ fontSize: 18, fontWeight: 700, color: '#e2e8f0' }}>{currency(market.amazon_positioning.price.our_avg_price)}</div>
                    <div style={{ fontSize: 11, color: market.amazon_positioning.price.price_delta_pct > 0 ? '#fbbf24' : '#34d399', marginTop: 2 }}>
                      {market.amazon_positioning.price.price_delta_pct > 0 ? '+' : ''}{market.amazon_positioning.price.price_delta_pct.toFixed(0)}% vs competitors
                    </div>
                  </div>
                ) : null}
              </div>

              {/* Share of Voice chart */}
              {sovChartData.length > 1 ? (
                <>
                  <div style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 600, marginBottom: 8 }}>Share of Voice — Spider vs Competitors</div>
                  <div className="chart-wrap-short">
                    <ResponsiveContainer width="100%" height={160}>
                      <BarChart data={sovChartData} layout="vertical" margin={{ left: 80 }}>
                        <CartesianGrid stroke="rgba(255,255,255,0.06)" horizontal={false} />
                        <XAxis type="number" stroke="#9fb0d4" tick={{ fontSize: 10 }} tickFormatter={(v: number) => `${v}%`} domain={[0, 100]} />
                        <YAxis type="category" dataKey="name" stroke="#9fb0d4" tick={{ fontSize: 11 }} width={75} />
                        <Tooltip formatter={(value: number) => [`${value}%`, 'Share of Voice']} />
                        <Bar dataKey="sov" radius={[0, 4, 4, 0]} barSize={18}>
                          {sovChartData.map((entry, idx) => (
                            <Cell key={idx} fill={entry.color} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </>
              ) : null}

              {/* Sentiment breakdown */}
              {pulse?.sentiment_breakdown ? (
                <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
                  {Object.entries(pulse.sentiment_breakdown).map(([label, count]) => (
                    <div key={label} style={{
                      padding: '4px 10px', borderRadius: 6, fontSize: 11,
                      background: label === 'positive' ? 'rgba(16,185,129,0.15)' : label === 'negative' ? 'rgba(239,68,68,0.15)' : 'rgba(255,255,255,0.05)',
                      color: label === 'positive' ? '#34d399' : label === 'negative' ? '#f87171' : '#9ca3af',
                    }}>
                      {label}: {count}
                    </div>
                  ))}
                </div>
              ) : null}
            </section>
          ) : null}

          {/* ═══════════════════════════════════════════════════════ */}
          {/* DECISION PIPELINE                                       */}
          {/* ═══════════════════════════════════════════════════════ */}
          {deci ? (
            <section className="card">
              <div className="venom-panel-head">
                <div>
                  <strong>Decision Pipeline</strong>
                  <p className="venom-chart-sub">DECI framework velocity &amp; health</p>
                </div>
                <Link to="/deci" className="analysis-link">Full framework &#x2197;</Link>
              </div>

              {/* Velocity metrics */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 10, marginBottom: 16 }}>
                <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 8, padding: '10px 12px' }}>
                  <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 2 }}>Total Decisions</div>
                  <div style={{ fontSize: 18, fontWeight: 700, color: '#e2e8f0' }}>{deciVelocity?.total_decisions ?? 0}</div>
                  <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{deciVelocity?.completed_decisions ?? 0} complete</div>
                </div>
                <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 8, padding: '10px 12px' }}>
                  <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 2 }}>Avg Time to Decision</div>
                  <div style={{ fontSize: 18, fontWeight: 700, color: '#e2e8f0' }}>{hoursToLabel(deciVelocity?.avg_creation_to_decision_hours ?? null)}</div>
                  <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>creation &rarr; decided</div>
                </div>
                <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 8, padding: '10px 12px' }}>
                  <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 2 }}>Avg Time to Complete</div>
                  <div style={{ fontSize: 18, fontWeight: 700, color: '#e2e8f0' }}>{hoursToLabel(deciVelocity?.avg_decision_to_complete_hours ?? null)}</div>
                  <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>decided &rarr; complete</div>
                </div>
                <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 8, padding: '10px 12px' }}>
                  <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 2 }}>Bottlenecks</div>
                  <div style={{ fontSize: 18, fontWeight: 700, color: bottleneckCount > 0 ? '#fbbf24' : '#34d399' }}>{bottleneckCount}</div>
                  <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{escalationCount} escalation{escalationCount !== 1 ? 's' : ''}</div>
                </div>
              </div>

              {/* Bottleneck details */}
              {bottleneckCount > 0 ? (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 600, marginBottom: 6 }}>Requires Attention</div>
                  <div className="stack-list compact">
                    {(deci.bottlenecks?.no_driver || []).slice(0, 3).map(b => (
                      <Link key={b.id} to="/deci" className="list-item status-bad" style={{ textDecoration: 'none', color: 'inherit' }}>
                        <div className="item-head">
                          <strong>{b.title}</strong>
                          <div className="inline-badges">
                            <span className="badge badge-bad">No driver</span>
                            <span className={`badge ${b.priority === 'critical' ? 'severity-high' : b.priority === 'high' ? 'severity-medium' : 'badge-muted'}`}>{b.priority}</span>
                          </div>
                        </div>
                      </Link>
                    ))}
                    {(deci.bottlenecks?.stale || []).slice(0, 3).map(b => (
                      <Link key={b.id} to="/deci" className="list-item status-warn" style={{ textDecoration: 'none', color: 'inherit' }}>
                        <div className="item-head">
                          <strong>{b.title}</strong>
                          <div className="inline-badges">
                            <span className="badge badge-warn">Stale</span>
                            <span className="badge badge-muted">{b.reason}</span>
                          </div>
                        </div>
                      </Link>
                    ))}
                  </div>
                </div>
              ) : null}

              {/* Critical decisions feed */}
              {criticalDecisions.length > 0 ? (
                <>
                  <div style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 600, marginBottom: 6 }}>Critical &amp; High Priority Decisions</div>
                  <div className="stack-list compact">
                    {criticalDecisions.map(d => (
                      <Link key={d.id} to="/deci" className="list-item status-muted" style={{ textDecoration: 'none', color: 'inherit' }}>
                        <div className="item-head">
                          <strong>{d.title}</strong>
                          <div className="inline-badges">
                            <span className={`badge ${d.priority === 'critical' ? 'severity-high' : d.priority === 'high' ? 'severity-medium' : 'badge-muted'}`}>{d.priority}</span>
                            <span className={`badge ${d.status === 'in_progress' ? 'badge-good' : d.status === 'blocked' ? 'badge-bad' : 'badge-neutral'}`}>{d.status.replace('_', ' ')}</span>
                            {d.driver_name ? <span className="badge badge-muted">{d.driver_name}</span> : null}
                          </div>
                        </div>
                      </Link>
                    ))}
                  </div>
                </>
              ) : null}

              {/* Ownership load */}
              {(deci.ownership_map?.length ?? 0) > 0 ? (
                <>
                  <div style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 600, marginTop: 12, marginBottom: 6 }}>Leadership Load</div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 8 }}>
                    {(deci.ownership_map || []).map((o: Record<string, unknown>, idx: number) => {
                      // Backend returns flat: { member_id, name, driver_count, ... }
                      const memberName = (o.member as Record<string, unknown>)?.name as string || o.name as string || 'Unknown'
                      const memberId = (o.member as Record<string, unknown>)?.id ?? o.member_id ?? idx
                      const driverCount = (o.driver_count as number) ?? 0
                      const executorCount = (o.executor_count as number) ?? 0
                      const blockedCount = (o.blocked_count as number) ?? 0
                      return (
                        <div key={String(memberId)} style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 8, padding: '8px 10px', display: 'flex', alignItems: 'center', gap: 10 }}>
                          <div style={{
                            width: 32, height: 32, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                            background: blockedCount > 0 ? 'rgba(239,68,68,0.2)' : 'rgba(59,130,246,0.15)',
                            color: blockedCount > 0 ? '#f87171' : '#60a5fa', fontWeight: 700, fontSize: 13,
                          }}>
                            {memberName.charAt(0)}
                          </div>
                          <div>
                            <div style={{ fontWeight: 600, fontSize: 12, color: '#e2e8f0' }}>{memberName}</div>
                            <div style={{ fontSize: 10, color: 'var(--muted)' }}>
                              {driverCount}D &middot; {executorCount}E{blockedCount > 0 ? ` · ${blockedCount} blocked` : ''}
                            </div>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </>
              ) : null}
            </section>
          ) : null}

          {/* ═══════════════════════════════════════════════════════ */}
          {/* DIVISION STATUS GRID                                    */}
          {/* ═══════════════════════════════════════════════════════ */}
          <section className="card">
            <div className="venom-panel-head">
              <strong>Division &amp; System Status</strong>
              <span className="venom-panel-hint">Click to drill in</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 8 }}>
              {divisions.map((div) => (
                <Link
                  key={div.path}
                  to={div.path}
                  style={{
                    display: 'block', textDecoration: 'none', color: 'inherit',
                    background: 'rgba(255,255,255,0.03)', borderRadius: 10, padding: '14px 16px',
                    border: '1px solid rgba(255,255,255,0.06)', transition: 'all 0.15s',
                  }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(59,130,246,0.08)'; (e.currentTarget as HTMLElement).style.borderColor = 'rgba(59,130,246,0.3)' }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.03)'; (e.currentTarget as HTMLElement).style.borderColor = 'rgba(255,255,255,0.06)' }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                    <span style={{ fontWeight: 600, fontSize: 13 }}>{div.label}</span>
                    <span style={{ width: 8, height: 8, borderRadius: '50%', background: healthDot(div.health), flexShrink: 0 }} />
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--muted)' }}>{div.metric}</div>
                  <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.3)', marginTop: 4 }}>{div.owner}</div>
                </Link>
              ))}
            </div>
          </section>
        </>
      ) : null}
    </div>
  )
}
