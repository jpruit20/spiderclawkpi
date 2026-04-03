# Sidecar

Sidecar is a file-driven KPI dashboard copilot for this Spider workspace.

## What it does

1. Watches `TARGET_REPO` for code/content changes.
2. Sends changed-file context to the configured OpenAI model.
3. Writes feedback into `sidecar/outbox/`.
4. Processes direct requests dropped into `sidecar/inbox/` and writes replies back to `sidecar/outbox/`.

## Active paths

- Inbox: `sidecar/inbox/`
- Processed inbox: `sidecar/inbox/processed/`
- Failed inbox: `sidecar/inbox/failed/`
- Outbox latest reply: `sidecar/outbox/latest_feedback.md`
- Outbox structured logs: `sidecar/outbox/*.json`
- Runtime status/latency snapshot: `sidecar/outbox/status.json`

## Request formats

### Simple markdown/text request

Create a file like `sidecar/inbox/question.md`:

```md
Review the KPI dashboard filtering logic and tell me the highest-risk bug.
```

### JSON request with attached context files

Create a file like `sidecar/inbox/question.json`:

```json
{
  "message": "Review the KPI dashboard routing logic and recommend fixes.",
  "context_files": [
    "memory/topics/kpi_dashboard.md",
    "memory/sessions/kpi_dashboard.md"
  ]
}
```

Context files may be absolute paths or workspace-relative paths.

## Behavior notes

- Sidecar ignores its own `sidecar/` directory to avoid self-trigger loops.
- It only watches source-like file types such as `.py`, `.ts`, `.tsx`, `.js`, `.jsx`, `.json`, `.md`, `.sql`, `.yaml`, `.yml`.
- `latest_feedback.md` is always replaced with the most recent file-watch analysis or inbox reply.
- Timestamped JSON files preserve a history of feedback/replies.
- `status.json` exposes the active model, PID, last request file, last request latency, last model latency, counters, and current runtime status.

## Start

```bash
./scripts/start_sidecar.sh
```

## Current intended use

Use Sidecar as a lightweight second set of eyes while building the Spider KPI dashboard. The main agent can write targeted questions into `sidecar/inbox/` and then read the reply from `sidecar/outbox/latest_feedback.md` or the newest `reply-*.json` file.
