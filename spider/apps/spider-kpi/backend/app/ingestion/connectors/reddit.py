"""Reddit social listening connector.

Fetches brand mentions and industry trends from Reddit's public JSON API
and upserts them into the social_mentions table.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import SocialMention
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
RATE_LIMIT_DELAY = 1.2  # Reddit OAuth allows ~60 req/min
USER_AGENT = "SpiderGrillsKPI/1.0 (by /u/spidergrills)"

# OAuth2 token cache
_oauth_token: str | None = None
_oauth_expires: float = 0

BRAND_QUERIES = [
    "spider grills",
    "spider grill",
    "venom grill",
    "venom controller",
    "huntsman grill",
    "giant huntsman",
]

MONITORED_SUBREDDITS = [
    "smoking",
    "grilling",
    "BBQ",
    "charcoalgrilling",
    "pelletgrills",
    "kamado",
    "webergrills",
    "Traeger",
]

# ── Classification helpers ──────────────────────────────────────────

BRAND_PATTERNS = [
    re.compile(r"\bspider\s*grill", re.IGNORECASE),
    re.compile(r"\bspider\s*grills", re.IGNORECASE),
    re.compile(r"\bvenom\s*controller", re.IGNORECASE),
    re.compile(r"\bvenom\s*grill", re.IGNORECASE),
    re.compile(r"\bhuntsman\s*grill", re.IGNORECASE),
    re.compile(r"\bgiant\s*huntsman", re.IGNORECASE),
]

PRODUCT_MAP = [
    (re.compile(r"\bvenom", re.IGNORECASE), "venom"),
    (re.compile(r"\bgiant\s*huntsman", re.IGNORECASE), "giant_huntsman"),
    (re.compile(r"\bhuntsman", re.IGNORECASE), "huntsman"),
]

COMPETITOR_MAP = [
    (re.compile(r"\btraeger", re.IGNORECASE), "traeger"),
    (re.compile(r"\bweber\b", re.IGNORECASE), "weber"),
    (re.compile(r"\bkamado\s*joe", re.IGNORECASE), "kamado_joe"),
    (re.compile(r"\bbig\s*green\s*egg|\bbge\b", re.IGNORECASE), "big_green_egg"),
    (re.compile(r"\brec\s*tec", re.IGNORECASE), "rec_tec"),
    (re.compile(r"\bcamp\s*chef", re.IGNORECASE), "camp_chef"),
    (re.compile(r"\bpit\s*boss", re.IGNORECASE), "pit_boss"),
    (re.compile(r"\boklahoma\s*joe", re.IGNORECASE), "oklahoma_joe"),
    (re.compile(r"\bchar-?griller", re.IGNORECASE), "char_griller"),
    (re.compile(r"\bmasterbuilt", re.IGNORECASE), "masterbuilt"),
    (re.compile(r"\bgravity\s*series", re.IGNORECASE), "masterbuilt"),
    (re.compile(r"\blouisiana\s*grills?", re.IGNORECASE), "louisiana_grills"),
    (re.compile(r"\bdyna-?glo", re.IGNORECASE), "dyna_glo"),
    (re.compile(r"\byoder\b", re.IGNORECASE), "yoder"),
    (re.compile(r"\bblaze\s*grill", re.IGNORECASE), "blaze"),
    (re.compile(r"\bflameboss", re.IGNORECASE), "flameboss"),
    (re.compile(r"\bfireboard", re.IGNORECASE), "fireboard"),
    (re.compile(r"\bbbq\s*guru", re.IGNORECASE), "bbq_guru"),
]

POSITIVE_WORDS = {"love", "amazing", "best", "great", "perfect", "recommend", "awesome", "excellent", "fantastic", "impressed"}
NEGATIVE_WORDS = {"problem", "issue", "broke", "terrible", "waste", "disappointed", "returned", "awful", "horrible", "defective", "worst", "regret"}

QUESTION_PATTERNS = [
    re.compile(r"\?"),
    re.compile(r"\banyone\s+(know|tried|used|have)\b", re.IGNORECASE),
    re.compile(r"\bshould\s+i\b", re.IGNORECASE),
    re.compile(r"\brecommend", re.IGNORECASE),
    re.compile(r"\badvice\b", re.IGNORECASE),
    re.compile(r"\bwhich\s+(grill|smoker|controller)\b", re.IGNORECASE),
]

COMPLAINT_PATTERNS = [
    re.compile(r"\bwarranty\b", re.IGNORECASE),
    re.compile(r"\brefund\b", re.IGNORECASE),
    re.compile(r"\breturned?\b", re.IGNORECASE),
    re.compile(r"\bcustomer\s+service\b", re.IGNORECASE),
    re.compile(r"\bterrible\b", re.IGNORECASE),
    re.compile(r"\bdisappointed\b", re.IGNORECASE),
]

REVIEW_PATTERNS = [
    re.compile(r"\breview\b", re.IGNORECASE),
    re.compile(r"\bunboxing\b", re.IGNORECASE),
    re.compile(r"\bfirst\s+impression", re.IGNORECASE),
    re.compile(r"\bmonths?\s+(in|later|with)\b", re.IGNORECASE),
    re.compile(r"\bupdate\b.*\b(after|month|week)", re.IGNORECASE),
]

PURCHASE_INTENT_PATTERNS = [
    re.compile(r"\b(thinking\s+(about|of)\s+(buying|getting|purchasing))\b", re.IGNORECASE),
    re.compile(r"\b(looking\s+(for|to\s+buy|at\s+buying))\b", re.IGNORECASE),
    re.compile(r"\b(deciding\s+between)\b", re.IGNORECASE),
    re.compile(r"\bwhich\s+(should\s+i|one|grill|smoker)\b", re.IGNORECASE),
    re.compile(r"\b(help\s+me\s+(choose|decide|pick))\b", re.IGNORECASE),
    re.compile(r"\b(vs\.?|versus)\b", re.IGNORECASE),
    re.compile(r"\bbest\s+(charcoal\s+)?(grill|smoker|controller)\s+(for|under)\b", re.IGNORECASE),
    re.compile(r"\b(worth\s+(it|the\s+(money|price|investment)))\b", re.IGNORECASE),
    re.compile(r"\b(upgrade|upgrading)\s+(from|to|my)\b", re.IGNORECASE),
    re.compile(r"\bfirst\s+(grill|smoker|charcoal)\b", re.IGNORECASE),
]

PRODUCT_INNOVATION_PATTERNS = [
    re.compile(r"\bi\s+wish\s+(my|the|a)\b", re.IGNORECASE),
    re.compile(r"\bwould\s+be\s+(nice|great|awesome|cool)\s+(if|to)\b", re.IGNORECASE),
    re.compile(r"\bwhy\s+(doesn.t|don.t|can.t|isn.t)\b.*\bgrill", re.IGNORECASE),
    re.compile(r"\b(need|want)\s+a\s+(grill|smoker|controller)\s+(that|with|which)\b", re.IGNORECASE),
    re.compile(r"\bmissing\s+feature", re.IGNORECASE),
    re.compile(r"\bif\s+only\b", re.IGNORECASE),
    re.compile(r"\b(dream|ideal|perfect)\s+(grill|smoker|setup|controller)\b", re.IGNORECASE),
    re.compile(r"\bfeature\s+request", re.IGNORECASE),
]


def _score_sentiment(text: str) -> tuple[str, float]:
    """Keyword-based sentiment scoring.  Returns (label, score) where score is -1.0 to 1.0."""
    words = set(re.findall(r"\b\w+\b", text.lower()))
    pos = len(words & POSITIVE_WORDS)
    neg = len(words & NEGATIVE_WORDS)
    total = pos + neg
    if total == 0:
        return "neutral", 0.0
    score = (pos - neg) / total
    if score > 0.25:
        label = "positive"
    elif score < -0.25:
        label = "negative"
    elif pos > 0 and neg > 0:
        label = "mixed"
    else:
        label = "neutral"
    return label, round(score, 3)


def _detect_product(text: str) -> str | None:
    for pattern, product_name in PRODUCT_MAP:
        if pattern.search(text):
            return product_name
    return None


def _detect_competitor(text: str) -> str | None:
    for pattern, competitor_name in COMPETITOR_MAP:
        if pattern.search(text):
            return competitor_name
    return None


def _is_brand_mention(text: str) -> bool:
    return any(p.search(text) for p in BRAND_PATTERNS)


def classify_mention(title: str, body: str) -> dict[str, Any]:
    """Classify a social mention (Reddit post, YouTube video, etc.).

    Returns a dict with classification, sentiment, relevance_score, brand_mentioned,
    product_mentioned, competitor_mentioned, trend_topic, and market_signals.
    """
    combined = f"{title} {body}"

    brand = _is_brand_mention(combined)
    product = _detect_product(combined)
    competitor = _detect_competitor(combined)
    sentiment_label, sentiment_score = _score_sentiment(combined)

    is_purchase_intent = any(p.search(combined) for p in PURCHASE_INTENT_PATTERNS)
    is_product_innovation = any(p.search(combined) for p in PRODUCT_INNOVATION_PATTERNS)
    is_question = any(p.search(combined) for p in QUESTION_PATTERNS)
    is_complaint = any(p.search(combined) for p in COMPLAINT_PATTERNS) and sentiment_score < 0
    is_review = any(p.search(combined) for p in REVIEW_PATTERNS)

    # Classification priority
    classification = "industry_trend"  # default for subreddit monitoring
    if brand:
        if is_complaint:
            classification = "complaint"
        elif is_review:
            classification = "product_review"
        elif is_purchase_intent:
            classification = "purchase_intent"
        elif is_question:
            classification = "customer_question"
        else:
            classification = "brand_mention"
    elif is_purchase_intent:
        classification = "purchase_intent"
    elif is_product_innovation:
        classification = "product_innovation"
    elif competitor:
        if is_complaint:
            classification = "competitor_complaint"
        elif is_review:
            classification = "competitor_review"
        elif is_question:
            classification = "customer_question"
        else:
            classification = "competitor_mention"
    elif is_question:
        classification = "customer_question"

    # Relevance score: 0-1 based on how directly the post relates to Spider Grills
    relevance = 0.1  # baseline for monitored subreddits
    if brand:
        relevance = 0.9
        if product:
            relevance = 1.0
    elif is_purchase_intent:
        relevance = 0.6
    elif is_product_innovation:
        relevance = 0.5
    elif competitor:
        relevance = 0.4
        if is_complaint:
            relevance = 0.5  # competitor pain points are valuable
    elif is_question:
        relevance = 0.3

    # Trend topic extraction — broad industry coverage
    trend_topic = None
    trend_keywords = [
        ("temperature control", r"\btemp(erature)?\s*(control|management|regulation|controller)\b"),
        ("pellet vs charcoal", r"\bpellet\b.*\bcharcoal\b|\bcharcoal\b.*\bpellet\b"),
        ("wifi connectivity", r"\bwi-?fi\b|\bbluetooth\b|\bapp\b.*\b(connect|grill|control)\b"),
        ("smart grilling", r"\bsmart\s*(grill|smoker|cook)\b|\b(iot|connected)\s*grill\b"),
        ("smoking", r"\bsmoking\b|\bsmoke\b.*\b(ring|flavor|wood)\b"),
        ("low and slow", r"\blow\s*and\s*slow\b"),
        ("reverse sear", r"\breverse\s*sear\b"),
        ("brisket", r"\bbrisket\b"),
        ("ribs", r"\bribs\b"),
        ("pulled pork", r"\bpulled\s*pork\b|\bpork\s*(butt|shoulder)\b"),
        ("kamado cooking", r"\bkamado\b.*\b(cook|bake|smoke|grill)\b"),
        ("charcoal types", r"\b(lump|briquette|binchotan)\s*(charcoal|coal)\b|\bcharcoal\s*(type|brand|quality)\b"),
        ("fire management", r"\b(fire|airflow|vent|damper)\s*(management|control|adjust)\b"),
        ("grill accessories", r"\b(accessori|gadget|attachment|upgrade)\b.*\b(grill|smoker)\b"),
        ("competition bbq", r"\bcompetition\s*(bbq|barbecue|cook)\b|\b(kcbs|ibca)\b"),
        ("outdoor kitchen", r"\boutdoor\s*kitchen\b|\bbuilt-?in\s*grill\b"),
        ("fuel efficiency", r"\b(fuel|charcoal)\s*(usage|efficiency|consumption|cost)\b"),
        ("grill maintenance", r"\b(clean|maint|rust|season)\b.*\b(grill|grate|smoker)\b"),
        ("ceramic grills", r"\bceramic\s*(grill|smoker|cooker)\b"),
        ("portable grilling", r"\bportable\s*(grill|smoker)\b|\b(travel|camping)\s*grill\b"),
    ]
    for topic_name, topic_pattern in trend_keywords:
        if re.search(topic_pattern, combined, re.IGNORECASE):
            trend_topic = topic_name
            break

    # Market signal tags for intelligence layer
    market_signals = []
    if is_purchase_intent:
        market_signals.append("purchase_intent")
    if is_product_innovation:
        market_signals.append("product_innovation")
    if competitor and is_complaint:
        market_signals.append("competitor_pain_point")
    if competitor and is_review and sentiment_score < -0.2:
        market_signals.append("competitor_weakness")
    if competitor and is_review and sentiment_score > 0.2:
        market_signals.append("competitor_strength")

    return {
        "classification": classification,
        "sentiment": sentiment_label,
        "sentiment_score": sentiment_score,
        "brand_mentioned": brand,
        "product_mentioned": product,
        "competitor_mentioned": competitor,
        "relevance_score": round(relevance, 2),
        "trend_topic": trend_topic,
        "market_signals": market_signals,
    }


# ── Reddit OAuth2 + API helpers ────────────────────────────────────

def _get_oauth_token() -> str | None:
    """Get Reddit OAuth2 bearer token using 'script' app type (read-only, no user context)."""
    global _oauth_token, _oauth_expires
    if _oauth_token and time.time() < _oauth_expires:
        return _oauth_token
    client_id = settings.reddit_client_id
    client_secret = settings.reddit_client_secret
    if not client_id or not client_secret:
        logger.warning("reddit OAuth credentials not configured (REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET)")
        return None
    try:
        resp = requests.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(client_id, client_secret),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT_SECONDS,
        )
        if resp.status_code != 200:
            logger.warning("reddit oauth failed: %d %s", resp.status_code, resp.text[:200])
            return None
        data = resp.json()
        _oauth_token = data.get("access_token")
        _oauth_expires = time.time() + data.get("expires_in", 3600) - 60
        logger.info("reddit oauth token acquired, expires in %ds", data.get("expires_in", 0))
        return _oauth_token
    except requests.RequestException as exc:
        logger.warning("reddit oauth request failed: %s", exc)
        return None


def _reddit_headers() -> dict[str, str]:
    token = _get_oauth_token()
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _api_base() -> str:
    """Use oauth.reddit.com when we have a token, else fallback to www.reddit.com."""
    return "https://oauth.reddit.com" if _get_oauth_token() else "https://www.reddit.com"


def _reddit_get(url: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Make a rate-limited GET request to Reddit's OAuth API."""
    time.sleep(RATE_LIMIT_DELAY)
    try:
        resp = requests.get(url, headers=_reddit_headers(), params=params, timeout=TIMEOUT_SECONDS)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 10))
            logger.warning("reddit rate limited, sleeping %ds", retry_after)
            time.sleep(retry_after)
            resp = requests.get(url, headers=_reddit_headers(), params=params, timeout=TIMEOUT_SECONDS)
        if resp.status_code == 401:
            global _oauth_token
            _oauth_token = None
            logger.warning("reddit oauth token expired, will refresh on next call")
            return None
        if resp.status_code != 200:
            logger.warning("reddit api returned %d for %s", resp.status_code, url)
            return None
        return resp.json()
    except requests.RequestException as exc:
        logger.warning("reddit request failed: %s", exc)
        return None


def _search_reddit(query: str, subreddit: str | None = None, limit: int = 25) -> list[dict[str, Any]]:
    """Search Reddit for posts matching *query*."""
    if subreddit:
        url = f"{_api_base()}/r/{subreddit}/search.json"
    else:
        url = f"{_api_base()}/search.json"
    params: dict[str, Any] = {"q": query, "sort": "new", "limit": limit, "restrict_sr": "on" if subreddit else "off", "t": "week"}
    data = _reddit_get(url, params)
    if not data or "data" not in data:
        return []
    return data["data"].get("children", [])


def _hot_posts(subreddit: str, limit: int = 25) -> list[dict[str, Any]]:
    """Get hot posts from a subreddit."""
    url = f"{_api_base()}/r/{subreddit}/hot.json"
    data = _reddit_get(url, {"limit": limit})
    if not data or "data" not in data:
        return []
    return data["data"].get("children", [])


def _post_to_dict(child: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a Reddit listing child into a flat dict."""
    post = child.get("data")
    if not post:
        return None
    created_utc = post.get("created_utc")
    published_at = datetime.fromtimestamp(created_utc, tz=timezone.utc) if created_utc else None
    return {
        "external_id": post.get("id") or post.get("name", ""),
        "title": post.get("title", ""),
        "body": post.get("selftext", ""),
        "author": post.get("author"),
        "subreddit": post.get("subreddit"),
        "source_url": f"https://www.reddit.com{post.get('permalink', '')}",
        "engagement_score": int(post.get("score", 0)),
        "comment_count": int(post.get("num_comments", 0)),
        "published_at": published_at,
    }


# ── Main sync function ─────────────────────────────────────────────

def sync_reddit(db: Session, lookback_hours: int = 48) -> dict[str, Any]:
    """Sync Reddit posts into social_mentions.

    Returns a status dict compatible with the standard connector interface.
    """
    started = time.monotonic()

    upsert_source_config(
        db,
        "reddit",
        configured=settings.reddit_enabled,
        enabled=settings.reddit_enabled,
        sync_mode="poll",
        config_json={
            "source_type": "connector",
            "lookback_hours": lookback_hours,
            "subreddits": MONITORED_SUBREDDITS,
        },
    )
    db.commit()

    if not settings.reddit_enabled:
        return {"ok": False, "message": "Reddit connector disabled", "records_processed": 0}

    run = start_sync_run(db, "reddit", "poll_recent", {"lookback_hours": lookback_hours})
    db.commit()

    stats: dict[str, Any] = {
        "records_fetched": 0,
        "inserted": 0,
        "updated": 0,
    }

    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

    try:
        all_posts: dict[str, dict[str, Any]] = {}  # keyed by external_id for dedup

        # 1) Brand-mention search (global search)
        for query in BRAND_QUERIES:
            children = _search_reddit(query, subreddit=None, limit=25)
            stats["records_fetched"] += len(children)
            for child in children:
                post = _post_to_dict(child)
                if post and post["external_id"] not in all_posts:
                    if post["published_at"] and post["published_at"] >= cutoff:
                        all_posts[post["external_id"]] = post

        # 2) Brand-mention search per subreddit
        for sub in MONITORED_SUBREDDITS:
            for query in BRAND_QUERIES[:3]:  # top 3 queries per sub to limit API calls
                children = _search_reddit(query, subreddit=sub, limit=10)
                stats["records_fetched"] += len(children)
                for child in children:
                    post = _post_to_dict(child)
                    if post and post["external_id"] not in all_posts:
                        if post["published_at"] and post["published_at"] >= cutoff:
                            all_posts[post["external_id"]] = post

        # 3) Hot/trending posts from monitored subreddits (industry trend analysis)
        for sub in MONITORED_SUBREDDITS:
            children = _hot_posts(sub, limit=25)
            stats["records_fetched"] += len(children)
            for child in children:
                post = _post_to_dict(child)
                if post and post["external_id"] not in all_posts:
                    if post["published_at"] and post["published_at"] >= cutoff:
                        all_posts[post["external_id"]] = post

        # 4) Upsert into social_mentions
        for ext_id, post in all_posts.items():
            classification = classify_mention(post["title"], post["body"])

            existing = db.execute(
                select(SocialMention).where(
                    SocialMention.platform == "reddit",
                    SocialMention.external_id == ext_id,
                )
            ).scalars().first()

            metadata = {
                "source_query": "brand_search" if classification["brand_mentioned"] else "subreddit_monitor",
                "market_signals": classification.get("market_signals", []),
            }

            if existing is None:
                mention = SocialMention(
                    platform="reddit",
                    external_id=ext_id,
                    source_url=post["source_url"],
                    title=post["title"],
                    body=post["body"],
                    author=post["author"],
                    subreddit=post["subreddit"],
                    engagement_score=post["engagement_score"],
                    comment_count=post["comment_count"],
                    sentiment=classification["sentiment"],
                    sentiment_score=classification["sentiment_score"],
                    classification=classification["classification"],
                    brand_mentioned=classification["brand_mentioned"],
                    product_mentioned=classification["product_mentioned"],
                    competitor_mentioned=classification["competitor_mentioned"],
                    trend_topic=classification["trend_topic"],
                    relevance_score=classification["relevance_score"],
                    published_at=post["published_at"],
                    metadata_json=metadata,
                )
                db.add(mention)
                stats["inserted"] += 1
            else:
                # Update engagement metrics (they change over time)
                existing.engagement_score = post["engagement_score"]
                existing.comment_count = post["comment_count"]
                existing.sentiment = classification["sentiment"]
                existing.sentiment_score = classification["sentiment_score"]
                existing.classification = classification["classification"]
                existing.brand_mentioned = classification["brand_mentioned"]
                existing.product_mentioned = classification["product_mentioned"]
                existing.competitor_mentioned = classification["competitor_mentioned"]
                existing.trend_topic = classification["trend_topic"]
                existing.relevance_score = classification["relevance_score"]
                existing.metadata_json = {**(existing.metadata_json or {}), **metadata}
                stats["updated"] += 1

        duration_ms = int((time.monotonic() - started) * 1000)
        run.metadata_json = {**(run.metadata_json or {}), **stats, "duration_ms": duration_ms}
        finish_sync_run(db, run, status="success", records_processed=stats["inserted"] + stats["updated"])
        db.commit()

        logger.info("reddit sync complete", extra={"stats": stats, "duration_ms": duration_ms})
        return {"ok": True, "records_processed": stats["inserted"] + stats["updated"], **stats, "duration_ms": duration_ms}

    except Exception as exc:
        db.rollback()
        run = db.merge(run)
        duration_ms = int((time.monotonic() - started) * 1000)
        run.metadata_json = {**(run.metadata_json or {}), **stats, "duration_ms": duration_ms}
        finish_sync_run(db, run, status="failed", error_message=str(exc))
        db.commit()
        logger.exception("reddit sync failed")
        return {"ok": False, "message": str(exc), "records_processed": 0, **stats, "duration_ms": duration_ms}
