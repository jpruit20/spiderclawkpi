"""Auto-deploy pipeline for AI-edited files.

After the AI edits dashboard files, this module:
1. Validates only allowed files were modified
2. Git adds + commits with attribution
3. Git pushes to trigger Vercel auto-deploy
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from app.services.ai_scoping import UserScope, resolve_safe_path, is_path_editable

logger = logging.getLogger(__name__)


@dataclass
class DeployResult:
    success: bool
    commit_sha: Optional[str] = None
    message: Optional[str] = None
    reverted_files: list[str] | None = None


async def _run(cmd: list[str], cwd: str) -> tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    return (
        proc.returncode or 0,
        stdout.decode("utf-8", errors="replace").strip(),
        stderr.decode("utf-8", errors="replace").strip(),
    )


async def validate_and_deploy(
    scope: UserScope,
    workspace_root: str,
    summary: str = "dashboard update",
) -> DeployResult:
    """Check which files changed, revert unauthorized edits, commit, and push.

    Returns a ``DeployResult`` with the outcome.
    """
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

    # 4. Stage authorized files
    rc, _, err = await _run(["git", "add"] + authorized, workspace_root)
    if rc != 0:
        return DeployResult(success=False, message=f"git add failed: {err}")

    # 5. Commit with attribution
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

    # 6. Push to trigger Vercel auto-deploy
    rc, _, err = await _run(
        ["git", "push", "origin", "HEAD"], workspace_root,
    )
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
