"""Google Reviews social listening connector.

Uses the Google Places API to fetch reviews for the Spider Grills business
and upserts them into the social_mentions table.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
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


def _configured() -> bool:
    return bool(settings.google_places_api_key and settings.google_places_id)


def _find_place_id() -> str | None:
    """Look up the Spider Grills place ID if not already configured."""
    if settings.google_places_id:
        return settings.google_places_id

    url = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
    params = {
        "input": "Spider Grills",
        "inputtype": "textquery",
        "fields": "place_id",
        "key": settings.google_places_api_key,
    }
    try:
        resp = requests.get(url, params=params, timeout=TIMEOUT_SECONDS)
        if resp.status_code != 200:
            return None
        candidates = resp.json().get("candidates", [])
        if candidates:
            return candidates[0].get("place_id")
    except requests.RequestException as exc:
        logger.warning("google places findplace failed: %s", exc)
    return None


def _fetch_reviews(place_id: str) -> list[dict[str, Any]]:
    """Fetch reviews for a given place ID."""
    url = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {
        "place_id": place_id,
        "fields": "reviews",
        "key": settings.google_places_api_key,
    }
    try:
        resp = requests.get(url, params=params, timeout=TIMEOUT_SECONDS)
        if resp.status_code != 200:
            logger.warning("google places details returned %d", resp.status_code)
            return []
        result = resp.json().get("result", {})
        return result.get("reviews", [])
    except requests.RequestException as exc:
        logger.warning("google places request failed: %s", exc)
        return []


def sync_google_reviews(db: Session) -> dict[str, Any]:
    """Sync Google Reviews into social_mentions."""
    started = time.monotonic()

    configured = _configured()
    upsert_source_config(
        db,
        "google_reviews",
        configured=configured,
        enabled=configured,
        sync_mode="poll",
        config_json={"source_type": "connector"},
    )
    db.commit()

    if not configured:
        return {"ok": False, "message": "Google Places API not configured (GOOGLE_PLACES_API_KEY + GOOGLE_PLACES_ID)", "records_processed": 0}

    run = start_sync_run(db, "google_reviews", "poll_recent", {})
    db.commit()

    stats: dict[str, Any] = {
        "records_fetched": 0,
        "inserted": 0,
        "updated": 0,
    }

    try:
        place_id = _find_place_id()
        if not place_id:
            raise RuntimeError("Could not resolve Google Places ID for Spider Grills")

        reviews = _fetch_reviews(place_id)
        stats["records_fetched"] = len(reviews)

        for review in reviews:
            author_name = review.get("author_name", "anonymous")
            review_text = review.get("text", "")
            rating = review.get("rating", 0)
            review_time = review.get("time")  # Unix timestamp
            # Create a stable external_id from author + time
            ext_id = f"gr_{author_name}_{review_time}"

            published_at = datetime.fromtimestamp(review_time, tz=timezone.utc) if review_time else None

            classification = classify_mention("", review_text)

            # Override sentiment based on star rating for Google Reviews
            if rating >= 4:
                sentiment = "positive"
                sentiment_score = (rating - 3) / 2.0  # 4 -> 0.5, 5 -> 1.0
            elif rating <= 2:
                sentiment = "negative"
                sentiment_score = (rating - 3) / 2.0  # 2 -> -0.5, 1 -> -1.0
            else:
                sentiment = "neutral"
                sentiment_score = 0.0

            existing = db.execute(
                select(SocialMention).where(
                    SocialMention.platform == "google_reviews",
                    SocialMention.external_id == ext_id,
                )
            ).scalars().first()

            if existing is None:
                mention = SocialMention(
                    platform="google_reviews",
                    external_id=ext_id,
                    source_url=review.get("author_url"),
                    title=f"{rating}-star review by {author_name}",
                    body=review_text,
                    author=author_name,
                    engagement_score=rating,
                    sentiment=sentiment,
                    sentiment_score=round(sentiment_score, 3),
                    classification="product_review",
                    brand_mentioned=True,
                    product_mentioned=classification.get("product_mentioned"),
                    relevance_score=1.0,
                    published_at=published_at,
                    metadata_json={
                        "rating": rating,
                        "language": review.get("language"),
                        "relative_time_description": review.get("relative_time_description"),
                    },
                )
                db.add(mention)
                stats["inserted"] += 1
            else:
                existing.body = review_text
                existing.engagement_score = rating
                existing.sentiment = sentiment
                existing.sentiment_score = round(sentiment_score, 3)
                stats["updated"] += 1

        duration_ms = int((time.monotonic() - started) * 1000)
        run.metadata_json = {**(run.metadata_json or {}), **stats, "duration_ms": duration_ms}
        finish_sync_run(db, run, status="success", records_processed=stats["inserted"] + stats["updated"])
        db.commit()

        logger.info("google_reviews sync complete", extra={"stats": stats, "duration_ms": duration_ms})
        return {"ok": True, "records_processed": stats["inserted"] + stats["updated"], **stats, "duration_ms": duration_ms}

    except Exception as exc:
        db.rollback()
        run = db.merge(run)
        duration_ms = int((time.monotonic() - started) * 1000)
        run.metadata_json = {**(run.metadata_json or {}), **stats, "duration_ms": duration_ms}
        finish_sync_run(db, run, status="failed", error_message=str(exc))
        db.commit()
        logger.exception("google_reviews sync failed")
        return {"ok": False, "message": str(exc), "records_processed": 0, **stats, "duration_ms": duration_ms}
