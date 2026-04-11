import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { BarIndicator } from '../components/BarIndicator'
import { TruthBadge, TruthState } from '../components/TruthBadge'
import { VenomKpiStrip, KpiCardDef } from '../components/VenomKpiStrip'
import { TruthLegend } from '../components/TruthLegend'
import { fmtPct, fmtInt, formatFreshness } from '../lib/format'
import { ApiError, api } from '../lib/api'
import { frictionRankingScore } from '../lib/operatingModel'
import { IssueClusterItem, IssueRadarResponse, SocialMention, SocialTrendsResponse, SourceHealthItem, TelemetrySummary } from '../lib/types'
import { truthStateFromSource } from '../lib/divisionContract'

function severityBadgeClass(severity: string): string {
  if (severity === 'high') return 'badge badge-bad'
  if (severity === 'medium') return 'badge badge-warn'
  return 'badge badge-good'
}

function severityStatusClass(severity: string): string {
  if (severity === 'high') return 'status-bad'
  if (severity === 'medium') return 'status-warn'
  return 'status-good'
}

const DRILL_ROUTES: { path: string; label: string; icon: string }[] = [
  { path: '/root-cause', label: 'Root Cause', icon: '\ud83d\udd0d' },
  { path: '/friction', label: 'Friction Map', icon: '\ud83e\udea8' },
  { path: '/division/product-engineering', label: 'Product Engineering', icon: '\u2699\ufe0f' },
]

export function IssueRadar() {
  const [data, setData] = useState<IssueRadarResponse>({
    signals: [],
    clusters: [],
    highest_business_risk: [],
    highest_burden: [],
    fastest_rising: [],
    source_breakdown: [],
    trend_heatmap: [],
    live_sources: [],
    scaffolded_sources: [],
  })
  const [sourceHealth, setSourceHealth] = useState<SourceHealthItem[]>([])
  const [telemetry, setTelemetry] = useState<TelemetrySummary | null>(null)
  const [socialMentions, setSocialMentions] = useState<SocialMention[]>([])
  const [socialTrends, setSocialTrends] = useState<SocialTrendsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const [issueData, sourceHealthData, telemetryData, mentionsData, trendsData] = await Promise.all([
          api.issues(),
          api.sourceHealth(),
          api.telemetrySummary(),
          api.socialMentions({days: 7}).catch(() => [] as SocialMention[]),
          api.socialTrends(30).catch(() => null as SocialTrendsResponse | null),
        ])
        if (!cancelled) {
          setData(issueData)
          setSourceHealth(sourceHealthData)
          setTelemetry(telemetryData)
          setSocialMentions(mentionsData)
          setSocialTrends(trendsData)
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load issues')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [])

  /* ---------- derived data (preserved from original) ---------- */

  const sortedClusters = useMemo(() => {
    return [...data.clusters]
      .map((item) => {
        const source = String(item.details_json?.source || '').toLowerCase()
        const usesClarity = source === 'clarity'
        const corroborated = Number(item.source_count || 0) > 1 || source !== 'clarity'
        const rankingScore = frictionRankingScore({
          impact: Number(item.details_json?.priority_score || 0) * 12,
          confidence: Number(item.confidence || 0.6),
          sourceHealth,
          usesClarity,
          corroborated,
        })
        return { ...item, __rankingScore: rankingScore }
      })
      .sort((a, b) => Number(b.__rankingScore || 0) - Number(a.__rankingScore || 0))
  }, [data.clusters, sourceHealth])

  const topThree = sortedClusters.slice(0, 3)

  const telemetryLatest = telemetry?.latest || null
  const telemetryCollection = telemetry?.collection_metadata || null
  const telemetrySlice = telemetry?.slice_snapshot || null
  const telemetrySampleSize = Math.max(
    telemetryCollection?.distinct_devices_observed || 0,
    telemetryCollection?.active_devices_last_15m || 0,
    telemetrySlice?.sessions_derived || 0,
  )
  const telemetrySampleReliability =
    telemetrySampleSize <= 1 || telemetryCollection?.scan_truncated || telemetryCollection?.max_record_cap_hit
      ? 'low'
      : telemetrySampleSize < 10
        ? 'medium'
        : 'high'

  const topIssueTruthState: TruthState = truthStateFromSource(sourceHealth, ['freshdesk', 'clarity', 'ga4'], 'proxy') as TruthState
  const totalSources = data.live_sources.length + data.scaffolded_sources.length
  const coverageTruth: TruthState = data.live_sources.length >= totalSources && totalSources > 0 ? 'canonical' : data.live_sources.length > 0 ? 'proxy' : 'unavailable'

  const hasTelemetry = Boolean(telemetryLatest)

  const maxPriorityScore = Math.max(
    ...data.highest_business_risk.slice(0, 3).map((c: IssueClusterItem) => Number(c.details_json?.priority_score || 0)),
    1,
  )

  /* ---------- KPI strip cards ---------- */

  const kpiCards: KpiCardDef[] = [
    {
      label: 'Priority Queue',
      value: fmtInt(sortedClusters.length),
      sub: 'sorted clusters for escalation',
      truthState: topIssueTruthState,
    },
    {
      label: 'Fastest Rising',
      value: fmtInt(data.fastest_rising.length),
      sub: 'clusters with upward pressure',
      truthState: topIssueTruthState,
      delta: data.fastest_rising.length > 0
        ? { text: `${data.fastest_rising[0]?.details_json?.trend_label || 'rising'}`, direction: 'up' }
        : undefined,
    },
    {
      label: 'Live Sources',
      value: `${data.live_sources.length} / ${totalSources}`,
      sub: 'source coverage',
      truthState: coverageTruth,
    },
  ]

  /* ---------- render ---------- */

  return (
    <div className="page-grid venom-page">
      {/* Header */}
      <div className="venom-header">
        <div>
          <h2 className="venom-title">Issue Radar</h2>
          <p className="venom-subtitle">
            {data.clusters.length} clusters from {data.live_sources.length} live sources
          </p>
        </div>
      </div>

      {loading ? <Card title="Issue Radar"><div className="state-message">Loading live issue data...</div></Card> : null}
      {error ? <Card title="Issue Radar Error"><div className="state-message error">{error}</div></Card> : null}

      {!loading && !error ? (
        <>
          <TruthLegend />

          {/* KPI Strip */}
          <VenomKpiStrip cards={kpiCards} cols={3} />

          {/* Escalation Queue */}
          <section className="card">
            <div className="venom-panel-head">
              <strong>Escalate First</strong>
              <span className="venom-panel-hint">Top 3 by business risk</span>
            </div>
            {topThree.length > 0 ? (
              <div className="stack-list">
                {topThree.map((cluster) => {
                  const score = Number(cluster.details_json?.priority_score || 0)
                  const burden = cluster.details_json?.tickets_per_100_orders ?? cluster.details_json?.tickets_per_100_orders_by_theme
                  const trendLabel = String(cluster.details_json?.trend_label || 'stable')
                  return (
                    <div className={`list-item ${severityStatusClass(cluster.severity)}`} key={cluster.id}>
                      <div className="item-head">
                        <strong>{cluster.title}</strong>
                        <span className={severityBadgeClass(cluster.severity)}>{cluster.severity}</span>
                      </div>
                      <p>{String(cluster.details_json?.priority_reason_summary || 'No priority reason')}</p>
                      <div className="inline-badges">
                        <span className="badge badge-neutral">score {score}</span>
                        <span className="badge badge-neutral">{burden ?? '--'} / 100 orders</span>
                        <span className={`badge ${trendLabel === 'rising' ? 'badge-bad' : trendLabel === 'falling' ? 'badge-good' : 'badge-neutral'}`}>{trendLabel}</span>
                      </div>
                      <BarIndicator value={score} max={maxPriorityScore} color={cluster.severity === 'high' ? 'var(--red)' : cluster.severity === 'medium' ? 'var(--orange)' : 'var(--green)'} />
                      <small>Owner: {cluster.owner_team || 'TBD'}</small>
                    </div>
                  )
                })}
              </div>
            ) : (
              <div className="state-message">No clusters returned for escalation.</div>
            )}
          </section>

          {/* Two-col: Fastest Rising + Highest Burden */}
          <div className="two-col two-col-equal">
            <section className="card">
              <div className="venom-panel-head">
                <strong>Fastest Rising</strong>
              </div>
              <div className="stack-list compact">
                {data.fastest_rising.slice(0, 3).map((cluster) => (
                  <div className={`list-item ${severityStatusClass(cluster.severity)}`} key={cluster.id}>
                    <div className="item-head">
                      <strong>{cluster.title}</strong>
                      <div className="inline-badges">
                        <span className={severityBadgeClass(cluster.severity)}>{cluster.severity}</span>
                        <span className="badge badge-neutral">{fmtPct(Number(cluster.details_json?.trend_pct || 0) / 100, 0)}</span>
                        <span className="badge badge-bad">{String(cluster.details_json?.trend_label || 'rising')}</span>
                      </div>
                    </div>
                  </div>
                ))}
                {!data.fastest_rising.length ? <div className="state-message">No rising clusters.</div> : null}
              </div>
            </section>

            <section className="card">
              <div className="venom-panel-head">
                <strong>Highest Burden</strong>
              </div>
              <div className="stack-list compact">
                {data.highest_burden.slice(0, 3).map((cluster) => {
                  const burden = cluster.details_json?.tickets_per_100_orders ?? cluster.details_json?.tickets_per_100_orders_by_theme
                  return (
                    <div className={`list-item ${severityStatusClass(cluster.severity)}`} key={cluster.id}>
                      <div className="item-head">
                        <strong>{cluster.title}</strong>
                        <div className="inline-badges">
                          <span className={severityBadgeClass(cluster.severity)}>{cluster.severity}</span>
                          <span className="badge badge-neutral">{burden ?? '--'} / 100 orders</span>
                        </div>
                      </div>
                    </div>
                  )
                })}
                {!data.highest_burden.length ? <div className="state-message">No burden clusters.</div> : null}
              </div>
            </section>
          </div>

          {/* Telemetry Correlation (conditional) */}
          {hasTelemetry ? (
            <section className="card">
              <div className="venom-panel-head">
                <strong>Telemetry Correlation</strong>
                <TruthBadge state={telemetrySampleReliability === 'high' ? 'proxy' : 'estimated'} />
              </div>
              <div className="venom-breakdown-list">
                <div className="venom-breakdown-row">
                  <span>Reliability</span>
                  <span className="venom-breakdown-val">{fmtPct(telemetryLatest!.session_reliability_score)}</span>
                </div>
                <div className="venom-breakdown-row">
                  <span>Disconnect rate</span>
                  <span className="venom-breakdown-val">{fmtPct(telemetryLatest!.disconnect_rate)}</span>
                </div>
                <div className="venom-breakdown-row">
                  <span>Sample size</span>
                  <span className="venom-breakdown-val">{fmtInt(telemetrySampleSize)} ({telemetrySampleReliability})</span>
                </div>
                <div className="venom-breakdown-row">
                  <span>Freshness</span>
                  <span className="venom-breakdown-val">{formatFreshness(telemetryCollection?.newest_sample_timestamp_seen)}</span>
                </div>
              </div>
            </section>
          ) : null}

          {/* Two-col: Signals + Source Coverage */}
          <div className="two-col two-col-equal">
            <section className="card">
              <div className="venom-panel-head">
                <strong>Signals</strong>
                <span className="venom-panel-hint">{Math.min(data.signals.length, 10)} of {data.signals.length}</span>
              </div>
              <div className="stack-list compact">
                {data.signals.slice(0, 10).map((signal) => (
                  <div className={`list-item ${severityStatusClass(signal.severity)}`} key={signal.id}>
                    <div className="item-head">
                      <strong>{signal.title}</strong>
                      <div className="inline-badges">
                        <span className={severityBadgeClass(signal.severity)}>{signal.severity}</span>
                        <span className="badge badge-neutral">{signal.source}</span>
                      </div>
                    </div>
                  </div>
                ))}
                {!data.signals.length ? <div className="state-message">No issue signals returned.</div> : null}
              </div>
            </section>

            <section className="card">
              <div className="venom-panel-head">
                <strong>Source Coverage</strong>
              </div>
              <div className="venom-breakdown-list">
                {data.source_breakdown.map((entry) => (
                  <div className="venom-breakdown-row" key={entry.source}>
                    <span>{entry.source}</span>
                    <span className={`badge ${entry.live ? 'badge-good' : 'badge-muted'}`}>{entry.live ? 'live' : 'scaffolded'}</span>
                    <span className="venom-breakdown-val">{entry.signals}s / {entry.clusters}c</span>
                  </div>
                ))}
                {!data.source_breakdown.length ? <div className="state-message">No source breakdown.</div> : null}
              </div>
            </section>
          </div>

          {/* Social Early Warning */}
          {(() => {
            const clusterKeywords = data.clusters.flatMap((c) => c.title.toLowerCase().split(/\s+/))
            const negativeMentions = socialMentions.filter((m) =>
              (m.sentiment === 'negative' || m.classification === 'complaint') &&
              m.title && clusterKeywords.some((kw) => kw.length > 3 && (m.title?.toLowerCase().includes(kw) || m.body?.toLowerCase().includes(kw)))
            ).slice(0, 5)
            return negativeMentions.length > 0 ? (
              <section className="card">
                <div className="venom-panel-head">
                  <strong>Social Early Warning</strong>
                  <span className="venom-panel-hint">Negative mentions matching issue clusters</span>
                </div>
                <div className="stack-list compact">
                  {negativeMentions.map((mention) => (
                    <div className="list-item status-warn" key={mention.id}>
                      <div className="item-head">
                        <strong>{mention.title || 'Untitled mention'}</strong>
                        <div className="inline-badges">
                          <span className="badge badge-neutral">{mention.platform}</span>
                          <span className={`badge ${mention.sentiment === 'negative' ? 'badge-bad' : 'badge-warn'}`}>{mention.sentiment}</span>
                        </div>
                      </div>
                      {mention.body ? <p>{mention.body.length > 150 ? `${mention.body.slice(0, 150)}...` : mention.body}</p> : null}
                    </div>
                  ))}
                </div>
              </section>
            ) : (
              <section className="card">
                <div className="venom-panel-head">
                  <strong>Social Early Warning</strong>
                  <span className="venom-panel-hint">Last 7 days</span>
                </div>
                <div className="state-message">No negative social mentions match current issue clusters.</div>
              </section>
            )
          })()}

          {/* Competitor Issue Comparison */}
          {socialTrends?.competitor_mentions && Object.keys(socialTrends.competitor_mentions).length > 0 ? (
            <section className="card">
              <div className="venom-panel-head">
                <strong>Competitor Issue Comparison</strong>
                <span className="venom-panel-hint">Are current issues unique to Spider Grills or industry-wide?</span>
              </div>
              <div className="venom-breakdown-list">
                {Object.entries(socialTrends.competitor_mentions).map(([name, count]) => (
                  <div className="venom-breakdown-row" key={name}>
                    <span>{name}</span>
                    <span className="venom-breakdown-val">{fmtInt(count as number)} mentions</span>
                  </div>
                ))}
              </div>
            </section>
          ) : (
            <section className="card">
              <div className="venom-panel-head">
                <strong>Competitor Issue Comparison</strong>
                <span className="venom-panel-hint">30-day window</span>
              </div>
              <div className="state-message">Competitor mention data will populate after social sync.</div>
            </section>
          )}

          {/* Navigation tiles */}
          <section className="card">
            <div className="venom-panel-head">
              <strong>Drill-downs</strong>
              <span className="venom-panel-hint">Click to explore</span>
            </div>
            <div className="venom-drill-grid">
              {DRILL_ROUTES.map((route) => (
                <Link key={route.path} to={route.path} className="venom-drill-tile">
                  <span className="venom-drill-icon">{route.icon}</span>
                  <div>
                    <strong>{route.label}</strong>
                    <small>{route.path}</small>
                  </div>
                </Link>
              ))}
            </div>
          </section>
        </>
      ) : null}
    </div>
  )
}
