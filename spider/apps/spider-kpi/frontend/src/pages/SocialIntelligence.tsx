import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { VenomKpiStrip, KpiCardDef } from '../components/VenomKpiStrip'
import { TruthBadge } from '../components/TruthBadge'
import { TruthLegend } from '../components/TruthLegend'
import { ApiError, api } from '../lib/api'
import { fmtInt, fmtPct, fmtDecimal } from '../lib/format'
import { SocialMention, SocialPulse, SocialTrendsResponse, YouTubePerformance, AmazonProductHealth, MarketIntelligence } from '../lib/types'
import { BarChart, Bar, ResponsiveContainer, CartesianGrid, XAxis, YAxis, Tooltip } from 'recharts'

type MentionFilter = 'all' | 'positive' | 'negative' | 'questions' | 'complaints'

function sentimentStatus(s: string) {
  if (s === 'positive') return 'good'
  if (s === 'negative') return 'bad'
  return 'warn'
}

function sentimentBadgeClass(s: string) {
  if (s === 'positive') return 'badge-good'
  if (s === 'negative') return 'badge-bad'
  return 'badge-warn'
}

function formatViews(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

export function SocialIntelligence() {
  const [pulse, setPulse] = useState<SocialPulse | null>(null)
  const [trends, setTrends] = useState<SocialTrendsResponse | null>(null)
  const [mentions, setMentions] = useState<SocialMention[]>([])
  const [youtube, setYoutube] = useState<YouTubePerformance | null>(null)
  const [amazon, setAmazon] = useState<AmazonProductHealth | null>(null)
  const [market, setMarket] = useState<MarketIntelligence | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<MentionFilter>('all')

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const [p, t, m, yt, amz, mkt] = await Promise.all([
          api.socialPulse(7).catch(() => null),
          api.socialTrends(30).catch(() => null),
          api.socialMentions({ days: 7 }).catch(() => []),
          api.youtubePerformance(30).catch(() => null),
          api.amazonProducts().catch(() => null),
          api.marketIntelligence(30).catch(() => null),
        ])
        if (cancelled) return
        setPulse(p)
        setTrends(t)
        setMentions(m)
        setYoutube(yt)
        setAmazon(amz)
        setMarket(mkt)
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

  // Platform breakdown for subtitle
  const platformParts: string[] = []
  const byPlatform = pulse?.by_platform || {}
  if (byPlatform['reddit']) platformParts.push(`${byPlatform['reddit']} Reddit`)
  if (byPlatform['youtube']) platformParts.push(`${byPlatform['youtube']} YouTube`)
  if (byPlatform['amazon']) platformParts.push(`${byPlatform['amazon']} Amazon`)
  if (byPlatform['google_reviews']) platformParts.push(`${byPlatform['google_reviews']} Google`)
  const platformSummary = platformParts.length > 0 ? ` (${platformParts.join(', ')})` : ''

  return (
    <div className="page-grid venom-page">
      <div className="venom-header">
        <div>
          <h2 className="venom-title">Social Intelligence</h2>
          <p className="venom-subtitle">
            {hasData ? `${fmtInt(totalMentions)} mentions tracked across Reddit, YouTube, and Amazon${platformSummary}` : 'Monitoring Reddit, YouTube, and Amazon for brand, competitor, and industry signals'}
          </p>
        </div>
      </div>

      {loading ? <Card title="Loading"><div className="state-message">Loading social intelligence...</div></Card> : null}
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

          {/* YouTube Content Intelligence */}
          <section className="card">
            <div className="venom-panel-head">
              <strong>YouTube Content Intelligence</strong>
              <span className="venom-panel-hint">30 days</span>
            </div>
            {youtube && youtube.total_videos > 0 ? (
              <>
                <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', marginBottom: 16 }}>
                  <div className="mini-stat">
                    <span className="mini-stat-value">{fmtInt(youtube.total_videos)}</span>
                    <span className="mini-stat-label">Videos</span>
                  </div>
                  <div className="mini-stat">
                    <span className="mini-stat-value">{formatViews(youtube.total_views)}</span>
                    <span className="mini-stat-label">Total Views</span>
                  </div>
                  <div className="mini-stat">
                    <span className="mini-stat-value">{formatViews(youtube.total_likes)}</span>
                    <span className="mini-stat-label">Total Likes</span>
                  </div>
                  <div className="mini-stat">
                    <span className="mini-stat-value">{youtube.avg_engagement_rate}%</span>
                    <span className="mini-stat-label">Avg Engagement</span>
                  </div>
                  <div className="mini-stat">
                    <span className="mini-stat-value">{fmtInt(youtube.total_comments)}</span>
                    <span className="mini-stat-label">Comments</span>
                  </div>
                </div>
                <div className="stack-list compact">
                  {youtube.top_videos.slice(0, 8).map((v) => (
                    <div key={v.video_id} className={`list-item status-${sentimentStatus(v.sentiment)}`}>
                      <div className="item-head">
                        <strong>{v.title || 'Untitled video'}</strong>
                        <div className="inline-badges">
                          <span className="badge badge-neutral">{formatViews(v.views)} views</span>
                          <span className="badge badge-neutral">{fmtInt(v.likes)} likes</span>
                          {v.engagement_rate > 0 ? <span className="badge badge-muted">{v.engagement_rate}% eng</span> : null}
                          <span className={`badge ${sentimentBadgeClass(v.sentiment)}`}>{v.sentiment}</span>
                        </div>
                      </div>
                      <div className="venom-mention-meta">
                        <span className="badge badge-muted">{v.author}</span>
                        {v.comments > 0 ? <span className="badge badge-neutral">{fmtInt(v.comments)} comments</span> : null}
                        {v.product_mentioned ? <span className="badge badge-good">{v.product_mentioned}</span> : null}
                        {v.competitor_mentioned ? <span className="badge badge-warn">{v.competitor_mentioned}</span> : null}
                        <a href={v.source_url} target="_blank" rel="noopener noreferrer" className="badge badge-neutral">Watch</a>
                      </div>
                      {v.top_comments && v.top_comments.length > 0 ? (
                        <div style={{ marginTop: 8, paddingLeft: 12, borderLeft: '2px solid rgba(255,255,255,0.1)' }}>
                          {v.top_comments.slice(0, 2).map((c, i) => (
                            <div key={i} style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 4 }}>
                              <strong>{c.author}</strong>: {c.text.slice(0, 150)}{c.text.length > 150 ? '...' : ''}
                              {c.likes > 0 ? <span style={{ marginLeft: 6, opacity: 0.7 }}>({c.likes} likes)</span> : null}
                            </div>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>

                {/* Comment highlights */}
                {youtube.comment_highlights.length > 0 ? (
                  <div style={{ marginTop: 16 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--muted)', marginBottom: 8 }}>Top Comments Across All Videos</div>
                    {youtube.comment_highlights.slice(0, 4).map((c, i) => (
                      <div key={i} style={{ fontSize: 12, color: 'var(--text-secondary, #b0b8c9)', marginBottom: 6, paddingLeft: 8, borderLeft: '2px solid var(--orange)' }}>
                        <strong>{c.author}</strong>: {c.text.slice(0, 200)}{c.text.length > 200 ? '...' : ''}
                        {c.likes > 0 ? <span style={{ marginLeft: 6, opacity: 0.7 }}>({c.likes} likes)</span> : null}
                      </div>
                    ))}
                  </div>
                ) : null}
              </>
            ) : (
              <div className="state-message">YouTube data will populate after first YouTube sync. Requires YOUTUBE_API_KEY.</div>
            )}
          </section>

          {/* Amazon Marketplace Health */}
          <section className="card">
            <div className="venom-panel-head">
              <strong>Amazon Marketplace Health</strong>
              <TruthBadge state="proxy" />
            </div>
            {amazon && amazon.total_products > 0 ? (
              <>
                <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', marginBottom: 16 }}>
                  <div className="mini-stat">
                    <span className="mini-stat-value">{fmtInt(amazon.total_products)}</span>
                    <span className="mini-stat-label">Products Tracked</span>
                  </div>
                  {amazon.best_bsr != null ? (
                    <div className="mini-stat">
                      <span className="mini-stat-value">#{fmtInt(amazon.best_bsr)}</span>
                      <span className="mini-stat-label">Best BSR</span>
                    </div>
                  ) : null}
                  {amazon.avg_bsr != null ? (
                    <div className="mini-stat">
                      <span className="mini-stat-value">#{fmtInt(amazon.avg_bsr)}</span>
                      <span className="mini-stat-label">Avg BSR</span>
                    </div>
                  ) : null}
                  {amazon.avg_price != null ? (
                    <div className="mini-stat">
                      <span className="mini-stat-value">${amazon.avg_price.toFixed(2)}</span>
                      <span className="mini-stat-label">Avg Price</span>
                    </div>
                  ) : null}
                  {amazon.price_range ? (
                    <div className="mini-stat">
                      <span className="mini-stat-value">${amazon.price_range.min.toFixed(0)}-${amazon.price_range.max.toFixed(0)}</span>
                      <span className="mini-stat-label">Price Range</span>
                    </div>
                  ) : null}
                </div>
                <div className="stack-list compact">
                  {amazon.products.map((p) => (
                    <div key={p.asin} className="list-item status-muted">
                      <div className="item-head">
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          {p.image_url ? <img src={p.image_url} alt="" style={{ width: 40, height: 40, objectFit: 'contain', borderRadius: 4, background: 'rgba(255,255,255,0.05)' }} /> : null}
                          <strong>{p.title || p.asin}</strong>
                        </div>
                        <div className="inline-badges">
                          {p.bsr != null ? <span className="badge badge-neutral">BSR #{fmtInt(p.bsr)}</span> : null}
                          {p.competitive_price != null ? <span className="badge badge-good">${p.competitive_price.toFixed(2)}</span> : null}
                          <span className="badge badge-muted">{p.asin}</span>
                        </div>
                      </div>
                      <div className="venom-mention-meta">
                        {p.bsr_category ? <span className="badge badge-muted">{p.bsr_category}</span> : null}
                        {p.brand ? <span className="badge badge-neutral">{p.brand}</span> : null}
                        {p.listed_price != null && p.competitive_price != null && p.listed_price !== p.competitive_price ? (
                          <span className="badge badge-warn">List: ${p.listed_price.toFixed(2)}</span>
                        ) : null}
                        <a href={p.source_url} target="_blank" rel="noopener noreferrer" className="badge badge-neutral">View on Amazon</a>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div className="state-message">Amazon product data will populate after first Amazon sync. Requires SP-API credentials.</div>
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
                        <span className={`badge ${sentimentBadgeClass(m.sentiment)}`}>{m.sentiment}</span>
                      </div>
                    </div>
                    {m.body ? <p className="venom-mention-body">{m.body.slice(0, 200)}{m.body.length > 200 ? '...' : ''}</p> : null}
                    <div className="venom-mention-meta">
                      {m.platform === 'youtube' && m.engagement_score > 0 ? <span className="badge badge-neutral">{formatViews(m.engagement_score)} views</span> : null}
                      {m.platform !== 'youtube' && m.engagement_score > 0 ? <span className="badge badge-neutral">{m.engagement_score} upvotes</span> : null}
                      {m.comment_count > 0 ? <span className="badge badge-neutral">{m.comment_count} comments</span> : null}
                      {m.product_mentioned ? <span className="badge badge-good">{m.product_mentioned}</span> : null}
                      {m.competitor_mentioned ? <span className="badge badge-warn">{m.competitor_mentioned}</span> : null}
                      {m.source_url ? <a href={m.source_url} target="_blank" rel="noopener noreferrer" className="badge badge-neutral">View source</a> : null}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="state-message">{hasData ? 'No mentions match this filter.' : 'Social listening will populate after first sync. Configure Reddit, YouTube, or Amazon credentials to start.'}</div>
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

          {/* ── Market Intelligence ── */}
          {market && market.total_mentions > 0 ? (
            <>
              {/* Competitive Landscape */}
              <section className="card">
                <div className="venom-panel-head">
                  <strong>Competitive Landscape</strong>
                  <span className="venom-panel-hint">30-day share of voice across all platforms</span>
                </div>
                <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', marginBottom: 16 }}>
                  <div className="mini-stat">
                    <span className="mini-stat-value">{fmtPct(market.competitive_landscape.brand_share_of_voice)}</span>
                    <span className="mini-stat-label">Spider Grills SOV</span>
                  </div>
                  <div className="mini-stat">
                    <span className="mini-stat-value">{fmtInt(market.competitive_landscape.brand_mentions)}</span>
                    <span className="mini-stat-label">Brand Mentions</span>
                  </div>
                  <div className="mini-stat">
                    <span className="mini-stat-value">{fmtInt(market.competitive_landscape.competitors.length)}</span>
                    <span className="mini-stat-label">Competitors Tracked</span>
                  </div>
                </div>
                {market.competitive_landscape.competitors.length > 0 ? (
                  <div className="chart-wrap-short">
                    <ResponsiveContainer width="100%" height={Math.max(200, market.competitive_landscape.competitors.slice(0, 10).length * 30)}>
                      <BarChart data={market.competitive_landscape.competitors.slice(0, 10)} layout="vertical">
                        <CartesianGrid stroke="rgba(255,255,255,0.06)" />
                        <XAxis type="number" stroke="#9fb0d4" />
                        <YAxis type="category" dataKey="competitor" stroke="#9fb0d4" tick={{ fontSize: 11 }} width={110} />
                        <Tooltip formatter={(value: number) => [fmtInt(value), 'Mentions']} />
                        <Bar dataKey="mentions" name="Mentions" fill="var(--orange)" radius={[0, 4, 4, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                ) : null}
                {market.competitive_landscape.competitors.length > 0 ? (
                  <div style={{ marginTop: 12 }}>
                    <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
                      <thead>
                        <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)', color: 'var(--muted)' }}>
                          <th style={{ textAlign: 'left', padding: '6px 8px' }}>Competitor</th>
                          <th style={{ textAlign: 'right', padding: '6px 8px' }}>Mentions</th>
                          <th style={{ textAlign: 'right', padding: '6px 8px' }}>SOV</th>
                          <th style={{ textAlign: 'right', padding: '6px 8px' }}>Sentiment</th>
                          <th style={{ textAlign: 'right', padding: '6px 8px' }}>Engagement</th>
                        </tr>
                      </thead>
                      <tbody>
                        {market.competitive_landscape.competitors.slice(0, 10).map((c) => (
                          <tr key={c.competitor} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                            <td style={{ padding: '6px 8px', fontWeight: 500 }}>{c.competitor.replace(/_/g, ' ')}</td>
                            <td style={{ textAlign: 'right', padding: '6px 8px' }}>{fmtInt(c.mentions)}</td>
                            <td style={{ textAlign: 'right', padding: '6px 8px' }}>{fmtPct(c.share_of_voice)}</td>
                            <td style={{ textAlign: 'right', padding: '6px 8px' }}>
                              <span className={`badge ${sentimentBadgeClass(c.sentiment_label)}`} style={{ fontSize: 11 }}>
                                {c.avg_sentiment > 0 ? '+' : ''}{c.avg_sentiment.toFixed(2)}
                              </span>
                            </td>
                            <td style={{ textAlign: 'right', padding: '6px 8px' }}>{fmtInt(c.total_engagement)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}
              </section>

              {/* Amazon Market Position */}
              {market.amazon_positioning.price || market.amazon_positioning.bsr ? (
                <section className="card">
                  <div className="venom-panel-head">
                    <strong>Amazon Market Position</strong>
                    <TruthBadge state="proxy" />
                  </div>
                  <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', marginBottom: 12 }}>
                    {market.amazon_positioning.price ? (
                      <>
                        <div className="mini-stat">
                          <span className="mini-stat-value">${market.amazon_positioning.price.our_avg_price}</span>
                          <span className="mini-stat-label">Our Avg Price</span>
                        </div>
                        <div className="mini-stat">
                          <span className="mini-stat-value">${market.amazon_positioning.price.competitor_avg_price}</span>
                          <span className="mini-stat-label">Competitor Avg</span>
                        </div>
                        <div className="mini-stat">
                          <span className="mini-stat-value" style={{ color: market.amazon_positioning.price.position === 'premium' ? 'var(--orange)' : market.amazon_positioning.price.position === 'value' ? 'var(--green)' : 'var(--text)' }}>
                            {market.amazon_positioning.price.position}
                          </span>
                          <span className="mini-stat-label">Price Position</span>
                        </div>
                      </>
                    ) : null}
                    {market.amazon_positioning.bsr ? (
                      <>
                        <div className="mini-stat">
                          <span className="mini-stat-value">#{fmtInt(market.amazon_positioning.bsr.our_best_bsr)}</span>
                          <span className="mini-stat-label">Our Best BSR</span>
                        </div>
                        <div className="mini-stat">
                          <span className="mini-stat-value">#{fmtInt(market.amazon_positioning.bsr.competitor_best_bsr)}</span>
                          <span className="mini-stat-label">Competitor Best</span>
                        </div>
                        <div className="mini-stat">
                          <span className="mini-stat-value" style={{ color: market.amazon_positioning.bsr.outranking_competitors ? 'var(--green)' : 'var(--orange)' }}>
                            {market.amazon_positioning.bsr.outranking_competitors ? 'Outranking' : 'Behind'}
                          </span>
                          <span className="mini-stat-label">BSR Position</span>
                        </div>
                      </>
                    ) : null}
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--muted)' }}>
                    Tracking {market.amazon_positioning.our_products} Spider Grills products vs {market.amazon_positioning.competitor_products} competitor products on Amazon
                  </div>
                </section>
              ) : null}

              {/* Trend Momentum + Purchase Intent — 2-col */}
              <div className="two-col two-col-equal">
                {/* Trend Momentum */}
                <section className="card">
                  <div className="venom-panel-head">
                    <strong>Trend Momentum</strong>
                    <span className="venom-panel-hint">Cross-platform topic tracking</span>
                  </div>
                  {market.trend_momentum.length > 0 ? (
                    <div className="stack-list compact">
                      {market.trend_momentum.slice(0, 10).map((t) => (
                        <div key={t.topic} className="list-item status-muted">
                          <div className="item-head">
                            <strong>{t.topic}</strong>
                            <div className="inline-badges">
                              <span className={`badge ${t.momentum === 'strong' ? 'badge-good' : t.momentum === 'growing' ? 'badge-warn' : 'badge-muted'}`}>
                                {t.momentum}
                              </span>
                              <span className="badge badge-neutral">{fmtInt(t.mentions)} mentions</span>
                              {t.cross_platform ? <span className="badge badge-good">cross-platform</span> : null}
                            </div>
                          </div>
                          <div className="venom-mention-meta">
                            {t.platforms.map((p) => (
                              <span key={p} className="badge badge-muted">{p}</span>
                            ))}
                            <span className="badge badge-neutral">{fmtInt(t.total_engagement)} engagement</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : <div className="state-message">Trend data will populate after social syncs run.</div>}
                </section>

                {/* Purchase Intent Monitor */}
                <section className="card">
                  <div className="venom-panel-head">
                    <strong>Purchase Intent Monitor</strong>
                    <span className="venom-panel-hint">{fmtInt(market.purchase_intent.total)} signals detected</span>
                  </div>
                  {market.purchase_intent.posts.length > 0 ? (
                    <div className="stack-list compact">
                      {market.purchase_intent.posts.slice(0, 6).map((p, i) => (
                        <div key={i} className="list-item status-muted">
                          <div className="item-head">
                            <strong>{p.title || 'Untitled'}</strong>
                            <div className="inline-badges">
                              <span className="badge badge-neutral">{p.platform}</span>
                              {p.engagement_score > 0 ? <span className="badge badge-neutral">{fmtInt(p.engagement_score)} eng</span> : null}
                            </div>
                          </div>
                          {p.body ? <p className="venom-mention-body">{p.body.slice(0, 120)}{p.body.length > 120 ? '...' : ''}</p> : null}
                          <div className="venom-mention-meta">
                            {p.competitor_mentioned ? <span className="badge badge-warn">{p.competitor_mentioned}</span> : null}
                            {p.product_mentioned ? <span className="badge badge-good">{p.product_mentioned}</span> : null}
                            {p.source_url ? <a href={p.source_url} target="_blank" rel="noopener noreferrer" className="badge badge-neutral">View</a> : null}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : <div className="state-message">Purchase intent signals will appear as people discuss buying grills.</div>}
                </section>
              </div>

              {/* Product Innovation + Competitor Pain Points — 2-col */}
              <div className="two-col two-col-equal">
                {/* Product Innovation Ideas */}
                <section className="card">
                  <div className="venom-panel-head">
                    <strong>Product Innovation Signals</strong>
                    <span className="venom-panel-hint">R&D opportunities from real users</span>
                  </div>
                  {market.product_innovation.posts.length > 0 ? (
                    <div className="stack-list compact">
                      {market.product_innovation.posts.slice(0, 6).map((p, i) => (
                        <div key={i} className="list-item status-good">
                          <div className="item-head">
                            <strong>{p.title || 'Untitled'}</strong>
                            <div className="inline-badges">
                              <span className="badge badge-neutral">{p.platform}</span>
                              {p.engagement_score > 0 ? <span className="badge badge-neutral">{fmtInt(p.engagement_score)} eng</span> : null}
                            </div>
                          </div>
                          {p.body ? <p className="venom-mention-body">{p.body.slice(0, 150)}{p.body.length > 150 ? '...' : ''}</p> : null}
                          <div className="venom-mention-meta">
                            {p.trend_topic ? <span className="badge badge-good">{p.trend_topic}</span> : null}
                            {p.source_url ? <a href={p.source_url} target="_blank" rel="noopener noreferrer" className="badge badge-neutral">View</a> : null}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : <div className="state-message">Innovation signals appear when users describe features they wish existed.</div>}
                </section>

                {/* Competitor Pain Points */}
                <section className="card">
                  <div className="venom-panel-head">
                    <strong>Competitor Pain Points</strong>
                    <span className="venom-panel-hint">Their weaknesses = your opportunity</span>
                  </div>
                  {market.competitor_pain_points.posts.length > 0 ? (
                    <div className="stack-list compact">
                      {market.competitor_pain_points.posts.slice(0, 6).map((p, i) => (
                        <div key={i} className="list-item status-bad">
                          <div className="item-head">
                            <strong>{p.title || 'Untitled'}</strong>
                            <div className="inline-badges">
                              <span className="badge badge-neutral">{p.platform}</span>
                              {p.competitor ? <span className="badge badge-warn">{p.competitor.replace(/_/g, ' ')}</span> : null}
                            </div>
                          </div>
                          {p.body ? <p className="venom-mention-body">{p.body.slice(0, 150)}{p.body.length > 150 ? '...' : ''}</p> : null}
                          <div className="venom-mention-meta">
                            {p.engagement_score > 0 ? <span className="badge badge-neutral">{fmtInt(p.engagement_score)} eng</span> : null}
                            {p.source_url ? <a href={p.source_url} target="_blank" rel="noopener noreferrer" className="badge badge-neutral">View</a> : null}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : <div className="state-message">Competitor complaints and weaknesses will surface as social data flows in.</div>}
                </section>
              </div>
            </>
          ) : null}

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
