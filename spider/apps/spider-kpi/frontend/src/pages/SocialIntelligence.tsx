import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { TruthBadge } from '../components/TruthBadge'
import { ProvenanceBanner } from '../components/ProvenanceBanner'
import { CollapsibleSection } from '../components/CollapsibleSection'
import { DivisionHero } from '../components/DivisionHero'
import { ApiError, api } from '../lib/api'
import { fmtInt, fmtPct, fmtDecimal } from '../lib/format'
import { SocialMention, SocialPulse, SocialTrendsResponse, YouTubePerformance, AmazonProductHealth, MarketIntelligence } from '../lib/types'
import { BarChart, Bar, ResponsiveContainer, CartesianGrid, XAxis, YAxis, Tooltip } from 'recharts'

type MentionFilter = 'all' | 'positive' | 'negative' | 'questions' | 'complaints' | 'brand' | 'competitor'
type PageSection = 'overview' | 'youtube' | 'amazon' | 'competitive'

function sentimentColor(s: string) {
  if (s === 'positive') return 'var(--green)'
  if (s === 'negative') return 'var(--red)'
  return 'var(--orange)'
}

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

function classificationLabel(c: string): string {
  const map: Record<string, string> = {
    brand_mention: 'Brand Mention',
    complaint: 'Complaint',
    product_review: 'Product Review',
    purchase_intent: 'Purchase Intent',
    customer_question: 'Question',
    product_innovation: 'Innovation Signal',
    competitor_mention: 'Competitor',
    competitor_complaint: 'Competitor Complaint',
    industry_trend: 'Industry Trend',
    product_listing: 'Product Listing',
    competitor_product: 'Competitor Product',
    unknown: 'General',
  }
  return map[c] || c.replace(/_/g, ' ')
}

function platformIcon(p: string): string {
  if (p === 'reddit') return '🔶'
  if (p === 'youtube') return '▶️'
  if (p === 'amazon') return '📦'
  return '🔗'
}

function timeAgo(dateStr: string | undefined): string {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  const days = Math.floor((Date.now() - d.getTime()) / 86400000)
  if (days === 0) return 'today'
  if (days === 1) return '1d ago'
  if (days < 7) return `${days}d ago`
  if (days < 30) return `${Math.floor(days / 7)}w ago`
  return `${Math.floor(days / 30)}mo ago`
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
  const [section, setSection] = useState<PageSection>('overview')

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

  // ── Computed values ──
  const brandMentionCount = pulse?.brand_mentions ?? 0
  const totalMentions = pulse?.total_mentions ?? 0
  const avgSentiment = pulse?.avg_sentiment_score ?? 0
  const competitorTotal = trends ? Object.values(trends.competitor_mentions).reduce((s, n) => s + n, 0) : 0
  const brandSOV = (brandMentionCount + competitorTotal) > 0 ? brandMentionCount / (brandMentionCount + competitorTotal) : 0
  const trendingCount = trends?.trending_topics?.length ?? 0
  const youtubeViews = youtube?.total_views ?? 0
  const amazonProducts = amazon?.total_products ?? 0

  const sentimentBreakdown = pulse?.sentiment_breakdown || {}
  const sentimentTotal = Object.values(sentimentBreakdown).reduce((s, n) => s + n, 0) || 1
  const posPct = ((sentimentBreakdown['positive'] || 0) / sentimentTotal) * 100
  const neuPct = ((sentimentBreakdown['neutral'] || 0) / sentimentTotal) * 100
  const negPct = ((sentimentBreakdown['negative'] || 0) / sentimentTotal) * 100
  const mixPct = ((sentimentBreakdown['mixed'] || 0) / sentimentTotal) * 100

  // KPI strip removed — DivisionHero already shows brand mentions /
  // sentiment / SOV / YouTube reach with richer state colors.

  // ── Spider products vs competitor products on Amazon ──
  const spiderProducts = useMemo(() => {
    if (!amazon) return []
    return amazon.products.filter(p => p.brand?.toLowerCase().includes('spider'))
  }, [amazon])

  const competitorProducts = useMemo(() => {
    if (!amazon) return []
    return amazon.products.filter(p => !p.brand?.toLowerCase().includes('spider'))
  }, [amazon])

  // ── Filtered mentions ──
  const filteredMentions = useMemo(() => {
    let filtered = mentions.filter((m) => m.brand_mentioned || m.relevance_score > 0.3)
    switch (filter) {
      case 'positive': filtered = filtered.filter((m) => m.sentiment === 'positive'); break
      case 'negative': filtered = filtered.filter((m) => m.sentiment === 'negative'); break
      case 'questions': filtered = filtered.filter((m) => m.classification === 'customer_question'); break
      case 'complaints': filtered = filtered.filter((m) => m.classification === 'complaint' || m.classification === 'competitor_complaint'); break
      case 'brand': filtered = filtered.filter((m) => m.brand_mentioned); break
      case 'competitor': filtered = filtered.filter((m) => m.competitor_mentioned); break
    }
    return filtered.slice(0, 25)
  }, [mentions, filter])

  // ── Competitor chart ──
  const competitorChartData = useMemo(() => {
    if (!trends?.competitor_mentions) return []
    return Object.entries(trends.competitor_mentions)
      .sort(([, a], [, b]) => b - a)
      .slice(0, 8)
      .map(([name, count]) => ({ name: name.replace(/_/g, ' '), count }))
  }, [trends])

  // ── Product mentions chart ──
  const productChartData = useMemo(() => {
    if (!trends?.product_mentions) return []
    return Object.entries(trends.product_mentions)
      .sort(([, a], [, b]) => b - a)
      .map(([name, count]) => ({ name, count }))
  }, [trends])

  const hasData = totalMentions > 0 || trendingCount > 0 || mentions.length > 0

  // ── Platform breakdown ──
  const byPlatform = pulse?.by_platform || {}
  const platformParts: string[] = []
  if (byPlatform['reddit']) platformParts.push(`${byPlatform['reddit']} Reddit`)
  if (byPlatform['youtube']) platformParts.push(`${byPlatform['youtube']} YouTube`)
  if (byPlatform['amazon']) platformParts.push(`${byPlatform['amazon']} Amazon`)

  const SECTION_TABS: [PageSection, string][] = [
    ['overview', 'Overview'],
    ['youtube', 'YouTube'],
    ['amazon', 'Amazon'],
    ['competitive', 'Competitive Intel'],
  ]

  return (
    <div className="page-grid venom-page">
      {/* ── DIVISION HERO — signature: wave ─────────────────────────
          Sentiment curve over a 14-point series built around the
          current average sentiment. Unique wave shape for this
          page; rising crest = positive trend, trough = negative. */}
      {(() => {
        // Build a simple 14-point wave around avgSentiment. Amplitude
        // reflects sentiment spread (neutral = flatter; polarized = choppier).
        const amplitude = Math.max(0.1, (negPct + posPct) / 150)
        const bias = avgSentiment
        const series = Array.from({ length: 14 }, (_, i) => {
          const base = bias
          const osc = Math.sin(i * 0.9) * amplitude
          const drift = (i / 14) * (bias * 0.5)
          return (base + osc + drift).toFixed(3)
        }).join(',')
        const sentState: 'good' | 'warn' | 'bad' | 'neutral' =
          avgSentiment >= 0.2 ? 'good'
          : avgSentiment >= 0 ? 'warn'
          : avgSentiment >= -0.2 ? 'warn'
          : 'bad'
        return (
          <DivisionHero
            accentColor="#ec4899"
            accentColorSoft="#06b6d4"
            signature="wave"
            title="Social Intelligence"
            subtitle={hasData
              ? `${fmtInt(totalMentions)} signals across ${platformParts.join(', ') || 'all platforms'} · US market priority`
              : 'Monitoring Reddit, YouTube, and Amazon for brand and competitor signals'}
            rightMeta={
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {SECTION_TABS.map(([key, label]) => (
                  <button key={key} className={`range-button${section === key ? ' active' : ''}`} onClick={() => setSection(key)}>{label}</button>
                ))}
              </div>
            }
            primary={{
              label: 'Brand sentiment (14-point wave)',
              value: avgSentiment > 0.1 ? `+${avgSentiment.toFixed(2)}` : avgSentiment < -0.1 ? avgSentiment.toFixed(2) : 'Neutral',
              sublabel: `${fmtInt(brandMentionCount)} brand mentions · ${posPct.toFixed(0)}% positive`,
              state: sentState,
              progress: (avgSentiment + 1) / 2,
              extra: { sparkline: series },
            }}
            flanking={[
              {
                label: 'Share of voice',
                value: fmtPct(brandSOV, 0),
                sublabel: `vs ${fmtInt(competitorTotal)} competitor mentions`,
                state: brandSOV >= 0.25 ? 'good' : brandSOV >= 0.15 ? 'warn' : 'bad',
                progress: brandSOV,
              },
              {
                label: 'YouTube reach',
                value: formatViews(youtubeViews),
                sublabel: 'last 30d',
                state: youtubeViews > 0 ? 'good' : 'neutral',
              },
            ]}
            tiles={[
              { label: 'Brand mentions', value: fmtInt(brandMentionCount), state: brandMentionCount > 10 ? 'good' : 'neutral' },
              { label: 'Trending topics', value: String(trendingCount), state: 'neutral' },
              { label: '% positive', value: `${posPct.toFixed(0)}%`, state: posPct >= 60 ? 'good' : posPct >= 40 ? 'warn' : 'bad' },
              { label: '% negative', value: `${negPct.toFixed(0)}%`, state: negPct <= 10 ? 'good' : negPct <= 25 ? 'warn' : 'bad' },
              { label: 'Competitors tracked', value: String(Object.keys(trends?.competitor_mentions ?? {}).length), state: 'neutral' },
              { label: 'Amazon products', value: fmtInt(amazonProducts), state: amazonProducts > 0 ? 'good' : 'neutral' },
            ]}
          />
        )
      })()}

      {loading ? <Card title="Loading"><div className="state-message">Loading social intelligence...</div></Card> : null}
      {error ? <Card title="Error"><div className="state-message error">{error}</div></Card> : null}

      {!loading && !error ? (
        <>
          {/* Section nav rendered once in the DivisionHero rightMeta;
              the duplicate row that used to appear here was removed. */}

          {/* VenomKpiStrip removed — DivisionHero owns those numbers.
              ProvenanceBanner folded so it doesn't push content down
              on every section view. */}
          <CollapsibleSection
            id="si-provenance"
            title="Source coverage & provenance"
            subtitle="Where these social signals come from and why sentiment is estimated"
            density="compact"
          >
            <ProvenanceBanner
              compact
              truthState="estimated"
              scope="7-day rolling · Reddit, YouTube, Amazon, Google Reviews"
              caveat="Sentiment is NLP-estimated. Mention counts reflect indexed posts only — not total market conversation."
            />
          </CollapsibleSection>

          {/* ════════════════════════════════════════════════
              SECTION: Overview
              ════════════════════════════════════════════════ */}
          {section === 'overview' ? (
            <>
              {/* Brand Health + Sentiment */}
              <div className="two-col two-col-equal">
                <section className="card">
                  <div className="venom-panel-head">
                    <strong>Brand Health</strong>
                    <TruthBadge state="estimated" />
                  </div>
                  {totalMentions > 0 ? (
                    <>
                      <div className="venom-sentiment-bar" style={{ marginBottom: 8 }}>
                        <div style={{ width: `${posPct}%`, background: 'var(--green)' }} title={`Positive: ${sentimentBreakdown['positive'] || 0}`} />
                        <div style={{ width: `${neuPct + mixPct}%`, background: 'var(--orange)' }} title={`Neutral/Mixed: ${(sentimentBreakdown['neutral'] || 0) + (sentimentBreakdown['mixed'] || 0)}`} />
                        <div style={{ width: `${negPct}%`, background: 'var(--red)' }} title={`Negative: ${sentimentBreakdown['negative'] || 0}`} />
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: 'var(--muted)', marginBottom: 12 }}>
                        <span style={{ color: 'var(--green)' }}>Positive: {sentimentBreakdown['positive'] || 0}</span>
                        <span style={{ color: 'var(--orange)' }}>Neutral: {(sentimentBreakdown['neutral'] || 0) + (sentimentBreakdown['mixed'] || 0)}</span>
                        <span style={{ color: 'var(--red)' }}>Negative: {sentimentBreakdown['negative'] || 0}</span>
                      </div>
                      {/* Platform breakdown */}
                      <div style={{ fontSize: 12, color: 'var(--muted)' }}>
                        <strong style={{ color: '#e2e8f0' }}>By Platform</strong>
                        <div style={{ display: 'flex', gap: 12, marginTop: 6, flexWrap: 'wrap' }}>
                          {Object.entries(byPlatform).map(([p, count]) => (
                            <div key={p} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                              <span>{platformIcon(p)}</span>
                              <span>{p}: <strong style={{ color: '#e2e8f0' }}>{count}</strong></span>
                            </div>
                          ))}
                        </div>
                      </div>
                    </>
                  ) : <div className="state-message">Waiting for social data...</div>}
                </section>

                <section className="card">
                  <div className="venom-panel-head">
                    <strong>Product Mentions</strong>
                    <span className="venom-panel-hint">30 days</span>
                  </div>
                  {productChartData.length > 0 ? (
                    <div className="chart-wrap-short">
                      <ResponsiveContainer width="100%" height={180}>
                        <BarChart data={productChartData}>
                          <CartesianGrid stroke="rgba(255,255,255,0.06)" />
                          <XAxis dataKey="name" stroke="#9fb0d4" tick={{ fontSize: 11 }} />
                          <YAxis stroke="#9fb0d4" />
                          <Tooltip />
                          <Bar dataKey="count" name="Mentions" fill="var(--green)" radius={[4, 4, 0, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  ) : <div className="state-message">Product mention data will populate after sync.</div>}
                </section>
              </div>

              {/* Competitor Share of Voice */}
              <div className="two-col two-col-equal">
                <section className="card">
                  <div className="venom-panel-head">
                    <strong>Competitor Share of Voice</strong>
                    <span className="venom-panel-hint">30-day mentions</span>
                  </div>
                  {competitorChartData.length > 0 ? (
                    <div className="chart-wrap-short">
                      <ResponsiveContainer width="100%" height={Math.max(180, competitorChartData.length * 28)}>
                        <BarChart data={competitorChartData} layout="vertical">
                          <CartesianGrid stroke="rgba(255,255,255,0.06)" />
                          <XAxis type="number" stroke="#9fb0d4" />
                          <YAxis type="category" dataKey="name" stroke="#9fb0d4" tick={{ fontSize: 11 }} width={100} />
                          <Tooltip />
                          <Bar dataKey="count" name="Mentions" fill="var(--orange)" radius={[0, 4, 4, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  ) : <div className="state-message">Competitor data populating...</div>}
                </section>

                <section className="card">
                  <div className="venom-panel-head">
                    <strong>Trending Topics</strong>
                    <span className="venom-panel-hint">30 days · r/smoking, r/grilling, r/BBQ</span>
                  </div>
                  {(trends?.trending_topics?.length || 0) > 0 ? (
                    <div className="stack-list compact">
                      {trends!.trending_topics.slice(0, 8).map((t) => (
                        <div key={t.topic} className="list-item status-muted">
                          <div className="item-head">
                            <strong>{t.topic}</strong>
                            <div className="inline-badges">
                              <span className="badge badge-neutral">{fmtInt(t.mention_count)}</span>
                              <span className="badge badge-muted">{fmtInt(t.total_engagement)} eng</span>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : <div className="state-message">Trends populate after Reddit sync.</div>}
                </section>
              </div>

              {/* Brand Mentions Feed — folded by default. Heaviest single
                  block on the overview tab; viewers drill in when they
                  need the per-mention list. */}
              <CollapsibleSection
                id="si-social-feed"
                title="Social feed"
                subtitle="Per-mention sentiment, classification, source"
                density="compact"
                meta={`${fmtInt(filteredMentions.length)} of ${fmtInt(mentions.length)} · 7 days`}
              >
                <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
                  {(['all', 'brand', 'positive', 'negative', 'questions', 'complaints', 'competitor'] as MentionFilter[]).map((tab) => (
                    <button key={tab} className={`range-button${filter === tab ? ' active' : ''}`} onClick={() => setFilter(tab)} style={{ fontSize: 11, padding: '4px 10px', textTransform: 'capitalize' }}>{tab}</button>
                  ))}
                </div>
                {filteredMentions.length > 0 ? (
                  <div className="stack-list compact">
                    {filteredMentions.map((m) => (
                      <div key={m.external_id} className={`list-item status-${sentimentStatus(m.sentiment)}`}>
                        <div className="item-head">
                          <strong style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <span style={{ fontSize: 14 }}>{platformIcon(m.platform)}</span>
                            {m.title || 'Untitled'}
                          </strong>
                          <div className="inline-badges">
                            <span className={`badge ${sentimentBadgeClass(m.sentiment)}`}>{m.sentiment}</span>
                            <span className="badge badge-muted">{classificationLabel(m.classification)}</span>
                            {m.published_at ? <span className="badge badge-muted">{timeAgo(m.published_at)}</span> : null}
                          </div>
                        </div>
                        {m.body ? <p className="venom-mention-body" style={{ maxHeight: 60, overflow: 'hidden' }}>{m.body.slice(0, 200)}{m.body.length > 200 ? '...' : ''}</p> : null}
                        <div className="venom-mention-meta">
                          {m.subreddit ? <span className="badge badge-muted">r/{m.subreddit}</span> : null}
                          {m.platform === 'youtube' && m.engagement_score > 0 ? <span className="badge badge-neutral">{formatViews(m.engagement_score)} views</span> : null}
                          {m.platform !== 'youtube' && m.engagement_score > 0 ? <span className="badge badge-neutral">{m.engagement_score} pts</span> : null}
                          {m.comment_count > 0 ? <span className="badge badge-neutral">{m.comment_count} comments</span> : null}
                          {m.product_mentioned ? <span className="badge badge-good">{m.product_mentioned}</span> : null}
                          {m.competitor_mentioned ? <span className="badge badge-warn">{m.competitor_mentioned.replace(/_/g, ' ')}</span> : null}
                          {m.source_url ? <a href={m.source_url} target="_blank" rel="noopener noreferrer" className="badge badge-neutral" style={{ textDecoration: 'none' }}>View &rarr;</a> : null}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : <div className="state-message">{hasData ? 'No mentions match this filter.' : 'Social feed populates after first sync.'}</div>}
              </CollapsibleSection>
            </>
          ) : null}

          {/* ════════════════════════════════════════════════
              SECTION: YouTube
              ════════════════════════════════════════════════ */}
          {section === 'youtube' ? (
            <>
              {youtube && youtube.total_videos > 0 ? (
                <>
                  {/* YouTube KPIs */}
                  <section className="card">
                    <div className="venom-panel-head">
                      <strong>YouTube Performance</strong>
                      <span className="venom-panel-hint">30-day US-prioritized content</span>
                    </div>
                    <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', marginBottom: 12 }}>
                      <div className="mini-stat">
                        <span className="mini-stat-value">{fmtInt(youtube.total_videos)}</span>
                        <span className="mini-stat-label">Videos Tracked</span>
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
                        <span className="mini-stat-label">Engagement Rate</span>
                      </div>
                      <div className="mini-stat">
                        <span className="mini-stat-value">{fmtInt(youtube.total_comments)}</span>
                        <span className="mini-stat-label">Comments</span>
                      </div>
                    </div>
                    {/* Sentiment bar */}
                    {youtube.sentiment_breakdown ? (
                      <div style={{ display: 'flex', gap: 12, fontSize: 12, color: 'var(--muted)' }}>
                        {Object.entries(youtube.sentiment_breakdown).map(([s, count]) => (
                          <span key={s} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                            <span style={{ width: 8, height: 8, borderRadius: '50%', background: sentimentColor(s) }} />
                            {s}: {count}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </section>

                  {/* Top Videos */}
                  <section className="card">
                    <div className="venom-panel-head">
                      <strong>Top Videos</strong>
                      <span className="venom-panel-hint">Sorted by views</span>
                    </div>
                    <div className="stack-list compact">
                      {youtube.top_videos.slice(0, 10).map((v) => (
                        <div key={v.video_id} className={`list-item status-${sentimentStatus(v.sentiment)}`}>
                          <div className="item-head">
                            <strong>{v.title || 'Untitled'}</strong>
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
                            {v.competitor_mentioned ? <span className="badge badge-warn">{v.competitor_mentioned.replace(/_/g, ' ')}</span> : null}
                            {v.published_at ? <span className="badge badge-muted">{timeAgo(v.published_at)}</span> : null}
                            <a href={v.source_url} target="_blank" rel="noopener noreferrer" className="badge badge-neutral" style={{ textDecoration: 'none' }}>Watch &rarr;</a>
                          </div>
                          {/* Top comments — English only */}
                          {v.top_comments && v.top_comments.length > 0 ? (
                            <div style={{ marginTop: 8, paddingLeft: 12, borderLeft: '2px solid rgba(255,255,255,0.1)' }}>
                              {v.top_comments.slice(0, 2).map((c, i) => (
                                <div key={i} style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 4 }}>
                                  <strong>{c.author}</strong>: {c.text.slice(0, 180)}{c.text.length > 180 ? '...' : ''}
                                  {c.likes > 0 ? <span style={{ marginLeft: 6, color: 'var(--blue)', fontSize: 11 }}>({c.likes} likes)</span> : null}
                                </div>
                              ))}
                            </div>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  </section>

                  {/* Comment Highlights */}
                  {youtube.comment_highlights.length > 0 ? (
                    <CollapsibleSection
                      id="si-yt-comment-highlights"
                      title="Top comments across all videos"
                      subtitle="Reference detail — drill in for the full audience-voice list"
                      density="compact"
                      meta={`${youtube.comment_highlights.length} comments · sorted by likes`}
                    >
                      <div className="stack-list compact">
                        {youtube.comment_highlights.slice(0, 6).map((c, i) => (
                          <div key={i} className="list-item status-muted">
                            <div style={{ fontSize: 13 }}>
                              <strong style={{ color: '#e2e8f0' }}>{c.author}</strong>
                              <span style={{ marginLeft: 8, color: 'var(--muted)' }}>{c.text.slice(0, 250)}{c.text.length > 250 ? '...' : ''}</span>
                            </div>
                            <div className="venom-mention-meta" style={{ marginTop: 4 }}>
                              {c.likes > 0 ? <span className="badge badge-neutral">{c.likes} likes</span> : null}
                              {c.published_at ? <span className="badge badge-muted">{timeAgo(c.published_at)}</span> : null}
                            </div>
                          </div>
                        ))}
                      </div>
                    </CollapsibleSection>
                  ) : null}
                </>
              ) : (
                <section className="card">
                  <div className="state-message">YouTube data is syncing. Results will appear within 1-2 sync cycles (every 6 hours).</div>
                </section>
              )}
            </>
          ) : null}

          {/* ════════════════════════════════════════════════
              SECTION: Amazon
              ════════════════════════════════════════════════ */}
          {section === 'amazon' ? (
            <>
              {amazon && amazon.total_products > 0 ? (
                <>
                  {/* Amazon KPIs */}
                  <section className="card">
                    <div className="venom-panel-head">
                      <strong>Amazon Marketplace Overview</strong>
                      <TruthBadge state="proxy" />
                    </div>
                    <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
                      <div className="mini-stat">
                        <span className="mini-stat-value">{fmtInt(spiderProducts.length)}</span>
                        <span className="mini-stat-label">Our Products</span>
                      </div>
                      <div className="mini-stat">
                        <span className="mini-stat-value">{fmtInt(competitorProducts.length)}</span>
                        <span className="mini-stat-label">Competitors Tracked</span>
                      </div>
                      {amazon.best_bsr != null ? (
                        <div className="mini-stat">
                          <span className="mini-stat-value" style={{ color: 'var(--green)' }}>#{fmtInt(amazon.best_bsr)}</span>
                          <span className="mini-stat-label">Best BSR</span>
                        </div>
                      ) : null}
                      {amazon.avg_bsr != null ? (
                        <div className="mini-stat">
                          <span className="mini-stat-value">#{fmtInt(amazon.avg_bsr)}</span>
                          <span className="mini-stat-label">Avg BSR</span>
                        </div>
                      ) : null}
                      {market?.amazon_positioning?.price ? (
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
                            <span className="mini-stat-value" style={{ color: market.amazon_positioning.price.position === 'premium' ? 'var(--orange)' : 'var(--green)' }}>
                              {market.amazon_positioning.price.position}
                            </span>
                            <span className="mini-stat-label">Price Position</span>
                          </div>
                        </>
                      ) : null}
                    </div>
                  </section>

                  {/* Spider Grills Products */}
                  <section className="card">
                    <div className="venom-panel-head">
                      <strong>Spider Grills Products</strong>
                      <span className="venom-panel-hint">{spiderProducts.length} listings</span>
                    </div>
                    {spiderProducts.length > 0 ? (
                      <div className="stack-list compact">
                        {spiderProducts.map((p) => (
                          <div key={p.asin} className="list-item status-good">
                            <div className="item-head">
                              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                                {p.image_url ? <img src={p.image_url} alt="" style={{ width: 44, height: 44, objectFit: 'contain', borderRadius: 4, background: 'rgba(255,255,255,0.05)' }} /> : null}
                                <div>
                                  <strong>{p.title || p.asin}</strong>
                                  <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{p.asin}</div>
                                </div>
                              </div>
                              <div className="inline-badges">
                                {p.bsr != null ? <span className="badge badge-good">BSR #{fmtInt(p.bsr)}</span> : <span className="badge badge-muted">No BSR</span>}
                                {p.bsr_category ? <span className="badge badge-muted">{p.bsr_category}</span> : null}
                              </div>
                            </div>
                            <div className="venom-mention-meta">
                              {p.competitive_price != null ? <span className="badge badge-neutral">${p.competitive_price.toFixed(2)}</span> : null}
                              <a href={p.source_url} target="_blank" rel="noopener noreferrer" className="badge badge-neutral" style={{ textDecoration: 'none' }}>Amazon &rarr;</a>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : <div className="state-message">No Spider Grills products found in catalog.</div>}
                  </section>

                  {/* Competitor Products — folded; 10+ rows of reference detail. */}
                  {competitorProducts.length > 0 ? (
                    <CollapsibleSection
                      id="si-amazon-competitors"
                      title="Competitor products"
                      subtitle="Per-ASIN brand, BSR, category"
                      density="compact"
                      meta={`${competitorProducts.length} tracked`}
                    >
                      <div style={{ overflowX: 'auto' }}>
                        <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse', minWidth: 600 }}>
                          <thead>
                            <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.15)', color: 'var(--muted)' }}>
                              <th style={{ textAlign: 'left', padding: '8px' }}>Product</th>
                              <th style={{ textAlign: 'left', padding: '8px' }}>Brand</th>
                              <th style={{ textAlign: 'center', padding: '8px' }}>BSR</th>
                              <th style={{ textAlign: 'center', padding: '8px' }}>Category</th>
                              <th style={{ textAlign: 'center', padding: '8px' }}>Link</th>
                            </tr>
                          </thead>
                          <tbody>
                            {competitorProducts.map((p) => (
                              <tr key={p.asin} style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                                <td style={{ padding: '8px', maxWidth: 300 }}>
                                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                    {p.image_url ? <img src={p.image_url} alt="" style={{ width: 32, height: 32, objectFit: 'contain', borderRadius: 3, background: 'rgba(255,255,255,0.05)' }} /> : null}
                                    <span style={{ fontWeight: 500 }}>{(p.title || p.asin).slice(0, 80)}{(p.title || '').length > 80 ? '...' : ''}</span>
                                  </div>
                                </td>
                                <td style={{ padding: '8px', color: 'var(--orange)', fontWeight: 500 }}>{p.brand || '—'}</td>
                                <td style={{ textAlign: 'center', padding: '8px' }}>
                                  {p.bsr != null ? <span style={{ color: 'var(--green)', fontWeight: 600 }}>#{fmtInt(p.bsr)}</span> : <span style={{ color: 'var(--muted)' }}>—</span>}
                                </td>
                                <td style={{ textAlign: 'center', padding: '8px', fontSize: 11, color: 'var(--muted)' }}>{p.bsr_category || '—'}</td>
                                <td style={{ textAlign: 'center', padding: '8px' }}>
                                  <a href={p.source_url} target="_blank" rel="noopener noreferrer" className="badge badge-neutral" style={{ textDecoration: 'none', fontSize: 11 }}>View</a>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </CollapsibleSection>
                  ) : null}
                </>
              ) : (
                <section className="card">
                  <div className="state-message">Amazon product data syncing. Data appears after SP-API connector runs.</div>
                </section>
              )}
            </>
          ) : null}

          {/* ════════════════════════════════════════════════
              SECTION: Competitive Intel
              ════════════════════════════════════════════════ */}
          {section === 'competitive' ? (
            <>
              {market && market.total_mentions > 0 ? (
                <>
                  {/* Competitive Landscape */}
                  <section className="card">
                    <div className="venom-panel-head">
                      <strong>Competitive Landscape</strong>
                      <span className="venom-panel-hint">30-day cross-platform analysis</span>
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
                        <span className="mini-stat-label">Competitors</span>
                      </div>
                    </div>
                  </section>
                  {/* Per-competitor table — fold separately so the
                      3 mini-stats above stay visible at-a-glance. */}
                  {market.competitive_landscape.competitors.length > 0 ? (
                    <CollapsibleSection
                      id="si-comp-landscape-table"
                      title="Per-competitor breakdown"
                      subtitle="Mentions · SOV · sentiment · engagement"
                      density="compact"
                      meta={`${Math.min(market.competitive_landscape.competitors.length, 12)} tracked`}
                    >
                      <div style={{ overflowX: 'auto' }}>
                        <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
                          <thead>
                            <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.15)', color: 'var(--muted)' }}>
                              <th style={{ textAlign: 'left', padding: '6px 8px' }}>Competitor</th>
                              <th style={{ textAlign: 'right', padding: '6px 8px' }}>Mentions</th>
                              <th style={{ textAlign: 'right', padding: '6px 8px' }}>SOV</th>
                              <th style={{ textAlign: 'right', padding: '6px 8px' }}>Sentiment</th>
                              <th style={{ textAlign: 'right', padding: '6px 8px' }}>Engagement</th>
                            </tr>
                          </thead>
                          <tbody>
                            {market.competitive_landscape.competitors.slice(0, 12).map((c) => (
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
                    </CollapsibleSection>
                  ) : null}

                  {/* Trend momentum stays visible — most-glanceable signal.
                      Purchase Intent folds (it's a 6-row reference list). */}
                  <section className="card">
                    <div className="venom-panel-head">
                      <strong>Trend Momentum</strong>
                      <span className="venom-panel-hint">Cross-platform topics</span>
                    </div>
                    {market.trend_momentum.length > 0 ? (
                      <div className="stack-list compact">
                        {market.trend_momentum.slice(0, 8).map((t) => (
                          <div key={t.topic} className="list-item status-muted">
                            <div className="item-head">
                              <strong>{t.topic}</strong>
                              <div className="inline-badges">
                                <span className={`badge ${t.momentum === 'strong' ? 'badge-good' : t.momentum === 'growing' ? 'badge-warn' : 'badge-muted'}`}>{t.momentum}</span>
                                <span className="badge badge-neutral">{fmtInt(t.mentions)}</span>
                                {t.cross_platform ? <span className="badge badge-good">multi-platform</span> : null}
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : <div className="state-message">Trend data populating...</div>}
                  </section>

                  <CollapsibleSection
                    id="si-purchase-intent"
                    title="Purchase intent"
                    subtitle="Posts where people discuss buying grills"
                    density="compact"
                    meta={`${fmtInt(market.purchase_intent.total)} signals`}
                  >
                    {market.purchase_intent.posts.length > 0 ? (
                      <div className="stack-list compact">
                        {market.purchase_intent.posts.slice(0, 6).map((p, i) => (
                          <div key={i} className="list-item status-muted">
                            <div className="item-head">
                              <strong>{p.title || 'Untitled'}</strong>
                              <div className="inline-badges">
                                <span className="badge badge-neutral">{platformIcon(p.platform)} {p.platform}</span>
                              </div>
                            </div>
                            {p.body ? <p className="venom-mention-body" style={{ maxHeight: 40, overflow: 'hidden' }}>{p.body.slice(0, 120)}</p> : null}
                            <div className="venom-mention-meta">
                              {p.competitor_mentioned ? <span className="badge badge-warn">{p.competitor_mentioned.replace(/_/g, ' ')}</span> : null}
                              {p.product_mentioned ? <span className="badge badge-good">{p.product_mentioned}</span> : null}
                              {p.source_url ? <a href={p.source_url} target="_blank" rel="noopener noreferrer" className="badge badge-neutral" style={{ textDecoration: 'none' }}>View &rarr;</a> : null}
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : <div className="state-message">Purchase intent signals appear as people discuss buying grills.</div>}
                  </CollapsibleSection>

                  {/* Innovation + Pain Points — folded together, both
                      are 5-row reference lists. */}
                  <CollapsibleSection
                    id="si-innovation-and-pain"
                    title="Innovation signals & competitor pain points"
                    subtitle="R&D opportunities · their weakness = your opportunity"
                    density="compact"
                    meta={`${market.product_innovation.posts.length} innovation · ${market.competitor_pain_points.posts.length} pain`}
                  >
                    <div className="two-col two-col-equal">
                      <section className="card">
                        <div className="venom-panel-head">
                          <strong>Innovation Signals</strong>
                          <span className="venom-panel-hint">R&D opportunities</span>
                        </div>
                        {market.product_innovation.posts.length > 0 ? (
                          <div className="stack-list compact">
                            {market.product_innovation.posts.slice(0, 5).map((p, i) => (
                              <div key={i} className="list-item status-good">
                                <div className="item-head">
                                  <strong>{p.title || 'Untitled'}</strong>
                                  <div className="inline-badges">
                                    <span className="badge badge-neutral">{platformIcon(p.platform)}</span>
                                    {p.engagement_score > 0 ? <span className="badge badge-neutral">{fmtInt(p.engagement_score)} eng</span> : null}
                                  </div>
                                </div>
                                {p.body ? <p className="venom-mention-body" style={{ maxHeight: 40, overflow: 'hidden' }}>{p.body.slice(0, 120)}</p> : null}
                                {p.trend_topic ? <span className="badge badge-good" style={{ marginTop: 4, display: 'inline-block' }}>{p.trend_topic}</span> : null}
                              </div>
                            ))}
                          </div>
                        ) : <div className="state-message">Innovation signals populate from user feature requests.</div>}
                      </section>

                      <section className="card">
                        <div className="venom-panel-head">
                          <strong>Competitor Pain Points</strong>
                          <span className="venom-panel-hint">Their weakness = your opportunity</span>
                        </div>
                        {market.competitor_pain_points.posts.length > 0 ? (
                          <div className="stack-list compact">
                            {market.competitor_pain_points.posts.slice(0, 5).map((p, i) => (
                              <div key={i} className="list-item status-bad">
                                <div className="item-head">
                                  <strong>{p.title || 'Untitled'}</strong>
                                  <div className="inline-badges">
                                    {p.competitor ? <span className="badge badge-warn">{p.competitor.replace(/_/g, ' ')}</span> : null}
                                  </div>
                                </div>
                                {p.body ? <p className="venom-mention-body" style={{ maxHeight: 40, overflow: 'hidden' }}>{p.body.slice(0, 120)}</p> : null}
                              </div>
                            ))}
                          </div>
                        ) : <div className="state-message">Competitor complaints surface as social data flows in.</div>}
                      </section>
                    </div>
                  </CollapsibleSection>
                </>
              ) : (
                <section className="card">
                  <div className="state-message">Competitive intelligence populates after social connectors sync. Tracking Reddit, YouTube, and Amazon.</div>
                </section>
              )}
            </>
          ) : null}

          {/* Related navigation folded — these are nav aids, not signals. */}
          <CollapsibleSection
            id="si-related"
            title="Related drill-downs"
            subtitle="Customer Experience · Marketing · Issue Radar · Product Engineering"
            density="compact"
          >
            <div className="venom-drill-grid">
              <Link to="/division/customer-experience" className="venom-drill-tile"><div><strong>Customer Experience</strong><small>Support + brand pulse</small></div></Link>
              <Link to="/division/marketing" className="venom-drill-tile"><div><strong>Marketing</strong><small>Campaigns + funnel</small></div></Link>
              <Link to="/issues" className="venom-drill-tile"><div><strong>Issue Radar</strong><small>Social early warning</small></div></Link>
              <Link to="/division/product-engineering" className="venom-drill-tile"><div><strong>Product Engineering</strong><small>Fleet telemetry</small></div></Link>
            </div>
          </CollapsibleSection>
        </>
      ) : null}
    </div>
  )
}
