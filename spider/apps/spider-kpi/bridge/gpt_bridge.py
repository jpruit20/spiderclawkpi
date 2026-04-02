import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests

BRIDGE_DIR = Path(r"C:\Users\josep\OneDrive\openclaw-gpt-bridge")
TO_GPT = BRIDGE_DIR / "to_gpt.txt"
FROM_GPT = BRIDGE_DIR / "from_gpt.txt"
STATE_FILE = BRIDGE_DIR / "bridge_state.json"
HISTORY_DIR = BRIDGE_DIR / "history"

API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
API_URL = "https://api.openai.com/v1/responses"
MODEL = "gpt-5"

SYSTEM_PROMPT = """You generate exact execution prompts for Open Claw.
Output plain text only.
Do not add markdown fences unless explicitly requested.
Be precise, operational, and implementation-focused.
"""

POLL_SECONDS = 2.0


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def ensure_files() -> None:
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    TO_GPT.touch(exist_ok=True)
    FROM_GPT.touch(exist_ok=True)
    if not STATE_FILE.exists():
        STATE_FILE.write_text(
            json.dumps(
                {
                    "last_to_gpt_mtime": 0.0,
                    "previous_response_id": None,
                    "status": "idle",
                    "last_processed_text_hash": None,
                    "last_success_at": None,
                    "last_error": None,
                    "last_request_preview": None,
                    "last_response_preview": None,
                },
                indent=2,
            ),
            encoding="utf-8",
        )


def load_state() -> dict[str, Any]:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    return {
        "last_to_gpt_mtime": data.get("last_to_gpt_mtime", 0.0),
        "previous_response_id": data.get("previous_response_id"),
        "status": data.get("status", "idle"),
        "last_processed_text_hash": data.get("last_processed_text_hash"),
        "last_success_at": data.get("last_success_at"),
        "last_error": data.get("last_error"),
        "last_request_preview": data.get("last_request_preview"),
        "last_response_preview": data.get("last_response_preview"),
    }


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace").strip()


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def build_input(user_text: str) -> list[dict[str, Any]]:
    return [
        {
            "role": "system",
            "content": [{"type": "input_text", "text": SYSTEM_PROMPT}],
        },
        {
            "role": "user",
            "content": [{"type": "input_text", "text": user_text}],
        },
    ]


def extract_output_text(payload: dict[str, Any]) -> str:
    output = payload.get("output", [])
    chunks: list[str] = []

    for item in output:
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                chunks.append(content.get("text", ""))

    text = "\n".join(chunk for chunk in chunks if chunk).strip()
    if text:
        return text

    if "output_text" in payload and isinstance(payload["output_text"], str):
        return payload["output_text"].strip()

    return ""


def call_openai(user_text: str, previous_response_id: Optional[str]) -> tuple[str, Optional[str]]:
    if not API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    body: dict[str, Any] = {
        "model": MODEL,
        "input": build_input(user_text),
    }
    if previous_response_id:
        body["previous_response_id"] = previous_response_id

    response = requests.post(API_URL, headers=headers, json=body, timeout=120)
    response.raise_for_status()
    payload = response.json()

    text = extract_output_text(payload)
    response_id = payload.get("id")
    if not text:
        raise RuntimeError(f"No output_text found in response payload: {json.dumps(payload)[:2000]}")
    return text, response_id


def archive_exchange(user_text: str, output_text: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    write_text(HISTORY_DIR / f"{stamp}_to.txt", user_text)
    write_text(HISTORY_DIR / f"{stamp}_from.txt", output_text)


def clear_to_gpt() -> None:
    write_text(TO_GPT, "")


def process_if_changed(state: dict[str, Any]) -> dict[str, Any]:
    try:
        mtime = TO_GPT.stat().st_mtime
    except FileNotFoundError:
        return state

    if mtime <= state.get("last_to_gpt_mtime", 0.0):
        return state

    user_text = read_text(TO_GPT)
    if not user_text:
        state["last_to_gpt_mtime"] = mtime
        state["status"] = "idle"
        save_state(state)
        return state

    request_hash = text_hash(user_text)
    if request_hash == state.get("last_processed_text_hash"):
        state["last_to_gpt_mtime"] = mtime
        state["status"] = "duplicate_skipped"
        state["last_error"] = None
        save_state(state)
        clear_to_gpt()
        return state

    state["status"] = "processing"
    state["last_error"] = None
    state["last_request_preview"] = user_text[:240]
    save_state(state)

    try:
        output_text, response_id = call_openai(
            user_text=user_text,
            previous_response_id=state.get("previous_response_id"),
        )
        write_text(FROM_GPT, output_text)
        archive_exchange(user_text, output_text)
        state["previous_response_id"] = response_id
        state["last_processed_text_hash"] = request_hash
        state["last_success_at"] = utc_now_iso()
        state["last_response_preview"] = output_text[:240]
        state["last_error"] = None
        state["status"] = "idle"
        clear_to_gpt()
    except Exception as exc:
        error_text = f"[GPT BRIDGE ERROR]\n{type(exc).__name__}: {exc}"
        write_text(FROM_GPT, error_text)
        state["last_error"] = error_text
        state["status"] = "error"

    state["last_to_gpt_mtime"] = mtime
    save_state(state)
    return state


def main() -> None:
    ensure_files()
    state = load_state()
    print(f"Watching: {TO_GPT}")
    print(f"Writing: {FROM_GPT}")
    print(f"History: {HISTORY_DIR}")

    while True:
        state = process_if_changed(state)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
