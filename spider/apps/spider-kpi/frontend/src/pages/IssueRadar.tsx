import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { BarIndicator } from '../components/BarIndicator'
import { TruthBadge, TruthState } from '../components/TruthBadge'
import { TruthLegend } from '../components/TruthLegend'
import { CollapsibleSection } from '../components/CollapsibleSection'
import { DivisionPageHeader } from '../components/DivisionPageHeader'
import { usePageConfig } from '../lib/usePageConfig'
import { fmtPct, fmtInt, formatFreshness } from '../lib/format'
import { ApiError, api } from '../lib/api'
import { frictionRankingScore } from '../lib/operatingModel'
import { IssueClusterItem, IssueRadarResponse, SocialMention, SocialTrendsResponse, SourceHealthItem, TelemetrySummary } from '../lib/types'
import { truthStateFromSource } from '../lib/divisionContract'
import { FeedbackPills, useMyFeedback } from '../components/FeedbackPills'
import { DivisionHero } from '../components/DivisionHero'

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
  const cfg = usePageConfig('issue_radar')
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
  const { reactions: signalReactions, updateReaction: updateSignalReaction } = useMyFeedback('issue_signal')

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

  /* KPI strip removed — DivisionHero already shows priority queue / rising
     / live sources with the same numbers and richer state colors. */

  /* ---------- render ---------- */

  return (
    <div className="page-grid venom-page">
      {/* ── DIVISION HERO — signature: radar ────────────────────────
          Polar radar with a sweeping line; top issue clusters plot
          as dots proportional to severity. Only Issue Radar uses
          this shape. */}
      {(() => {
        const topClusters = sortedClusters.slice(0, 8)
        const clusterCount = sortedClusters.length
        const risingCount = data.fastest_rising.length
        const liveCount = data.live_sources.length
        const totalSourcesCount = data.live_sources.length + data.scaffolded_sources.length
        const topName = topClusters[0]?.title || topClusters[0]?.details_json?.name as string || '—'
        const heroState: 'good' | 'warn' | 'bad' | 'neutral' =
          clusterCount === 0 ? 'good'
          : clusterCount > 8 ? 'bad'
          : clusterCount > 4 ? 'warn'
          : 'neutral'
        return (
          <DivisionHero
            accentColor="#ff6d7a"
            accentColorSoft="#f59e0b"
            signature="radar"
            title="Issue Radar"
            subtitle={`${clusterCount} clusters from ${liveCount} live sources — priority-ranked by business risk and burden.`}
            rightMeta={
              <div style={{ display: 'flex', gap: 6 }}>
                {DRILL_ROUTES.map(r => (
                  <Link key={r.path} to={r.path} className="range-button" style={{ textDecoration: 'none', fontSize: 11 }}>
                    {r.icon} {r.label}
                  </Link>
                ))}
              </div>
            }
            primary={{
              label: 'Active issue clusters',
              value: String(clusterCount),
              sublabel: `top: ${topName.slice(0, 32)}`,
              state: heroState,
              layers: topClusters.map((c, i) => ({
                label: (c.title || `cluster ${i}`).slice(0, 16),
                value: String((c.details_json?.impact_score as number) ?? i * 12 + 30),
              })),
            }}
            flanking={[
              {
                label: 'Rising',
                value: String(risingCount),
                sublabel: 'upward pressure',
                state: risingCount === 0 ? 'good' : risingCount <= 2 ? 'warn' : 'bad',
              },
              {
                label: 'Top business risk',
                value: fmtInt(data.highest_business_risk.length),
                sublabel: 'risk-ranked',
                state: data.highest_business_risk.length === 0 ? 'good' : 'warn',
              },
            ]}
            tiles={[
              {
                label: 'Live sources',
                value: `${liveCount}/${totalSourcesCount}`,
                state: liveCount >= totalSourcesCount * 0.7 ? 'good' : 'warn',
              },
              { label: 'Signals', value: fmtInt(data.signals.length), state: 'neutral' },
              { label: 'Top burden', value: fmtInt(data.highest_burden.length), state: 'neutral' },
              { label: 'Scaffolded', value: fmtInt(data.scaffolded_sources.length), state: 'neutral' },
            ]}
          />
        )
      })()}

      {loading ? <Card title="Issue Radar"><div className="state-message">Loading live issue data...</div></Card> : null}
      {error ? <Card title="Issue Radar Error"><div className="state-message error">{error}</div></Card> : null}

      {!loading && !error ? (
        <>
          <DivisionPageHeader cfg={cfg} divisionLabel="Issue Radar · Joseph" />

          {/* TruthLegend folded — viewers click in when they need the
              canonical/proxy/estimated key. */}
          <CollapsibleSection
            id="ir-truth-legend"
            title="Truth-state legend"
            subtitle="What the canonical / proxy / estimated badges mean"
            density="compact"
          >
            <TruthLegend />
          </CollapsibleSection>

          {/* Warning-lights TileGrid removed — DivisionHero's flanking +
              tiles already show priority queue / rising / live sources /
              top severity. No need to repeat. */}

          {/* Escalate First — top 3 visualized as severity bars with score
              scaled against max; click through to each cluster source. */}
          <section className="card">
            <div className="venom-panel-head">
              <strong>Escalate first</strong>
              <span className="venom-panel-hint">top 3 by business risk</span>
            </div>
            {topThree.length > 0 ? (
              <div style={{ display: 'grid', gap: 10 }}>
                {topThree.map((cluster, idx) => {
                  const score = Number(cluster.details_json?.priority_score || 0)
                  const burden = cluster.details_json?.tickets_per_100_orders ?? cluster.details_json?.tickets_per_100_orders_by_theme
                  const trendLabel = String(cluster.details_json?.trend_label || 'stable')
                  const severityColor =
                    cluster.severity === 'high' ? '#ef4444'
                    : cluster.severity === 'medium' ? '#f59e0b'
                    : '#22c55e'
                  const pct = Math.min(score / maxPriorityScore * 100, 100)
                  const trendColor = trendLabel === 'rising' ? '#ef4444' : trendLabel === 'falling' ? '#22c55e' : '#9ca3af'
                  return (
                    <div
                      key={cluster.id}
                      style={{
                        padding: '12px 14px',
                        background: cluster.severity === 'high' ? 'rgba(239, 68, 68, 0.08)'
                          : cluster.severity === 'medium' ? 'rgba(245, 158, 11, 0.08)'
                          : 'rgba(34, 197, 94, 0.06)',
                        borderLeft: `3px solid ${severityColor}`,
                        borderRadius: 8,
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12 }}>
                        <div style={{ fontWeight: 600, fontSize: 14, flex: 1 }}>
                          <span style={{ color: severityColor, marginRight: 8, fontWeight: 700 }}>#{idx + 1}</span>
                          {cluster.title}
                        </div>
                        <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexShrink: 0, fontSize: 11 }}>
                          <span style={{ color: 'var(--muted)' }}>score</span>
                          <span style={{ color: severityColor, fontWeight: 700, fontSize: 16 }}>{score}</span>
                        </div>
                      </div>
                      {/* Score bar scaled against max priority */}
                      <div style={{ position: 'relative', height: 6, background: 'rgba(255,255,255,0.05)', borderRadius: 3, marginTop: 10 }}>
                        <div style={{ position: 'absolute', top: 0, bottom: 0, left: 0, width: `${pct}%`, background: severityColor, borderRadius: 3 }} />
                      </div>
                      <div style={{ display: 'flex', gap: 16, fontSize: 11, color: 'var(--muted)', marginTop: 8, flexWrap: 'wrap' }}>
                        <span>🎯 owner: {cluster.owner_team || 'TBD'}</span>
                        <span>📊 {burden ?? '—'} / 100 orders</span>
                        <span style={{ color: trendColor, fontWeight: 600 }}>
                          {trendLabel === 'rising' ? '▲' : trendLabel === 'falling' ? '▼' : '▬'} {trendLabel}
                        </span>
                      </div>
                      {String(cluster.details_json?.priority_reason_summary || '') && (
                        <p style={{ fontSize: 12, margin: '8px 0 0', color: 'var(--text)', lineHeight: 1.45 }}>
                          {String(cluster.details_json?.priority_reason_summary)}
                        </p>
                      )}
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

          {/* Telemetry correlation — folded; viewers drill in for fleet detail. */}
          {hasTelemetry ? (
            <CollapsibleSection
              id="ir-telemetry-correlation"
              title="Telemetry correlation"
              subtitle="Session reliability · disconnect rate · sample size · freshness"
              density="compact"
              meta={`${fmtPct(telemetryLatest!.session_reliability_score)} reliability`}
            >
              <div className="venom-panel-head" style={{ marginTop: 0 }}>
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
            </CollapsibleSection>
          ) : null}

          {/* Signals + source coverage — both lists folded by default.
              The hero already shows live-source count and signal count. */}
          <CollapsibleSection
            id="ir-signals"
            title="All signals"
            subtitle="Per-signal severity + source"
            density="compact"
            meta={`${Math.min(data.signals.length, 10)} of ${data.signals.length}`}
          >
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
                  <div style={{ marginTop: 6 }}>
                    <FeedbackPills
                      artifactType="issue_signal"
                      artifactId={String(signal.id)}
                      currentReaction={signalReactions.get(String(signal.id)) ?? null}
                      compact
                      onChange={r => updateSignalReaction(String(signal.id), r)}
                    />
                  </div>
                </div>
              ))}
              {!data.signals.length ? <div className="state-message">No issue signals returned.</div> : null}
            </div>
          </CollapsibleSection>

          <CollapsibleSection
            id="ir-source-coverage"
            title="Source coverage"
            subtitle="Per-source live/scaffolded state and signal/cluster volume"
            density="compact"
            meta={`${data.live_sources.length}/${totalSources} live`}
          >
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
          </CollapsibleSection>

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

          {/* Competitor comparison — folded; useful context but not first-glance. */}
          <CollapsibleSection
            id="ir-competitor-comparison"
            title="Competitor issue comparison"
            subtitle="Are current issues unique to Spider Grills or industry-wide?"
            density="compact"
          >
            {socialTrends?.competitor_mentions && Object.keys(socialTrends.competitor_mentions).length > 0 ? (
              <div className="venom-breakdown-list">
                {Object.entries(socialTrends.competitor_mentions).map(([name, count]) => (
                  <div className="venom-breakdown-row" key={name}>
                    <span>{name}</span>
                    <span className="venom-breakdown-val">{fmtInt(count as number)} mentions</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="state-message">Competitor mention data will populate after social sync.</div>
            )}
          </CollapsibleSection>

          {/* Bottom drill-down nav removed — DivisionHero rightMeta already
              renders the same drill routes as buttons. */}
        </>
      ) : null}
    </div>
  )
}
