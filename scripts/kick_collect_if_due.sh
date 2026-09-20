#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${HOME}/Library/Logs"
LOG_FILE="${IOS_HUNTER_KICK_LOG:-${LOG_DIR}/ios-hunter-collect-kick.log}"
SLOTS_TMP="$(mktemp)"
cleanup() { rm -f "${SLOTS_TMP}"; }
trap cleanup EXIT

mkdir -p "${LOG_DIR}"
exec >>"${LOG_FILE}" 2>&1

log() {
  printf '%s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$*"
}

cd "${ROOT}"

if ! command -v git >/dev/null 2>&1; then
  log "ERROR: git not found"
  exit 1
fi
if ! command -v gh >/dev/null 2>&1; then
  log "ERROR: gh not found"
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  log "ERROR: python3 not found"
  exit 1
fi

log "fetch origin main"
if ! git fetch origin main; then
  log "ERROR: git fetch failed"
  exit 1
fi

if ! git show origin/main:database/collect_slots.json >"${SLOTS_TMP}"; then
  printf '%s\n' '{"days":{}}' >"${SLOTS_TMP}"
  log "WARN: collect_slots.json missing on origin/main — using empty"
fi

export COLLECT_SLOTS_PATH="${SLOTS_TMP}"

active="$(
  gh run list \
    --workflow "Collect iOS Jobs" \
    --limit 5 \
    --json status,databaseId \
    --jq '[.[] | select(.status=="queued" or .status=="in_progress" or .status=="pending" or .status=="waiting")] | length' \
    2>/dev/null || echo "error"
)"
if [[ "${active}" == "error" ]]; then
  log "ERROR: gh run list failed"
  exit 1
fi
if [[ "${active}" != "0" ]]; then
  log "SKIP: Collect already queued/in_progress (count=${active})"
  exit 0
fi

set +e
gate_out="$(python3 "${ROOT}/scripts/should_kick_collect.py" 2>&1)"
gate_status=$?
set -e
printf '%s\n' "${gate_out}"
if [[ "${gate_status}" -eq 1 ]]; then
  log "SKIP: gate exit ${gate_status}"
  exit 0
fi

if [[ "${gate_status}" -ne 0 ]]; then
  log "ERROR: gate exit ${gate_status}"
  exit "${gate_status}"
fi
if [[ "${IOS_HUNTER_KICK_DRY_RUN:-0}" == "1" ]]; then
  log "DRY RUN: would dispatch Collect iOS Jobs"
  exit 0
fi
log "DISPATCH: Collect iOS Jobs"
if ! gh workflow run "Collect iOS Jobs" --ref main; then
  log "ERROR: gh workflow run failed"
  exit 1
fi
log "OK: Collect iOS Jobs dispatched"
exit 0
