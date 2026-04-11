import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { VenomKpiStrip, KpiCardDef } from '../components/VenomKpiStrip'
import { TruthBadge } from '../components/TruthBadge'
import { TruthLegend } from '../components/TruthLegend'
import { ApiError, api } from '../lib/api'
import { fmtInt, fmtPct, fmtDecimal } from '../lib/format'
import { SocialMention, SocialPulse, SocialTrendsResponse } from '../lib/types'
import { BarChart, Bar, ResponsiveContainer, CartesianGrid, XAxis, YAxis, Tooltip } from 'recharts'

type MentionFilter = 'all' | 'positive' | 'negative' | 'questions' | 'complaints'

function sentimentStatus(s: string) {
  if (s === 'positive') return 'good'
  if (s === 'negative') return 'bad'
  return 'warn'
}

export function SocialIntelligence() {
  const [pulse, setPulse] = useState<SocialPulse | null>(null)
  const [trends, setTrends] = useState<SocialTrendsResponse | null>(null)
  const [mentions, setMentions] = useState<SocialMention[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<MentionFilter>('all')

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const [p, t, m] = await Promise.all([
          api.socialPulse(7).catch(() => null),
          api.socialTrends(30).catch(() => null),
          api.socialMentions({ days: 7 }).catch(() => []),
        ])
        if (cancelled) return
        setPulse(p)
        setTrends(t)
        setMentions(m)
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load social data')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => { cancelled = true }
  }, [])

  const brandMentionCount = pulse?.brand_mentions ?? 0
  const totalMentions = pulse?.total_mentions ?? 0
  const avgSentiment = pulse?.avg_sentiment_score ?? 0
  const competitorTotal = trends ? Object.values(trends.competitor_mentions).reduce((s, n) => s + n, 0) : 0
  const competitorShare = (brandMentionCount + competitorTotal) > 0 ? competitorTotal / (brandMentionCount + competitorTotal) : 0
  const trendingCount = trends?.trending_topics?.length ?? 0

  const kpiCards = useMemo<KpiCardDef[]>(() => [
    { label: 'Brand Mentions', value: fmtInt(brandMentionCount), sub: '7-day count', truthState: 'proxy' },
    {
      label: 'Avg Sentiment',
      value: avgSentiment > 0 ? `+${fmtDecimal(avgSentiment)}` : avgSentiment < 0 ? fmtDecimal(avgSentiment) : 'Neutral',
      sub: '-1.0 (negative) to +1.0 (positive)',
      truthState: 'estimated',
      delta: avgSentiment > 0.2 ? { text: 'Positive', direction: 'up' as const } : avgSentiment < -0.2 ? { text: 'Negative', direction: 'down' as const } : { text: 'Neutral', direction: 'flat' as const },
    },
    { label: 'Competitor Share', value: fmtPct(competitorShare), sub: `${fmtInt(competitorTotal)} competitor vs ${fmtInt(brandMentionCount)} brand`, truthState: 'estimated' },
    { label: 'Trending Topics', value: fmtInt(trendingCount), sub: '30-day topics detected', truthState: 'proxy' },
  ], [brandMentionCount, avgSentiment, competitorShare, competitorTotal, trendingCount])

  const sentimentBreakdown = pulse?.sentiment_breakdown || {}
  const sentimentTotal = Object.values(sentimentBreakdown).reduce((s, n) => s + n, 0) || 1
  const posPct = ((sentimentBreakdown['positive'] || 0) / sentimentTotal) * 100
  const neuPct = ((sentimentBreakdown['neutral'] || 0) / sentimentTotal) * 100
  const negPct = ((sentimentBreakdown['negative'] || 0) / sentimentTotal) * 100
  const mixPct = ((sentimentBreakdown['mixed'] || 0) / sentimentTotal) * 100

  const productData = useMemo(() => {
    if (!trends?.product_mentions) return []
    return Object.entries(trends.product_mentions)
      .sort(([, a], [, b]) => b - a)
      .map(([name, count]) => ({ name, count }))
  }, [trends])

  const competitorData = useMemo(() => {
    if (!trends?.competitor_mentions) return []
    return Object.entries(trends.competitor_mentions)
      .sort(([, a], [, b]) => b - a)
      .slice(0, 8)
      .map(([name, count]) => ({ name, count }))
  }, [trends])

  const filteredMentions = useMemo(() => {
    let filtered = mentions.filter((m) => m.brand_mentioned || m.relevance_score > 0.3)
    switch (filter) {
      case 'positive': filtered = filtered.filter((m) => m.sentiment === 'positive'); break
      case 'negative': filtered = filtered.filter((m) => m.sentiment === 'negative'); break
      case 'questions': filtered = filtered.filter((m) => m.classification === 'customer_question'); break
      case 'complaints': filtered = filtered.filter((m) => m.classification === 'complaint'); break
    }
    return filtered.slice(0, 20)
  }, [mentions, filter])

  const brandHealthScore = useMemo(() => {
    if (!pulse || totalMentions === 0) return null
    const sentimentComponent = (avgSentiment + 1) / 2 * 50
    const volumeComponent = Math.min(brandMentionCount / 10, 1) * 30
    const engagementComponent = Math.min((pulse.top_mentions?.[0]?.engagement_score || 0) / 100, 1) * 20
    return Math.round(sentimentComponent + volumeComponent + engagementComponent)
  }, [pulse, totalMentions, avgSentiment, brandMentionCount])

  const hasData = totalMentions > 0 || trendingCount > 0 || mentions.length > 0

  return (
    <div className="page-grid venom-page">
      <div className="venom-header">
        <div>
          <h2 className="venom-title">Social Intelligence</h2>
          <p className="venom-subtitle">
            {hasData ? `${fmtInt(totalMentions)} mentions tracked across Reddit, YouTube, and Google Reviews` : 'Monitoring Reddit, YouTube, and Google Reviews for brand, competitor, and industry signals'}
          </p>
        </div>
      </div>

      {loading ? <Card title="Loading"><div className="state-message">Loading social intelligence…</div></Card> : null}
      {error ? <Card title="Error"><div className="state-message error">{error}</div></Card> : null}

      {!loading && !error ? (
        <>
          <TruthLegend />
          <VenomKpiStrip cards={kpiCards} />

          {/* Brand Health Score */}
          <section className="card">
            <div className="venom-panel-head">
              <strong>Brand Health Score</strong>
              <TruthBadge state="estimated" />
            </div>
            {brandHealthScore != null ? (
              <>
                <div className="hero-metric">{brandHealthScore}<small style={{ fontSize: 16, color: 'var(--muted)', marginLeft: 6 }}>/ 100</small></div>
                <div className="venom-sentiment-bar">
                  <div style={{ width: `${posPct}%`, background: 'var(--green)' }} title={`Positive: ${sentimentBreakdown['positive'] || 0}`} />
                  <div style={{ width: `${neuPct + mixPct}%`, background: 'var(--orange)' }} title={`Neutral/Mixed: ${(sentimentBreakdown['neutral'] || 0) + (sentimentBreakdown['mixed'] || 0)}`} />
                  <div style={{ width: `${negPct}%`, background: 'var(--red)' }} title={`Negative: ${sentimentBreakdown['negative'] || 0}`} />
                </div>
                <div className="venom-sentiment-labels">
                  <span>Positive: {sentimentBreakdown['positive'] || 0}</span>
                  <span>Neutral: {sentimentBreakdown['neutral'] || 0}</span>
                  <span>Mixed: {sentimentBreakdown['mixed'] || 0}</span>
                  <span>Negative: {sentimentBreakdown['negative'] || 0}</span>
                </div>
              </>
            ) : (
              <div className="state-message">Brand health score will populate after first social sync.</div>
            )}
          </section>

          {/* Product Mentions + Competitor Radar */}
          <div className="two-col two-col-equal">
            <section className="card">
              <div className="venom-panel-head">
                <strong>Product Mentions</strong>
                <span className="venom-panel-hint">30 days</span>
              </div>
              {productData.length > 0 ? (
                <div className="chart-wrap-short">
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={productData}>
                      <CartesianGrid stroke="rgba(255,255,255,0.06)" />
                      <XAxis dataKey="name" stroke="#9fb0d4" tick={{ fontSize: 11 }} />
                      <YAxis stroke="#9fb0d4" />
                      <Tooltip />
                      <Bar dataKey="count" name="Mentions" fill="var(--green)" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : <div className="state-message">Product mention data will populate after first sync.</div>}
            </section>

            <section className="card">
              <div className="venom-panel-head">
                <strong>Competitor Radar</strong>
                <span className="venom-panel-hint">Share of voice</span>
              </div>
              {competitorData.length > 0 ? (
                <div className="chart-wrap-short">
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={competitorData} layout="vertical">
                      <CartesianGrid stroke="rgba(255,255,255,0.06)" />
                      <XAxis type="number" stroke="#9fb0d4" />
                      <YAxis type="category" dataKey="name" stroke="#9fb0d4" tick={{ fontSize: 11 }} width={100} />
                      <Tooltip />
                      <Bar dataKey="count" name="Mentions" fill="var(--orange)" radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : <div className="state-message">Competitor data will populate after first sync.</div>}
            </section>
          </div>

          {/* Brand Mentions Feed */}
          <section className="card">
            <div className="venom-panel-head">
              <strong>Brand Mentions Feed</strong>
              <span className="venom-panel-hint">Last 7 days</span>
            </div>
            <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
              {(['all', 'positive', 'negative', 'questions', 'complaints'] as MentionFilter[]).map((tab) => (
                <button key={tab} className={`range-button${filter === tab ? ' active' : ''}`} onClick={() => setFilter(tab)}>{tab}</button>
              ))}
            </div>
            {filteredMentions.length > 0 ? (
              <div className="stack-list compact">
                {filteredMentions.map((m) => (
                  <div key={m.external_id} className={`list-item status-${sentimentStatus(m.sentiment)}`}>
                    <div className="item-head">
                      <strong>{m.title || 'Untitled post'}</strong>
                      <div className="inline-badges">
                        <span className="badge badge-neutral">{m.platform}</span>
                        {m.subreddit ? <span className="badge badge-muted">r/{m.subreddit}</span> : null}
                        <span className={`badge ${m.sentiment === 'positive' ? 'badge-good' : m.sentiment === 'negative' ? 'badge-bad' : 'badge-warn'}`}>{m.sentiment}</span>
                      </div>
                    </div>
                    {m.body ? <p className="venom-mention-body">{m.body.slice(0, 200)}{m.body.length > 200 ? '...' : ''}</p> : null}
                    <div className="venom-mention-meta">
                      {m.engagement_score > 0 ? <span className="badge badge-neutral">{m.engagement_score} upvotes</span> : null}
                      {m.comment_count > 0 ? <span className="badge badge-neutral">{m.comment_count} comments</span> : null}
                      {m.product_mentioned ? <span className="badge badge-good">{m.product_mentioned}</span> : null}
                      {m.competitor_mentioned ? <span className="badge badge-warn">{m.competitor_mentioned}</span> : null}
                      {m.source_url ? <a href={m.source_url} target="_blank" rel="noopener noreferrer" className="badge badge-neutral">View source</a> : null}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="state-message">{hasData ? 'No mentions match this filter.' : 'Social listening will populate after first Reddit sync. Set up Reddit OAuth credentials to start.'}</div>
            )}
          </section>

          {/* Industry Trends */}
          <section className="card">
            <div className="venom-panel-head">
              <strong>Industry Trends — Charcoal Grilling</strong>
              <span className="venom-panel-hint">30-day trending topics from r/smoking, r/grilling, r/BBQ</span>
            </div>
            {(trends?.trending_topics?.length || 0) > 0 ? (
              <div className="stack-list compact">
                {trends!.trending_topics.slice(0, 8).map((t) => (
                  <div key={t.topic} className="list-item status-muted">
                    <div className="item-head">
                      <strong>{t.topic}</strong>
                      <div className="inline-badges">
                        <span className="badge badge-neutral">{fmtInt(t.mention_count)} mentions</span>
                        <span className="badge badge-muted">{fmtInt(t.total_engagement)} engagement</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="state-message">Industry trends will populate after first Reddit sync.</div>
            )}
          </section>

          {/* Navigation */}
          <section className="card">
            <div className="venom-panel-head"><strong>Related Pages</strong></div>
            <div className="venom-drill-grid">
              <Link to="/division/customer-experience" className="venom-drill-tile"><div><strong>Customer Experience</strong><small>Support queue + brand pulse</small></div></Link>
              <Link to="/division/marketing" className="venom-drill-tile"><div><strong>Marketing</strong><small>Industry trends + campaigns</small></div></Link>
              <Link to="/issues" className="venom-drill-tile"><div><strong>Issue Radar</strong><small>Social early warning + escalation</small></div></Link>
              <Link to="/division/product-engineering" className="venom-drill-tile"><div><strong>Product Engineering</strong><small>Fleet telemetry + device health</small></div></Link>
            </div>
          </section>
        </>
      ) : null}
    </div>
  )
}
