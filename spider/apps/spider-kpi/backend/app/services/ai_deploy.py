"""Auto-deploy pipeline for AI-edited files.

After the AI edits dashboard files, this module:
1. Validates only allowed files were modified
2. Git adds + commits with attribution
3. Git pushes to trigger Vercel auto-deploy

Push authentication uses GITHUB_TOKEN from the environment (the same token
used by the GitHub issues integration).  The token is injected into the
remote URL for the push so no persistent credential helper is needed.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Optional

from app.services.ai_scoping import UserScope, is_path_editable

logger = logging.getLogger(__name__)


@dataclass
class DeployResult:
    success: bool
    commit_sha: Optional[str] = None
    message: Optional[str] = None
    reverted_files: list[str] | None = None


async def _run(cmd: list[str], cwd: str, timeout: int = 30) -> tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    return (
        proc.returncode or 0,
        stdout.decode("utf-8", errors="replace").strip(),
        stderr.decode("utf-8", errors="replace").strip(),
    )


async def _get_authenticated_remote(workspace_root: str) -> Optional[str]:
    """Inject the GITHUB_TOKEN into the existing origin remote URL.

    Reads the current ``origin`` remote from git, then replaces the host
    portion with ``x-access-token:<token>@github.com``.  Returns ``None``
    if the token is not configured or the remote isn't HTTPS GitHub.
    """
    from app.core.config import get_settings
    settings = get_settings()
    token = settings.github_token
    if not token:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        return None
    # Read the actual remote URL from git
    rc, remote_url, _ = await _run(
        ["git", "config", "--get", "remote.origin.url"], workspace_root,
    )
    if rc != 0 or "github.com" not in remote_url:
        return None
    # https://github.com/owner/repo.git → https://x-access-token:<token>@github.com/owner/repo.git
    if remote_url.startswith("https://github.com/"):
        return remote_url.replace("https://github.com/", f"https://x-access-token:{token}@github.com/")
    if remote_url.startswith("https://") and "github.com" in remote_url:
        # Already has credentials embedded — replace them
        import re
        return re.sub(r'https://[^@]*@github\.com/', f'https://x-access-token:{token}@github.com/', remote_url)
    return None


async def validate_and_deploy(
    scope: UserScope,
    workspace_root: str,
    summary: str = "dashboard update",
) -> DeployResult:
    """Check which files changed, revert unauthorized edits, commit, and push."""

    # 1. Check what files actually changed on disk
    rc, diff_output, _ = await _run(
        ["git", "diff", "--name-only"], workspace_root,
    )
    if rc != 0:
        return DeployResult(success=False, message="git diff failed")

    changed = [f for f in diff_output.splitlines() if f.strip()]
    if not changed:
        return DeployResult(success=False, message="No files were modified")

    # 2. Split into authorized and unauthorized changes
    authorized: list[str] = []
    unauthorized: list[str] = []
    for rel_path in changed:
        if is_path_editable(scope, rel_path):
            authorized.append(rel_path)
        else:
            unauthorized.append(rel_path)

    # 3. Revert unauthorized changes
    reverted: list[str] = []
    if unauthorized:
        for upath in unauthorized:
            rc, _, err = await _run(
                ["git", "checkout", "--", upath], workspace_root,
            )
            if rc == 0:
                reverted.append(upath)
            else:
                logger.warning("Failed to revert %s: %s", upath, err)
        logger.warning(
            "Reverted %d unauthorized file(s) for user=%s: %s",
            len(reverted), scope.email, reverted,
        )

    if not authorized:
        return DeployResult(
            success=False,
            message="No authorized file changes to deploy",
            reverted_files=reverted,
        )

    # 4. Ensure git user is configured (needed for commits on the droplet)
    await _run(["git", "config", "user.email", "kpi-ai@spidergrills.com"], workspace_root)
    await _run(["git", "config", "user.name", "Spider KPI AI"], workspace_root)

    # 5. Stage authorized files
    rc, _, err = await _run(["git", "add"] + authorized, workspace_root)
    if rc != 0:
        return DeployResult(success=False, message=f"git add failed: {err}")

    # 6. Commit with attribution
    short_summary = summary[:80] if len(summary) > 80 else summary
    commit_msg = f"AI edit: {short_summary} (by {scope.email})"
    rc, _, err = await _run(
        ["git", "commit", "-m", commit_msg],
        workspace_root,
    )
    if rc != 0:
        return DeployResult(success=False, message=f"git commit failed: {err}")

    # Get the commit SHA
    rc, sha, _ = await _run(
        ["git", "rev-parse", "--short", "HEAD"], workspace_root,
    )

    # 7. Push — use token-authenticated URL if available, else try default remote
    auth_remote = await _get_authenticated_remote(workspace_root)
    if auth_remote:
        push_cmd = ["git", "push", auth_remote, "HEAD:refs/heads/master"]
    else:
        push_cmd = ["git", "push", "origin", "HEAD"]

    rc, _, err = await _run(push_cmd, workspace_root, timeout=60)
    if rc != 0:
        logger.error("git push failed: %s", err)
        return DeployResult(
            success=True,
            commit_sha=sha,
            message=f"Committed ({sha}) but push failed: {err}. Deploy manually.",
            reverted_files=reverted or None,
        )

    logger.info("AI deploy: commit=%s files=%s user=%s", sha, authorized, scope.email)
    return DeployResult(
        success=True,
        commit_sha=sha,
        message=f"Deployed ({sha}). Vercel will auto-build.",
        reverted_files=reverted or None,
    )
