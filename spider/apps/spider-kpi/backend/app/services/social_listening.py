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
