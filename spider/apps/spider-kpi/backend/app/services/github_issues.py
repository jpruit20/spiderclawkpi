"""
GitHub Issues service for fetching P0/P1 engineering issues.
"""
import logging
from datetime import datetime, timezone
from typing import Optional
import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


def fetch_engineering_issues(labels: Optional[list[str]] = None, state: str = "open", per_page: int = 20) -> dict:
    """
    Fetch engineering issues from GitHub with optional label filtering.

    Args:
        labels: List of labels to filter by (e.g., ["bug", "P0", "P1"])
        state: Issue state ("open", "closed", "all")
        per_page: Number of issues to fetch

    Returns:
        Dict with issues list and metadata
    """
    settings = get_settings()

    if not settings.github_token:
        logger.warning("GITHUB_TOKEN not configured - returning empty issues list")
        return {
            "issues": [],
            "total_count": 0,
            "configured": False,
            "error": "GitHub integration not configured"
        }

    owner = settings.github_owner
    repo = settings.github_repo

    headers = {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    # Build query params
    params = {
        "state": state,
        "per_page": per_page,
        "sort": "updated",
        "direction": "desc"
    }

    if labels:
        params["labels"] = ",".join(labels)

    try:
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues"
        logger.info(f"Fetching GitHub issues from {owner}/{repo}")

        with httpx.Client(timeout=15.0) as client:
            response = client.get(url, headers=headers, params=params)
            response.raise_for_status()

            raw_issues = response.json()

            # Filter out pull requests (GitHub API returns PRs as issues)
            issues = [
                {
                    "id": issue["id"],
                    "number": issue["number"],
                    "title": issue["title"],
                    "state": issue["state"],
                    "html_url": issue["html_url"],
                    "labels": [label["name"] for label in issue.get("labels", [])],
                    "created_at": issue["created_at"],
                    "updated_at": issue["updated_at"],
                    "user": issue["user"]["login"] if issue.get("user") else None,
                    "assignees": [a["login"] for a in issue.get("assignees", [])],
                    "priority": _extract_priority(issue.get("labels", [])),
                    "is_bug": any(label["name"].lower() == "bug" for label in issue.get("labels", [])),
                }
                for issue in raw_issues
                if "pull_request" not in issue  # Filter out PRs
            ]

            return {
                "issues": issues,
                "total_count": len(issues),
                "configured": True,
                "repo": f"{owner}/{repo}",
                "fetched_at": datetime.now(timezone.utc).isoformat()
            }

    except httpx.HTTPStatusError as e:
        logger.error(f"GitHub API error: {e.response.status_code} - {e.response.text}")
        return {
            "issues": [],
            "total_count": 0,
            "configured": True,
            "error": f"GitHub API error: {e.response.status_code}"
        }
    except Exception as e:
        logger.error(f"Failed to fetch GitHub issues: {e}")
        return {
            "issues": [],
            "total_count": 0,
            "configured": True,
            "error": str(e)
        }


def _extract_priority(labels: list[dict]) -> Optional[str]:
    """Extract priority from labels (P0, P1, P2, critical, etc.)"""
    label_names = [label["name"].lower() for label in labels]

    if "p0" in label_names or "critical" in label_names:
        return "P0"
    elif "p1" in label_names or "high" in label_names:
        return "P1"
    elif "p2" in label_names or "medium" in label_names:
        return "P2"
    elif "p3" in label_names or "low" in label_names:
        return "P3"

    return None


def get_p0_p1_issues() -> dict:
    """Get open engineering issues, prioritized by severity.

    Fetches all open issues (not just bugs), assigns priority from labels,
    and returns them sorted: P0 first, then P1, then bugs, then the rest.
    """
    result = fetch_engineering_issues(labels=None, state="open", per_page=50)

    if result.get("issues"):
        PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        issues = result["issues"]
        # Sort: P0/P1 first, then bugs, then by updated_at
        issues.sort(key=lambda i: (
            PRIORITY_ORDER.get(i.get("priority") or "", 99),
            0 if i.get("is_bug") else 1,
            i.get("updated_at", ""),
        ))
        result["issues"] = issues[:15]
        result["total_count"] = len(issues)

    return result
