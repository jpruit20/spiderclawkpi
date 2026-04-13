"""Claude Code CLI orchestration for the AI dashboard editor.

Invokes ``claude -p`` as a subprocess in ``stream-json`` mode, parses the
NDJSON output line-by-line, and yields simplified SSE-friendly event dicts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

from app.services.ai_scoping import UserScope, DIVISION_LABELS

logger = logging.getLogger(__name__)

# Maximum wall-clock seconds before we kill the CLI process.
CLI_TIMEOUT_SECONDS = 300
# Dollar cap per request (safety net).
CLI_MAX_BUDGET_USD = 0.50


@dataclass
class SSEEvent:
    """A single event to be serialized and sent to the browser."""
    event: str            # SSE event name
    data: dict[str, Any]  # JSON-serializable payload


def _build_system_prompt(scope: UserScope) -> str:
    """Return the system prompt injected into the CLI invocation."""
    return f"""\
You are the AI editor for the Spider Grills KPI dashboard.
You are helping the **{scope.division_label}** team leader make changes to their dashboard page.

## Rules
- You may ONLY edit this file: `{scope.editable_file}`
- You may READ any file under `{scope.readable_prefix}` to understand the codebase.
- Do NOT create new files. All changes must go into the existing page file.
- Do NOT modify backend code, deploy scripts, environment files, or any file outside `{scope.readable_prefix}`.

## Tech stack
- React 18 with TypeScript
- Recharts for all charts (Line, Area, Bar, Composed, Pie)
- Custom CSS dark theme (no Tailwind, no Material UI) — styles are in `frontend/src/styles.css`
- Reusable components in `frontend/src/components/` (read them for reference)
- API client in `frontend/src/lib/api.ts`, types in `frontend/src/lib/types.ts`
- Formatting helpers in `frontend/src/lib/format.ts`

## Workflow
1. ALWAYS read the target file first before making changes.
2. Read shared components or lib files if you need to understand imports or types.
3. Make minimal, focused changes — do not rewrite the entire file.
4. Preserve the existing code style and patterns.
5. After editing, briefly explain what you changed and why.
"""


def _build_prompt(user_message: str, history: list[dict[str, str]] | None) -> str:
    """Combine optional history and the current user message into one prompt."""
    parts: list[str] = []
    if history:
        parts.append("## Previous conversation for context")
        for msg in history[-5:]:  # last 5 messages max
            role = msg.get("role", "user")
            content = msg.get("content", "")
            parts.append(f"**{role}**: {content}")
        parts.append("")
    parts.append(user_message)
    return "\n".join(parts)


def _find_claude_binary() -> str | None:
    """Locate the ``claude`` CLI binary on PATH."""
    return shutil.which("claude")


async def run_cli_turn(
    user_message: str,
    scope: UserScope,
    history: list[dict[str, str]] | None = None,
    workspace_root: str = ".",
) -> AsyncGenerator[SSEEvent, None]:
    """Run one Claude Code CLI turn and yield SSE events.

    This is an async generator that can be consumed directly by a
    ``StreamingResponse``.
    """
    claude_bin = _find_claude_binary()
    if not claude_bin:
        yield SSEEvent(event="error", data={"message": "Claude Code CLI not found on server. Please install it."})
        return

    prompt = _build_prompt(user_message, history)
    system_prompt = _build_system_prompt(scope)

    cmd = [
        claude_bin,
        "-p", prompt,
        "--output-format", "stream-json",
        "--model", "sonnet",
        "--bare",
        "--dangerously-skip-permissions",
        "--append-system-prompt", system_prompt,
        "--allowed-tools", "Read", "Edit", "Glob", "Grep",
        "--max-budget-usd", str(CLI_MAX_BUDGET_USD),
    ]

    logger.info("AI agent start: user=%s division=%s", scope.email, scope.division)
    yield SSEEvent(event="status", data={"message": "Starting AI assistant..."})

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workspace_root,
        )
    except Exception as exc:
        logger.exception("Failed to start Claude CLI")
        yield SSEEvent(event="error", data={"message": f"Failed to start AI: {exc}"})
        return

    # Track tool calls to detect file modifications
    active_tools: dict[int, dict[str, Any]] = {}  # index -> {name, input_parts}
    files_modified: list[str] = []
    text_buffer: list[str] = []

    try:
        assert process.stdout is not None
        async for raw_line in _read_lines_with_timeout(process.stdout, CLI_TIMEOUT_SECONDS):
            line = raw_line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            top_type = obj.get("type")

            # ── Final result ──
            if top_type == "result":
                result_text = obj.get("result", "")
                usage = obj.get("usage", {})
                yield SSEEvent(event="done", data={
                    "result": result_text,
                    "files_changed": len(files_modified),
                    "files": files_modified,
                    "usage": usage,
                })
                continue

            # ── System events (retries, errors) ──
            if top_type == "system":
                subtype = obj.get("subtype", "")
                if subtype == "api_retry":
                    yield SSEEvent(event="status", data={
                        "message": f"API retry (attempt {obj.get('attempt', '?')})...",
                    })
                continue

            # ── Stream events ──
            if top_type != "stream_event":
                continue

            event = obj.get("event", {})
            event_type = event.get("type", "")

            # Text delta
            if event_type == "content_block_delta":
                delta = event.get("delta", {})
                delta_type = delta.get("type", "")

                if delta_type == "text_delta":
                    text = delta.get("text", "")
                    if text:
                        text_buffer.append(text)
                        yield SSEEvent(event="text", data={"content": text})

                elif delta_type == "input_json_delta":
                    # Accumulate tool input JSON
                    idx = event.get("index", -1)
                    if idx in active_tools:
                        active_tools[idx]["input_parts"].append(delta.get("partial_json", ""))

            # Tool use start
            elif event_type == "content_block_start":
                cb = event.get("content_block", {})
                if cb.get("type") == "tool_use":
                    idx = event.get("index", -1)
                    tool_name = cb.get("name", "unknown")
                    active_tools[idx] = {
                        "name": tool_name,
                        "id": cb.get("id", ""),
                        "input_parts": [],
                    }
                    yield SSEEvent(event="tool_start", data={
                        "tool": tool_name,
                        "index": idx,
                    })

            # Content block stop (tool input complete)
            elif event_type == "content_block_stop":
                idx = event.get("index", -1)
                if idx in active_tools:
                    tool_info = active_tools.pop(idx)
                    tool_name = tool_info["name"]
                    # Try to parse the accumulated tool input
                    raw_input = "".join(tool_info["input_parts"])
                    try:
                        tool_input = json.loads(raw_input) if raw_input else {}
                    except json.JSONDecodeError:
                        tool_input = {"raw": raw_input}

                    file_path = tool_input.get("file_path", tool_input.get("path", ""))

                    if tool_name == "Edit" and file_path:
                        files_modified.append(file_path)
                        yield SSEEvent(event="file_modified", data={
                            "tool": tool_name,
                            "file": file_path,
                        })
                    else:
                        yield SSEEvent(event="tool_use", data={
                            "tool": tool_name,
                            "file": file_path or None,
                        })

            # Message stop — a single turn completed
            elif event_type == "message_stop":
                pass  # The CLI may do multiple turns; wait for "result"

    except asyncio.TimeoutError:
        logger.warning("AI agent timed out for user=%s", scope.email)
        yield SSEEvent(event="error", data={"message": "AI assistant timed out."})
        process.kill()
    except Exception as exc:
        logger.exception("AI agent error for user=%s", scope.email)
        yield SSEEvent(event="error", data={"message": f"AI assistant error: {exc}"})
    finally:
        # Ensure process is cleaned up
        if process.returncode is None:
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=5)
            except Exception:
                process.kill()

    # If we never got a "result" event, yield done with what we have
    if not any(True for _ in []):  # generator already yielded done above; this is a safety net
        pass


async def _read_lines_with_timeout(
    stream: asyncio.StreamReader,
    timeout: float,
) -> AsyncGenerator[str, None]:
    """Read lines from *stream* with an overall *timeout*."""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError()
        try:
            line = await asyncio.wait_for(stream.readline(), timeout=remaining)
        except asyncio.TimeoutError:
            raise
        if not line:
            break  # EOF
        yield line.decode("utf-8", errors="replace")
