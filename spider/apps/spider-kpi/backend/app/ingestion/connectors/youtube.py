"""YouTube social listening connector.

Uses the YouTube Data API v3 search endpoint to discover brand-related videos
and upserts them into the social_mentions table.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import SocialMention
from app.ingestion.connectors.reddit import classify_mention
from app.services.source_health import finish_sync_run, start_sync_run, upsert_source_config

settings = get_settings()
logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.INFO)
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    logger.addHandler(stream_handler)

TIMEOUT_SECONDS = 15

BRAND_QUERIES = [
    "spider grills",
    "venom grill controller",
    "huntsman grill",
]

INDUSTRY_QUERIES = [
    "charcoal grill review",
    "best charcoal grill 2026",
    "kamado grill review",
    "grill temperature controller",
    "charcoal vs pellet grill",
    "smart grill technology",
    "charcoal smoker review",
]

SEARCH_QUERIES = BRAND_QUERIES + INDUSTRY_QUERIES


def _configured() -> bool:
    return bool(settings.youtube_api_key)


def _is_latin_text(text: str) -> bool:
    """Return True if the majority of the text uses Latin-script characters.

    This is a lightweight heuristic to filter out non-English comments
    (Russian, Arabic, CJK, etc.) without requiring a heavy NLP library.
    """
    if not text:
        return True
    latin_count = sum(1 for ch in text if ch.isascii() or '\u00C0' <= ch <= '\u024F')
    return latin_count / len(text) > 0.6


def _search_youtube(query: str, published_after: str, max_results: int = 25) -> list[dict[str, Any]]:
    """Search YouTube Data API v3 for videos matching *query*."""
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "order": "date",
        "maxResults": max_results,
        "publishedAfter": published_after,
        "relevanceLanguage": "en",
        "regionCode": "US",
        "key": settings.youtube_api_key,
    }
    try:
        resp = requests.get(url, params=params, timeout=TIMEOUT_SECONDS)
        if resp.status_code != 200:
            logger.warning("youtube search returned %d: %s", resp.status_code, resp.text[:200])
            return []
        return resp.json().get("items", [])
    except requests.RequestException as exc:
        logger.warning("youtube request failed: %s", exc)
        return []


def _get_video_stats(video_ids: list[str]) -> dict[str, dict[str, int]]:
    """Fetch view and comment counts for a batch of video IDs."""
    if not video_ids:
        return {}
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {
        "part": "statistics,contentDetails",
        "id": ",".join(video_ids),
        "key": settings.youtube_api_key,
    }
    try:
        resp = requests.get(url, params=params, timeout=TIMEOUT_SECONDS)
        if resp.status_code != 200:
            return {}
        result: dict[str, dict[str, int]] = {}
        for item in resp.json().get("items", []):
            stats = item.get("statistics", {})
            result[item["id"]] = {
                "view_count": int(stats.get("viewCount", 0)),
                "comment_count": int(stats.get("commentCount", 0)),
                "like_count": int(stats.get("likeCount", 0)),
            }
        return result
    except requests.RequestException as exc:
        logger.warning("youtube stats request failed: %s", exc)
        return {}


def _get_video_comments(video_id: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Fetch top comment threads for a video, sorted by relevance."""
    url = "https://www.googleapis.com/youtube/v3/commentThreads"
    params = {
        "part": "snippet",
        "videoId": video_id,
        "maxResults": max_results,
        "order": "relevance",
        "textFormat": "plainText",
        "key": settings.youtube_api_key,
    }
    try:
        resp = requests.get(url, params=params, timeout=TIMEOUT_SECONDS)
        if resp.status_code == 403:
            # Comments may be disabled on this video
            return []
        if resp.status_code != 200:
            return []
        comments = []
        for item in resp.json().get("items", []):
            snippet = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
            text = (snippet.get("textDisplay", "") or "")[:300]
            # Skip non-Latin comments (Russian, Arabic, CJK, etc.)
            if not _is_latin_text(text):
                continue
            comments.append({
                "author": snippet.get("authorDisplayName", ""),
                "text": text,
                "likes": int(snippet.get("likeCount", 0)),
                "published_at": snippet.get("publishedAt"),
            })
        return comments
    except requests.RequestException as exc:
        logger.warning("youtube comments request for %s failed: %s", video_id, exc)
        return []


def sync_youtube(db: Session, lookback_hours: int = 168) -> dict[str, Any]:
    """Sync YouTube videos into social_mentions.

    Default lookback is 168 hours (7 days).
    """
    started = time.monotonic()

    configured = _configured()
    upsert_source_config(
        db,
        "youtube",
        configured=configured,
        enabled=configured,
        sync_mode="poll",
        config_json={"source_type": "connector"},
    )
    db.commit()

    if not configured:
        return {"ok": False, "message": "YouTube API key not configured (YOUTUBE_API_KEY)", "records_processed": 0}

    run = start_sync_run(db, "youtube", "poll_recent", {"lookback_hours": lookback_hours})
    db.commit()

    stats: dict[str, Any] = {
        "records_fetched": 0,
        "inserted": 0,
        "updated": 0,
    }

    published_after = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        all_videos: dict[str, dict[str, Any]] = {}

        for query in SEARCH_QUERIES:
            is_brand_query = query in BRAND_QUERIES
            items = _search_youtube(query, published_after, max_results=25 if is_brand_query else 15)
            stats["records_fetched"] += len(items)
            for item in items:
                video_id = item.get("id", {}).get("videoId")
                if not video_id or video_id in all_videos:
                    continue
                snippet = item.get("snippet", {})
                published_at_str = snippet.get("publishedAt", "")
                published_at = None
                if published_at_str:
                    try:
                        published_at = datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))
                    except ValueError:
                        pass
                title = snippet.get("title", "")
                # Skip non-English videos (Cyrillic, CJK, Arabic, etc.)
                if not _is_latin_text(title):
                    continue
                all_videos[video_id] = {
                    "external_id": video_id,
                    "title": title,
                    "body": snippet.get("description", ""),
                    "author": snippet.get("channelTitle", ""),
                    "source_url": f"https://www.youtube.com/watch?v={video_id}",
                    "published_at": published_at,
                    "search_query": query,
                    "search_type": "brand" if is_brand_query else "industry",
                }

        # Fetch stats in batch
        video_ids = list(all_videos.keys())
        video_stats = _get_video_stats(video_ids)

        # Fetch top comments for the 10 most-engaged videos
        top_video_ids = sorted(video_stats.keys(), key=lambda vid: video_stats[vid].get("view_count", 0), reverse=True)[:10]
        video_comments: dict[str, list[dict[str, Any]]] = {}
        for vid in top_video_ids:
            comments = _get_video_comments(vid, max_results=5)
            if comments:
                video_comments[vid] = comments
        stats["videos_with_comments"] = len(video_comments)

        for video_id, video in all_videos.items():
            vs = video_stats.get(video_id, {})
            video["engagement_score"] = vs.get("view_count", 0)
            video["comment_count"] = vs.get("comment_count", 0)
            video["like_count"] = vs.get("like_count", 0)

            classification = classify_mention(video["title"], video["body"])

            # Calculate engagement rate
            views = video["engagement_score"]
            likes = video["like_count"]
            engagement_rate = round(likes / views * 100, 2) if views > 0 else 0.0

            metadata = {
                "like_count": video["like_count"],
                "engagement_rate": engagement_rate,
                "search_query": video.get("search_query", ""),
                "search_type": video.get("search_type", "brand"),
                "market_signals": classification.get("market_signals", []),
            }
            if video_id in video_comments:
                metadata["top_comments"] = video_comments[video_id]

            existing = db.execute(
                select(SocialMention).where(
                    SocialMention.platform == "youtube",
                    SocialMention.external_id == video_id,
                )
            ).scalars().first()

            if existing is None:
                mention = SocialMention(
                    platform="youtube",
                    external_id=video_id,
                    source_url=video["source_url"],
                    title=video["title"],
                    body=video["body"],
                    author=video["author"],
                    engagement_score=video["engagement_score"],
                    comment_count=video["comment_count"],
                    sentiment=classification["sentiment"],
                    sentiment_score=classification["sentiment_score"],
                    classification=classification["classification"],
                    brand_mentioned=classification["brand_mentioned"],
                    product_mentioned=classification["product_mentioned"],
                    competitor_mentioned=classification["competitor_mentioned"],
                    trend_topic=classification["trend_topic"],
                    relevance_score=classification["relevance_score"],
                    published_at=video["published_at"],
                    metadata_json=metadata,
                )
                db.add(mention)
                stats["inserted"] += 1
            else:
                existing.engagement_score = video["engagement_score"]
                existing.comment_count = video["comment_count"]
                existing.sentiment = classification["sentiment"]
                existing.sentiment_score = classification["sentiment_score"]
                existing.classification = classification["classification"]
                existing.relevance_score = classification["relevance_score"]
                existing.metadata_json = {**(existing.metadata_json or {}), **metadata}
                stats["updated"] += 1

        duration_ms = int((time.monotonic() - started) * 1000)
        run.metadata_json = {**(run.metadata_json or {}), **stats, "duration_ms": duration_ms}
        finish_sync_run(db, run, status="success", records_processed=stats["inserted"] + stats["updated"])
        db.commit()

        logger.info("youtube sync complete", extra={"stats": stats, "duration_ms": duration_ms})
        return {"ok": True, "records_processed": stats["inserted"] + stats["updated"], **stats, "duration_ms": duration_ms}

    except Exception as exc:
        db.rollback()
        run = db.merge(run)
        duration_ms = int((time.monotonic() - started) * 1000)
        run.metadata_json = {**(run.metadata_json or {}), **stats, "duration_ms": duration_ms}
        finish_sync_run(db, run, status="failed", error_message=str(exc))
        db.commit()
        logger.exception("youtube sync failed")
        return {"ok": False, "message": str(exc), "records_processed": 0, **stats, "duration_ms": duration_ms}
