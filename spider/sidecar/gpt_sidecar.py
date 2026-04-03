import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv
from openai import OpenAI

SIDECAR_FILE_ROOT = Path(__file__).resolve().parent
load_dotenv(SIDECAR_FILE_ROOT / ".env")

WORKSPACE_ROOT = Path(os.getenv("WORKSPACE_ROOT", "/home/jpruit20/.openclaw/workspace/spider")).resolve()
TARGET_REPO = Path(os.getenv("TARGET_REPO", str(WORKSPACE_ROOT))).resolve()
SIDECAR_ROOT = WORKSPACE_ROOT / "sidecar"
INBOX = SIDECAR_ROOT / "inbox"
OUTBOX = SIDECAR_ROOT / "outbox"
LOCK_FILE = SIDECAR_ROOT / ".sidecar.lock"
MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4")
MAX_FILE_CHARS = int(os.getenv("MAX_FILE_CHARS", "12000"))
POLL_SECONDS = float(os.getenv("POLL_SECONDS", "2"))
MAX_CONTEXT_FILES = int(os.getenv("MAX_CONTEXT_FILES", "6"))

WATCH_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".md", ".sql", ".yaml", ".yml"}
IGNORE_DIR_NAMES = {
    ".git",
    "node_modules",
    ".next",
    "dist",
    "build",
    ".turbo",
    ".venv",
    "venv",
    "__pycache__",
    "coverage",
    "out",
}
IGNORE_PATHS = {
    SIDECAR_ROOT.resolve(),
}

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def acquire_lock() -> None:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            existing_pid = LOCK_FILE.read_text(encoding="utf-8").strip()
        except Exception:
            existing_pid = "unknown"
        print(f"[sidecar] lock exists; another instance may be running (pid={existing_pid})")
        sys.exit(1)

    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))


def release_lock() -> None:
    try:
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()
    except Exception:
        pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dirs() -> None:
    INBOX.mkdir(parents=True, exist_ok=True)
    OUTBOX.mkdir(parents=True, exist_ok=True)


def is_ignored(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except FileNotFoundError:
        resolved = path

    if any(part in IGNORE_DIR_NAMES for part in resolved.parts):
        return True

    for ignored in IGNORE_PATHS:
        try:
            resolved.relative_to(ignored)
            return True
        except ValueError:
            pass

    return False


def iter_watch_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in WATCH_EXTS:
            continue
        if is_ignored(path):
            continue
        yield path


def read_text(path: Path, limit: int = MAX_FILE_CHARS) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception as exc:
        return f"[read error: {exc}]"


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE_ROOT))
    except Exception:
        return str(path)


def snapshot_files(root: Path) -> dict[str, float]:
    files: dict[str, float] = {}
    for path in iter_watch_files(root):
        try:
            files[str(path.resolve())] = path.stat().st_mtime
        except FileNotFoundError:
            continue
    return files


def gather_neighbor_context(changed_file: Path) -> str:
    siblings = []
    parent = changed_file.parent
    if parent.exists():
        for path in sorted(parent.iterdir()):
            if path == changed_file or not path.is_file():
                continue
            if path.suffix.lower() not in WATCH_EXTS or is_ignored(path):
                continue
            siblings.append(path)
            if len(siblings) >= MAX_CONTEXT_FILES:
                break

    if not siblings:
        return "No nearby context files collected."

    chunks = []
    for path in siblings:
        chunks.append(f"### {rel(path)}\n{read_text(path, limit=max(1500, MAX_FILE_CHARS // 4))}")
    return "\n\n".join(chunks)


def build_change_prompt(changed_file: Path, content: str) -> str:
    return f"""
You are Sidecar, assisting the Spider KPI dashboard build/debug loop.

Workspace root: {WORKSPACE_ROOT}
Target repo: {TARGET_REPO}
Changed file: {rel(changed_file)}

Your job:
- inspect the changed file
- identify likely bugs, regressions, missing edge cases, or implementation risks
- recommend specific fixes
- prefer concise, technical, implementation-ready guidance
- if confidence is low, say what additional file or evidence is needed

Changed file content:
{content}

Nearby context:
{gather_neighbor_context(changed_file)}
""".strip()


def build_inbox_prompt(message_text: str, context_files: list[Path]) -> str:
    rendered_files = []
    for path in context_files[:MAX_CONTEXT_FILES]:
        rendered_files.append(f"### {rel(path)}\n{read_text(path)}")

    context_block = "\n\n".join(rendered_files) if rendered_files else "No context files were attached."

    return f"""
You are Sidecar, a real-time coding copilot for the Spider KPI dashboard.

Your job:
- answer the request directly
- focus on implementation support, debugging, architecture, and next actions
- be concrete and concise
- when relevant, cite file paths to inspect or change
- if the request is ambiguous, state the ambiguity and the best next step

Request:
{message_text}

Context files:
{context_block}
""".strip()


def call_model(prompt: str) -> str:
    response = client.responses.create(model=MODEL, input=prompt)
    text = getattr(response, "output_text", "").strip()
    return text or "No feedback returned."


def write_latest_feedback(title: str, body: str, meta: dict[str, object] | None = None) -> None:
    meta = meta or {}
    lines = [f"# {title}", ""]
    if meta:
        lines.append("## Meta")
        for key, value in meta.items():
            lines.append(f"- {key}: {value}")
        lines.append("")
    lines.extend(["## Feedback", body.strip(), ""])
    (OUTBOX / "latest_feedback.md").write_text("\n".join(lines), encoding="utf-8")


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def analyze_file(path: Path) -> None:
    content = read_text(path)
    prompt = build_change_prompt(path, content)
    text = call_model(prompt)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    payload = {
        "type": "file_change_feedback",
        "created_at": utc_now(),
        "file": rel(path),
        "model": MODEL,
        "feedback": text,
    }
    write_json(OUTBOX / f"feedback-{stamp}.json", payload)
    write_latest_feedback(
        title="Sidecar Feedback",
        body=text,
        meta={"file": rel(path), "created_at": payload["created_at"], "model": MODEL},
    )
    print(f"[sidecar] updated feedback for {rel(path)}")


def parse_inbox_request(path: Path) -> tuple[str, list[Path]]:
    if path.suffix.lower() == ".json":
        data = json.loads(read_text(path, limit=20000))
        message_text = str(data.get("message", "")).strip()
        context_files = []
        for raw in data.get("context_files", []):
            candidate = (WORKSPACE_ROOT / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
            if candidate.exists() and candidate.is_file():
                context_files.append(candidate)
        return message_text, context_files

    return read_text(path, limit=20000).strip(), []


def process_inbox() -> None:
    requests = sorted(
        [p for p in INBOX.iterdir() if p.is_file() and p.suffix.lower() in {".md", ".txt", ".json"}],
        key=lambda p: p.stat().st_mtime,
    )
    for path in requests:
        try:
            message_text, context_files = parse_inbox_request(path)
            if not message_text:
                reply = "Inbox request was empty."
            else:
                reply = call_model(build_inbox_prompt(message_text, context_files))

            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            reply_payload = {
                "type": "inbox_reply",
                "created_at": utc_now(),
                "request_file": path.name,
                "model": MODEL,
                "reply": reply,
            }
            write_json(OUTBOX / f"reply-{stamp}.json", reply_payload)
            write_latest_feedback(
                title="Sidecar Reply",
                body=reply,
                meta={"request_file": path.name, "created_at": reply_payload["created_at"], "model": MODEL},
            )
            processed_dir = INBOX / "processed"
            processed_dir.mkdir(parents=True, exist_ok=True)
            destination = processed_dir / path.name
            if path.exists():
                path.rename(destination)
            print(f"[sidecar] replied to {path.name}")
        except Exception as exc:
            error_payload = {
                "type": "inbox_error",
                "created_at": utc_now(),
                "request_file": path.name,
                "error": str(exc),
            }
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            write_json(OUTBOX / f"error-{stamp}.json", error_payload)
            write_latest_feedback(
                title="Sidecar Error",
                body=str(exc),
                meta={"request_file": path.name, "created_at": error_payload["created_at"]},
            )
            failed_dir = INBOX / "failed"
            failed_dir.mkdir(parents=True, exist_ok=True)
            destination = failed_dir / path.name
            if path.exists():
                path.rename(destination)
            print(f"[sidecar] failed to process {path.name}: {exc}")


def write_status() -> None:
    payload = {
        "type": "status",
        "created_at": utc_now(),
        "workspace_root": str(WORKSPACE_ROOT),
        "target_repo": str(TARGET_REPO),
        "model": MODEL,
        "poll_seconds": POLL_SECONDS,
        "watch_exts": sorted(WATCH_EXTS),
    }
    write_json(OUTBOX / "status.json", payload)


def main() -> None:
    acquire_lock()
    try:
        ensure_dirs()
        write_status()
        print(f"[sidecar] workspace={WORKSPACE_ROOT}")
        print(f"[sidecar] watching {TARGET_REPO}")
        prev = snapshot_files(TARGET_REPO)

        while True:
            process_inbox()
            curr = snapshot_files(TARGET_REPO)
            changed = [Path(p) for p, mt in curr.items() if prev.get(p) != mt]
            if changed:
                changed.sort(key=lambda p: curr[str(p.resolve())], reverse=True)
                analyze_file(changed[0])
            prev = curr
            time.sleep(POLL_SECONDS)
    finally:
        release_lock()


if __name__ == "__main__":
    main()
