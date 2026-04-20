"""YouTube -> LoreEvent sync.

Distinct from ``youtube.py`` (which feeds ``social_mentions`` for
industry trend detection), this connector drives the *Lore Ledger*
institutional-memory timeline. Two streams:

1. **Own-channel uploads** (@SpiderGrills) — every upload with
   views > ``OWN_VIEW_FLOOR`` becomes a Lore event. These are
   press/marketing moments that belong in company history.
2. **Third-party mentions** — videos discovered by the existing
   ``youtube.py`` connector (stored in ``social_mentions``) where
   a third-party creator talks about Spider Grills products and
   the video has views > ``THIRD_PARTY_VIEW_FLOOR``. Ambassadors,
   unsolicited reviews, press pickups.

Dedup: LoreEvent rows carry ``source_refs_json->>'video_id'`` so
repeated syncs refresh stats rather than duplicating rows. Title
bumps (YouTube rarely permits this but it happens) still match.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import requests
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import LoreEvent, SocialMention
from app.services.source_health import finish_sync_run, start_sync_run, upsert_source_config

settings = get_settings()
logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 15
CHANNEL_HANDLE = "@SpiderGrills"

# View floors — Joseph 2026-04-19: Spider-Grills uploads from the
# early days sometimes sit around a few hundred views; > 1k keeps
# the timeline focused on videos that actually reached people.
# Third-party pickups need a higher floor because random grilling
# channels mentioning "spider grills" in passing shouldn't clutter
# lore with every 500-view drop.
OWN_VIEW_FLOOR = 1_000
THIRD_PARTY_VIEW_FLOOR = 10_000

SOURCE_TYPE = "youtube"


def _configured() -> bool:
    return bool(settings.youtube_api_key)


def _resolve_own_channel_id() -> tuple[str | None, str | None]:
    """Return (channel_id, uploads_playlist_id) for @SpiderGrills."""
    url = "https://www.googleapis.com/youtube/v3/channels"
    params = {
        "part": "contentDetails,snippet",
        "forHandle": CHANNEL_HANDLE,
        "key": settings.youtube_api_key,
    }
    try:
        resp = requests.get(url, params=params, timeout=TIMEOUT_SECONDS)
        if resp.status_code != 200:
            logger.warning("youtube channels.list %d: %s", resp.status_code, resp.text[:200])
            return (None, None)
        items = resp.json().get("items", [])
        if not items:
            return (None, None)
        ch = items[0]
        return (
            ch.get("id"),
            ch.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads"),
        )
    except requests.RequestException as exc:
        logger.warning("youtube channels.list failed: %s", exc)
        return (None, None)


def _list_playlist_video_ids(playlist_id: str, max_pages: int = 20) -> list[str]:
    """Walk a playlist's items (paginated). Cap at ``max_pages`` * 50."""
    url = "https://www.googleapis.com/youtube/v3/playlistItems"
    ids: list[str] = []
    page_token: str | None = None
    for _ in range(max_pages):
        params: dict[str, Any] = {
            "part": "contentDetails",
            "playlistId": playlist_id,
            "maxResults": 50,
            "key": settings.youtube_api_key,
        }
        if page_token:
            params["pageToken"] = page_token
        try:
            resp = requests.get(url, params=params, timeout=TIMEOUT_SECONDS)
            if resp.status_code != 200:
                logger.warning("youtube playlistItems %d: %s", resp.status_code, resp.text[:200])
                break
            data = resp.json()
        except requests.RequestException as exc:
            logger.warning("youtube playlistItems failed: %s", exc)
            break
        for it in data.get("items", []):
            vid = it.get("contentDetails", {}).get("videoId")
            if vid:
                ids.append(vid)
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return ids


def _fetch_videos_full(video_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch snippet+statistics for a list of video IDs in batches of 50."""
    out: dict[str, dict[str, Any]] = {}
    if not video_ids:
        return out
    url = "https://www.googleapis.com/youtube/v3/videos"
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i : i + 50]
        params = {
            "part": "snippet,statistics",
            "id": ",".join(batch),
            "key": settings.youtube_api_key,
        }
        try:
            resp = requests.get(url, params=params, timeout=TIMEOUT_SECONDS)
            if resp.status_code != 200:
                logger.warning("youtube videos.list %d: %s", resp.status_code, resp.text[:200])
                continue
            for item in resp.json().get("items", []):
                vid = item.get("id")
                if vid:
                    out[vid] = item
        except requests.RequestException as exc:
            logger.warning("youtube videos.list failed: %s", exc)
    return out


def _upsert_lore_event(
    db: Session,
    *,
    video_id: str,
    title: str,
    description: str,
    published_at: datetime,
    views: int,
    likes: int,
    channel_title: str,
    channel_type: str,  # "own" | "third_party"
    search_query: str | None = None,
) -> str:
    """Insert or update a LoreEvent keyed on source_refs_json->>'video_id'.

    Returns ``"inserted"`` or ``"updated"``.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    existing = db.execute(
        select(LoreEvent).where(
            and_(
                LoreEvent.source_type == SOURCE_TYPE,
                LoreEvent.source_refs_json["video_id"].astext == video_id,
            )
        )
    ).scalars().first()

    # Cap the title so it fits the 256-char column. Trim description
    # hard since it's just a teaser — the external URL is the truth.
    trimmed_title = (title or f"YouTube video {video_id}")[:256]
    blurb = (description or "").strip().split("\n")[0][:400]

    source_refs = {
        "platform": "youtube",
        "video_id": video_id,
        "url": url,
        "channel_title": channel_title,
        "channel_type": channel_type,
        "views": views,
        "likes": likes,
        "search_query": search_query,
    }

    if existing is None:
        ev = LoreEvent(
            event_type="press" if channel_type == "third_party" else "launch",
            title=trimmed_title,
            description=blurb or None,
            start_date=published_at.date(),
            division="marketing",
            confidence="confirmed",
            source_type=SOURCE_TYPE,
            source_refs_json=source_refs,
            metadata_json={
                "auto_created": True,
                "source": "youtube_lore_sync",
            },
            created_by="youtube_lore_sync",
        )
        db.add(ev)
        return "inserted"

    # Refresh live stats but don't touch human edits to title/description.
    existing.source_refs_json = {**(existing.source_refs_json or {}), **source_refs}
    existing.metadata_json = {
        **(existing.metadata_json or {}),
        "last_stats_refresh": datetime.now(timezone.utc).isoformat(),
    }
    return "updated"


def _published_dt(item: dict[str, Any]) -> datetime | None:
    raw = (item.get("snippet") or {}).get("publishedAt") or ""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def sync_youtube_lore(db: Session) -> dict[str, Any]:
    """Two-pass sync: own-channel uploads + eligible third-party mentions."""
    started = time.monotonic()
    source_name = "youtube_lore"

    configured = _configured()
    upsert_source_config(
        db,
        source_name,
        configured=configured,
        enabled=configured,
        sync_mode="poll",
        config_json={"source_type": "connector"},
    )
    db.commit()

    if not configured:
        return {"ok": False, "message": "YouTube API key not configured", "records_processed": 0}

    run = start_sync_run(db, source_name, "poll_channel_and_mentions", {})
    db.commit()

    stats = {
        "own_videos_scanned": 0,
        "own_inserted": 0,
        "own_updated": 0,
        "own_skipped_below_floor": 0,
        "third_party_scanned": 0,
        "third_party_inserted": 0,
        "third_party_updated": 0,
        "third_party_skipped_below_floor": 0,
    }

    try:
        # ── Pass 1: own-channel uploads ────────────────────────────
        _, uploads_playlist_id = _resolve_own_channel_id()
        if uploads_playlist_id:
            own_ids = _list_playlist_video_ids(uploads_playlist_id)
            own_full = _fetch_videos_full(own_ids)
            stats["own_videos_scanned"] = len(own_full)
            for vid, item in own_full.items():
                snippet = item.get("snippet", {})
                statistics = item.get("statistics", {})
                views = int(statistics.get("viewCount", 0) or 0)
                likes = int(statistics.get("likeCount", 0) or 0)
                if views < OWN_VIEW_FLOOR:
                    stats["own_skipped_below_floor"] += 1
                    continue
                published_at = _published_dt(item)
                if not published_at:
                    continue
                outcome = _upsert_lore_event(
                    db,
                    video_id=vid,
                    title=snippet.get("title", ""),
                    description=snippet.get("description", ""),
                    published_at=published_at,
                    views=views,
                    likes=likes,
                    channel_title=snippet.get("channelTitle", "Spider Grills"),
                    channel_type="own",
                )
                if outcome == "inserted":
                    stats["own_inserted"] += 1
                else:
                    stats["own_updated"] += 1
            db.commit()
        else:
            logger.warning("youtube_lore: could not resolve uploads playlist for %s", CHANNEL_HANDLE)

        # ── Pass 2: third-party videos from social_mentions ────────
        # The existing youtube.py connector already filtered by brand
        # keywords; we only need to apply the higher view floor and
        # exclude anything that actually came from the Spider Grills
        # channel (caught in Pass 1).
        mentions = db.execute(
            select(SocialMention).where(
                and_(
                    SocialMention.platform == "youtube",
                    SocialMention.engagement_score >= THIRD_PARTY_VIEW_FLOOR,
                    SocialMention.brand_mentioned.is_(True),
                )
            )
        ).scalars().all()
        stats["third_party_scanned"] = len(mentions)
        for m in mentions:
            author = (m.author or "").lower()
            if "spider grills" in author or "spidergrills" in author:
                # Own channel — already handled in Pass 1.
                continue
            if m.engagement_score < THIRD_PARTY_VIEW_FLOOR:
                stats["third_party_skipped_below_floor"] += 1
                continue
            published_at = m.published_at or datetime.now(timezone.utc)
            # Normalize to UTC-aware for .date() safety.
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=timezone.utc)
            md = m.metadata_json or {}
            outcome = _upsert_lore_event(
                db,
                video_id=m.external_id,
                title=m.title or "",
                description=m.body or "",
                published_at=published_at,
                views=int(m.engagement_score or 0),
                likes=int(md.get("like_count", 0) or 0),
                channel_title=m.author or "",
                channel_type="third_party",
                search_query=md.get("search_query"),
            )
            if outcome == "inserted":
                stats["third_party_inserted"] += 1
            else:
                stats["third_party_updated"] += 1
        db.commit()

        duration_ms = int((time.monotonic() - started) * 1000)
        processed = (
            stats["own_inserted"] + stats["own_updated"]
            + stats["third_party_inserted"] + stats["third_party_updated"]
        )
        run.metadata_json = {**(run.metadata_json or {}), **stats, "duration_ms": duration_ms}
        finish_sync_run(db, run, status="success", records_processed=processed)
        db.commit()
        logger.info("youtube_lore sync complete", extra={"stats": stats, "duration_ms": duration_ms})
        return {"ok": True, "records_processed": processed, **stats, "duration_ms": duration_ms}

    except Exception as exc:
        db.rollback()
        run = db.merge(run)
        duration_ms = int((time.monotonic() - started) * 1000)
        run.metadata_json = {**(run.metadata_json or {}), **stats, "duration_ms": duration_ms}
        finish_sync_run(db, run, status="failed", error_message=str(exc))
        db.commit()
        logger.exception("youtube_lore sync failed")
        return {"ok": False, "message": str(exc), "records_processed": 0, **stats, "duration_ms": duration_ms}
