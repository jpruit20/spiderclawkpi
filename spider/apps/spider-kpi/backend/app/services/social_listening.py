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
