#!/usr/bin/env bash
set -euo pipefail

FRONTEND_BASE="${FRONTEND_BASE:-https://kpi.spidergrills.com}"
BACKEND_BASE="${BACKEND_BASE:-https://api-kpi.spidergrills.com}"

routes=(
  "/"
  "/commercial"
  "/support"
  "/ux"
  "/issues"
  "/diagnostics"
  "/source-health"
)

api_paths=(
  "/api/overview"
  "/api/kpis/daily"
  "/api/kpis/intraday"
  "/api/diagnostics"
  "/api/recommendations"
  "/api/source-health"
  "/api/support/overview"
  "/api/issues"
  "/api/data-quality"
)

failures=0

check_url() {
  local label="$1"
  local url="$2"
  local expect_type="${3:-}"
  local tmp_body tmp_headers status ctype
  tmp_body=$(mktemp)
  tmp_headers=$(mktemp)

  if ! curl -fsS -D "$tmp_headers" -o "$tmp_body" "$url"; then
    echo "FAIL [$label] request failed: $url"
    failures=$((failures + 1))
    rm -f "$tmp_body" "$tmp_headers"
    return
  fi

  status=$(awk 'toupper($1) ~ /^HTTP\// { code=$2 } END { print code }' "$tmp_headers")
  ctype=$(awk 'BEGIN{IGNORECASE=1} /^content-type:/ {sub(/\r$/, "", $0); print substr($0,15)}' "$tmp_headers" | tail -n1 | sed 's/^ *//')

  if [[ "$status" != "200" ]]; then
    echo "FAIL [$label] expected 200 got $status: $url"
    failures=$((failures + 1))
  elif [[ "$expect_type" == "html" ]] && ! grep -qi '<!doctype html\|<html' "$tmp_body"; then
    echo "FAIL [$label] expected HTML body: $url"
    failures=$((failures + 1))
  elif [[ "$expect_type" == "json" ]] && ! python3 - <<'PY' "$tmp_body"
import json, sys
json.load(open(sys.argv[1]))
PY
  then
    echo "FAIL [$label] expected valid JSON: $url"
    failures=$((failures + 1))
  else
    echo "PASS [$label] $status ${ctype:-unknown}"
  fi

  rm -f "$tmp_body" "$tmp_headers"
}

check_url "backend health" "$BACKEND_BASE/health" json

for route in "${routes[@]}"; do
  label="frontend route ${route}"
  check_url "$label" "$FRONTEND_BASE$route" html
done

for path in "${api_paths[@]}"; do
  label="frontend proxied ${path}"
  check_url "$label" "$FRONTEND_BASE$path" json
done

if (( failures > 0 )); then
  echo "SMOKE TEST FAILED ($failures failures)"
  exit 1
fi

echo "SMOKE TEST PASSED"
