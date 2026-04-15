#!/usr/bin/env bash
# Thin wrapper around the Flask JSON API (no long curl lines).
# Usage: ./scripts/api.sh <command>
# Optional: MTG_API_BASE=http://raspberrypi.local:5000  (default http://127.0.0.1:5000)
# Optional: MTG_CONFIRM_JSON='{"foil":true,"quantity":2}' for confirm

set -euo pipefail

BASE="${MTG_API_BASE:-http://127.0.0.1:5000}"
BASE="${BASE%/}"

_pretty() {
  if command -v jq >/dev/null 2>&1; then
    jq .
  else
    python3 -m json.tool 2>/dev/null || cat
  fi
}

usage() {
  echo "Usage: $0 <command>" >&2
  echo "" >&2
  echo "Commands:" >&2
  echo "  health              GET  /api/health" >&2
  echo "  identify            POST /api/identify (camera + Claude only)" >&2
  echo "  scan                POST /api/scan (full pipeline + pending)" >&2
  echo "  confirm             POST /api/confirm (body from MTG_CONFIRM_JSON or foil=false qty=1)" >&2
  echo "  rescan              POST /api/rescan" >&2
  echo "  inventory [limit]   GET  /api/inventory (default limit 50)" >&2
  echo "" >&2
  echo "Environment:" >&2
  echo "  MTG_API_BASE        Base URL (default http://127.0.0.1:5000)" >&2
  echo "  MTG_CONFIRM_JSON    JSON body for confirm" >&2
  exit 2
}

cmd="${1:-}"
shift || true

case "$cmd" in
  health)
    curl -sS -f "$BASE/api/health" | _pretty
    ;;
  identify)
    curl -sS -f -X POST "$BASE/api/identify" | _pretty
    ;;
  scan)
    curl -sS -f -X POST "$BASE/api/scan" | _pretty
    ;;
  confirm)
    curl -sS -f -X POST "$BASE/api/confirm" \
      -H 'Content-Type: application/json' \
      -d "${MTG_CONFIRM_JSON:-{\"foil\":false,\"quantity\":1}}" | _pretty
    ;;
  rescan)
    curl -sS -f -X POST "$BASE/api/rescan" | _pretty
    ;;
  inventory)
    limit="${1:-50}"
    curl -sS -f "$BASE/api/inventory?limit=$limit" | _pretty
    ;;
  -h|--help|help|"")
    usage
    ;;
  *)
    echo "Unknown command: $cmd" >&2
    usage
    ;;
esac
