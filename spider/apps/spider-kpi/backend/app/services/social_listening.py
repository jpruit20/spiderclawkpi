"""Social listening service.

Aggregation and query helpers for social_mentions data used by the API layer.
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models import SocialMention

logger = logging.getLogger(__name__)


def get_social_mentions(
    db: Session,
    platform: str | None = None,
    classification: str | None = None,
    days: int = 7,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return a list of social mention dicts, newest first."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    query = (
        select(SocialMention)
        .where(SocialMention.published_at >= cutoff)
        .order_by(desc(SocialMention.published_at))
        .limit(limit)
    )
    if platform:
        query = query.where(SocialMention.platform == platform)
    if classification:
        query = query.where(SocialMention.classification == classification)

    rows = db.execute(query).scalars().all()
    return [
        {
            "id": row.id,
            "platform": row.platform,
            "external_id": row.external_id,
            "source_url": row.source_url,
            "title": row.title,
            "body": (row.body or "")[:500],
            "author": row.author,
            "subreddit": row.subreddit,
            "engagement_score": row.engagement_score,
            "comment_count": row.comment_count,
            "sentiment": row.sentiment,
            "sentiment_score": row.sentiment_score,
            "classification": row.classification,
            "brand_mentioned": row.brand_mentioned,
            "product_mentioned": row.product_mentioned,
            "competitor_mentioned": row.competitor_mentioned,
            "trend_topic": row.trend_topic,
            "relevance_score": row.relevance_score,
            "published_at": row.published_at.isoformat() if row.published_at else None,
            "discovered_at": row.discovered_at.isoformat() if row.discovered_at else None,
        }
        for row in rows
    ]


def get_social_trends(db: Session, days: int = 30) -> dict[str, Any]:
    """Return trending topics aggregated from social_mentions."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(
        select(SocialMention).where(SocialMention.published_at >= cutoff)
    ).scalars().all()

    topic_counter: Counter[str] = Counter()
    topic_engagement: defaultdict[str, int] = defaultdict(int)
    classification_counter: Counter[str] = Counter()
    platform_counter: Counter[str] = Counter()
    competitor_counter: Counter[str] = Counter()
    product_counter: Counter[str] = Counter()

    for row in rows:
        classification_counter[row.classification] += 1
        platform_counter[row.platform] += 1
        if row.trend_topic:
            topic_counter[row.trend_topic] += 1
            topic_engagement[row.trend_topic] += row.engagement_score
        if row.competitor_mentioned:
            competitor_counter[row.competitor_mentioned] += 1
        if row.product_mentioned:
            product_counter[row.product_mentioned] += 1

    trending_topics = [
        {
            "topic": topic,
            "mention_count": count,
            "total_engagement": topic_engagement[topic],
        }
        for topic, count in topic_counter.most_common(20)
    ]

    return {
        "period_days": days,
        "total_mentions": len(rows),
        "trending_topics": trending_topics,
        "by_classification": dict(classification_counter.most_common()),
        "by_platform": dict(platform_counter.most_common()),
        "competitor_mentions": dict(competitor_counter.most_common(10)),
        "product_mentions": dict(product_counter.most_common(10)),
    }


def get_brand_pulse(db: Session, days: int = 7) -> dict[str, Any]:
    """Return brand health metrics: mention count, sentiment breakdown, top mentions."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(
        select(SocialMention).where(SocialMention.published_at >= cutoff)
    ).scalars().all()

    total = len(rows)
    brand_mentions = [r for r in rows if r.brand_mentioned]
    sentiment_counts: Counter[str] = Counter()
    sentiment_scores: list[float] = []
    platform_counts: Counter[str] = Counter()

    for row in rows:
        sentiment_counts[row.sentiment] += 1
        sentiment_scores.append(row.sentiment_score)
        platform_counts[row.platform] += 1

    avg_sentiment = round(sum(sentiment_scores) / len(sentiment_scores), 3) if sentiment_scores else 0.0

    # Top mentions by engagement
    top_mentions = sorted(rows, key=lambda r: r.engagement_score, reverse=True)[:10]
    top_mentions_out = [
        {
            "platform": m.platform,
            "title": m.title,
            "source_url": m.source_url,
            "engagement_score": m.engagement_score,
            "sentiment": m.sentiment,
            "classification": m.classification,
            "published_at": m.published_at.isoformat() if m.published_at else None,
        }
        for m in top_mentions
    ]

    return {
        "period_days": days,
        "total_mentions": total,
        "brand_mentions": len(brand_mentions),
        "avg_sentiment_score": avg_sentiment,
        "sentiment_breakdown": dict(sentiment_counts.most_common()),
        "by_platform": dict(platform_counts.most_common()),
        "top_mentions": top_mentions_out,
    }


def get_youtube_performance(db: Session, days: int = 30) -> dict[str, Any]:
    """Return YouTube-specific video performance metrics."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(
        select(SocialMention).where(
            SocialMention.published_at >= cutoff,
            SocialMention.platform == "youtube",
        ).order_by(desc(SocialMention.engagement_score))
    ).scalars().all()

    total_views = 0
    total_likes = 0
    total_comments = 0
    sentiment_counts: Counter[str] = Counter()
    all_comments: list[dict[str, Any]] = []

    top_videos = []
    for row in rows:
        views = row.engagement_score or 0
        meta = row.metadata_json or {}
        likes = meta.get("like_count", 0)
        engagement_rate = meta.get("engagement_rate", 0.0)
        total_views += views
        total_likes += likes
        total_comments += row.comment_count or 0
        sentiment_counts[row.sentiment] += 1

        video_data: dict[str, Any] = {
            "video_id": row.external_id,
            "title": row.title,
            "author": row.author,
            "source_url": row.source_url,
            "views": views,
            "likes": likes,
            "comments": row.comment_count or 0,
            "engagement_rate": engagement_rate,
            "sentiment": row.sentiment,
            "product_mentioned": row.product_mentioned,
            "competitor_mentioned": row.competitor_mentioned,
            "published_at": row.published_at.isoformat() if row.published_at else None,
        }

        # Include top comments if available
        top_comments = meta.get("top_comments", [])
        if top_comments:
            video_data["top_comments"] = top_comments[:3]
            all_comments.extend(top_comments)

        top_videos.append(video_data)

    avg_engagement_rate = (
        round(total_likes / total_views * 100, 2) if total_views > 0 else 0.0
    )

    # Find most-discussed comment themes
    comment_highlights = sorted(all_comments, key=lambda c: c.get("likes", 0), reverse=True)[:5]

    return {
        "period_days": days,
        "total_videos": len(rows),
        "total_views": total_views,
        "total_likes": total_likes,
        "total_comments": total_comments,
        "avg_engagement_rate": avg_engagement_rate,
        "sentiment_breakdown": dict(sentiment_counts.most_common()),
        "top_videos": top_videos[:15],
        "comment_highlights": comment_highlights,
    }


def get_amazon_product_health(db: Session) -> dict[str, Any]:
    """Return Amazon product health metrics from catalog data."""
    rows = db.execute(
        select(SocialMention).where(
            SocialMention.platform == "amazon",
        ).order_by(desc(SocialMention.updated_at))
    ).scalars().all()

    products = []
    bsr_values = []
    prices = []

    for row in rows:
        meta = row.metadata_json or {}
        asin = meta.get("asin", row.external_id.replace("product:", ""))
        bsr = meta.get("bsr")
        competitive_price = meta.get("competitive_price")
        listed_price = meta.get("listed_price")

        product: dict[str, Any] = {
            "asin": asin,
            "title": row.title,
            "source_url": row.source_url,
            "brand": meta.get("brand", row.author),
            "bsr": bsr,
            "bsr_category": meta.get("bsr_category"),
            "competitive_price": competitive_price,
            "listed_price": listed_price,
            "image_url": meta.get("image_url"),
            "last_updated": row.updated_at.isoformat() if row.updated_at else None,
        }
        products.append(product)

        if bsr and isinstance(bsr, (int, float)):
            bsr_values.append(int(bsr))
        if competitive_price and isinstance(competitive_price, (int, float)):
            prices.append(float(competitive_price))

    avg_bsr = round(sum(bsr_values) / len(bsr_values)) if bsr_values else None
    best_bsr = min(bsr_values) if bsr_values else None
    avg_price = round(sum(prices) / len(prices), 2) if prices else None
    price_range = {"min": min(prices), "max": max(prices)} if prices else None

    return {
        "total_products": len(products),
        "products": products,
        "avg_bsr": avg_bsr,
        "best_bsr": best_bsr,
        "avg_price": avg_price,
        "price_range": price_range,
    }


def get_industry_trends(db: Session, days: int = 30) -> dict[str, Any]:
    """Return charcoal grilling industry trends from Reddit data."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(
        select(SocialMention).where(
            SocialMention.published_at >= cutoff,
            SocialMention.platform == "reddit",
            SocialMention.classification == "industry_trend",
        )
    ).scalars().all()

    subreddit_counter: Counter[str] = Counter()
    topic_counter: Counter[str] = Counter()
    topic_engagement: defaultdict[str, int] = defaultdict(int)
    competitor_counter: Counter[str] = Counter()

    for row in rows:
        if row.subreddit:
            subreddit_counter[row.subreddit] += 1
        if row.trend_topic:
            topic_counter[row.trend_topic] += 1
            topic_engagement[row.trend_topic] += row.engagement_score
        if row.competitor_mentioned:
            competitor_counter[row.competitor_mentioned] += 1

    hot_topics = [
        {
            "topic": topic,
            "mention_count": count,
            "total_engagement": topic_engagement[topic],
        }
        for topic, count in topic_counter.most_common(15)
    ]

    # Most-discussed posts
    top_posts = sorted(rows, key=lambda r: r.engagement_score, reverse=True)[:10]
    top_posts_out = [
        {
            "title": p.title,
            "subreddit": p.subreddit,
            "source_url": p.source_url,
            "engagement_score": p.engagement_score,
            "comment_count": p.comment_count,
            "trend_topic": p.trend_topic,
            "published_at": p.published_at.isoformat() if p.published_at else None,
        }
        for p in top_posts
    ]

    return {
        "period_days": days,
        "total_industry_posts": len(rows),
        "hot_topics": hot_topics,
        "by_subreddit": dict(subreddit_counter.most_common()),
        "competitor_share_of_voice": dict(competitor_counter.most_common()),
        "top_posts": top_posts_out,
    }


def get_market_intelligence(db: Session, days: int = 30) -> dict[str, Any]:
    """Return market intelligence: competitive landscape, purchase intent,
    product innovation signals, trend momentum, and positioning opportunities."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(
        select(SocialMention).where(SocialMention.published_at >= cutoff)
    ).scalars().all()

    # ── Competitive Landscape ──
    competitor_mentions: Counter[str] = Counter()
    competitor_sentiment: defaultdict[str, list[float]] = defaultdict(list)
    competitor_engagement: defaultdict[str, int] = defaultdict(int)
    brand_mention_count = 0
    brand_engagement = 0

    # ── Purchase Intent ──
    purchase_intent_posts: list[dict[str, Any]] = []

    # ── Product Innovation ──
    innovation_posts: list[dict[str, Any]] = []

    # ── Competitor Pain Points (opportunity) ──
    competitor_pain_points: list[dict[str, Any]] = []

    # ── Trend Momentum ──
    topic_counter: Counter[str] = Counter()
    topic_engagement: defaultdict[str, int] = defaultdict(int)
    topic_platforms: defaultdict[str, set[str]] = defaultdict(set)

    # ── Platform Coverage ──
    platform_counter: Counter[str] = Counter()
    classification_counter: Counter[str] = Counter()

    # ── Amazon Competitive Pricing ──
    our_products: list[dict[str, Any]] = []
    competitor_products: list[dict[str, Any]] = []

    for row in rows:
        platform_counter[row.platform] += 1
        classification_counter[row.classification] += 1
        meta = row.metadata_json or {}
        market_signals = meta.get("market_signals", [])

        # Brand vs competitor tracking
        if row.brand_mentioned:
            brand_mention_count += 1
            brand_engagement += row.engagement_score
        if row.competitor_mentioned:
            competitor_mentions[row.competitor_mentioned] += 1
            competitor_sentiment[row.competitor_mentioned].append(row.sentiment_score)
            competitor_engagement[row.competitor_mentioned] += row.engagement_score

        # Purchase intent posts
        if row.classification == "purchase_intent" or "purchase_intent" in market_signals:
            purchase_intent_posts.append({
                "title": row.title,
                "body": (row.body or "")[:200],
                "platform": row.platform,
                "source_url": row.source_url,
                "engagement_score": row.engagement_score,
                "comment_count": row.comment_count,
                "competitor_mentioned": row.competitor_mentioned,
                "product_mentioned": row.product_mentioned,
                "published_at": row.published_at.isoformat() if row.published_at else None,
            })

        # Product innovation signals
        if row.classification == "product_innovation" or "product_innovation" in market_signals:
            innovation_posts.append({
                "title": row.title,
                "body": (row.body or "")[:300],
                "platform": row.platform,
                "source_url": row.source_url,
                "engagement_score": row.engagement_score,
                "comment_count": row.comment_count,
                "trend_topic": row.trend_topic,
                "published_at": row.published_at.isoformat() if row.published_at else None,
            })

        # Competitor pain points — negative competitor reviews/complaints
        if ("competitor_pain_point" in market_signals
                or "competitor_weakness" in market_signals
                or row.classification in ("competitor_complaint",)):
            competitor_pain_points.append({
                "title": row.title,
                "body": (row.body or "")[:200],
                "platform": row.platform,
                "source_url": row.source_url,
                "competitor": row.competitor_mentioned,
                "sentiment_score": row.sentiment_score,
                "engagement_score": row.engagement_score,
                "published_at": row.published_at.isoformat() if row.published_at else None,
            })

        # Trend topic tracking
        if row.trend_topic:
            topic_counter[row.trend_topic] += 1
            topic_engagement[row.trend_topic] += row.engagement_score
            topic_platforms[row.trend_topic].add(row.platform)

        # Amazon product positioning
        if row.platform == "amazon":
            data_type = meta.get("data_type", "")
            product_entry = {
                "asin": meta.get("asin"),
                "title": row.title,
                "bsr": meta.get("bsr"),
                "bsr_category": meta.get("bsr_category"),
                "competitive_price": meta.get("competitive_price"),
                "brand": meta.get("brand", row.author),
            }
            if data_type == "product_catalog" or row.classification == "product_listing":
                our_products.append(product_entry)
            elif data_type == "competitor_product" or row.classification == "competitor_product":
                competitor_products.append(product_entry)

    # ── Build competitive landscape ──
    total_voice = brand_mention_count + sum(competitor_mentions.values())
    brand_share_of_voice = round(brand_mention_count / total_voice, 3) if total_voice > 0 else 0

    competitor_landscape = []
    for comp, count in competitor_mentions.most_common(15):
        scores = competitor_sentiment[comp]
        avg_sent = round(sum(scores) / len(scores), 3) if scores else 0.0
        competitor_landscape.append({
            "competitor": comp,
            "mentions": count,
            "share_of_voice": round(count / total_voice, 3) if total_voice > 0 else 0,
            "avg_sentiment": avg_sent,
            "total_engagement": competitor_engagement[comp],
            "sentiment_label": "positive" if avg_sent > 0.2 else "negative" if avg_sent < -0.2 else "neutral",
        })

    # ── Build trend momentum (cross-platform trends are stronger signals) ──
    trending_topics = []
    for topic, count in topic_counter.most_common(20):
        platforms = list(topic_platforms[topic])
        trending_topics.append({
            "topic": topic,
            "mentions": count,
            "total_engagement": topic_engagement[topic],
            "platforms": platforms,
            "cross_platform": len(platforms) > 1,
            "momentum": "strong" if count > 5 and len(platforms) > 1 else "growing" if count > 2 else "emerging",
        })

    # ── Amazon price positioning ──
    our_prices = [p["competitive_price"] for p in our_products if p.get("competitive_price")]
    comp_prices = [p["competitive_price"] for p in competitor_products if p.get("competitive_price")]
    our_bsrs = [p["bsr"] for p in our_products if p.get("bsr")]
    comp_bsrs = [p["bsr"] for p in competitor_products if p.get("bsr")]

    price_positioning = None
    if our_prices and comp_prices:
        our_avg = round(sum(our_prices) / len(our_prices), 2)
        comp_avg = round(sum(comp_prices) / len(comp_prices), 2)
        price_positioning = {
            "our_avg_price": our_avg,
            "competitor_avg_price": comp_avg,
            "price_delta_pct": round((our_avg - comp_avg) / comp_avg * 100, 1) if comp_avg > 0 else 0,
            "position": "premium" if our_avg > comp_avg * 1.1 else "competitive" if our_avg > comp_avg * 0.9 else "value",
        }

    bsr_positioning = None
    if our_bsrs and comp_bsrs:
        our_best = min(our_bsrs)
        comp_best = min(comp_bsrs)
        bsr_positioning = {
            "our_best_bsr": our_best,
            "competitor_best_bsr": comp_best,
            "our_product_count": len(our_products),
            "competitor_product_count": len(competitor_products),
            "outranking_competitors": our_best < comp_best,
        }

    # Sort by engagement (most-discussed first)
    purchase_intent_posts.sort(key=lambda p: p["engagement_score"], reverse=True)
    innovation_posts.sort(key=lambda p: p["engagement_score"], reverse=True)
    competitor_pain_points.sort(key=lambda p: p["engagement_score"], reverse=True)

    return {
        "period_days": days,
        "total_mentions": len(rows),
        "by_platform": dict(platform_counter.most_common()),
        "by_classification": dict(classification_counter.most_common()),
        "competitive_landscape": {
            "brand_mentions": brand_mention_count,
            "brand_engagement": brand_engagement,
            "brand_share_of_voice": brand_share_of_voice,
            "competitors": competitor_landscape,
        },
        "purchase_intent": {
            "total": len(purchase_intent_posts),
            "posts": purchase_intent_posts[:15],
        },
        "product_innovation": {
            "total": len(innovation_posts),
            "posts": innovation_posts[:15],
        },
        "competitor_pain_points": {
            "total": len(competitor_pain_points),
            "posts": competitor_pain_points[:15],
        },
        "trend_momentum": trending_topics,
        "amazon_positioning": {
            "price": price_positioning,
            "bsr": bsr_positioning,
            "our_products": len(our_products),
            "competitor_products": len(competitor_products),
        },
    }
