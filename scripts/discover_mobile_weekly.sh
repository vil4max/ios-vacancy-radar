#!/usr/bin/env bash
# Weekly mobile-employer discovery: run, verify, commit and push to main.
#
# The owner granted this job standing permission (2026-09-22) to commit and
# push its own output: only the three discovery data files, and only after
# ruff, the tests and the private-data scan pass. Anything else aborts the run
# without publishing. It works in a throwaway worktree at origin/main, so the
# main checkout and other sessions' worktrees are never touched.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${HOME}/Library/Logs"
LOG_FILE="${RADAR_DISCOVERY_LOG:-${LOG_DIR}/ios-vacancy-radar-discovery.log}"
PYTHON="${RADAR_PYTHON:-${ROOT}/.venv/bin/python}"
KIT="${DEV_ROOT:-${HOME}/Developer/Personal}/agent-tools/agent-engineering-kit"
SCAN="${KIT}/features/policy/private-data-scan.py"
DRY_RUN="${RADAR_DISCOVERY_DRY_RUN:-0}"
ALLOWED_FILES=(
  "database/company_discovered.json"
  "database/company_discovery_state.json"
  "database/dou_service_companies.json"
)

mkdir -p "${LOG_DIR}"
exec >>"${LOG_FILE}" 2>&1

log() {
  printf '%s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$*"
}

WORKTREE=""
cleanup() {
  if [[ -n "${WORKTREE}" ]]; then
    git -C "${ROOT}" worktree remove --force "${WORKTREE}" >/dev/null 2>&1 || true
    rm -rf "${WORKTREE}"
  fi
}
trap cleanup EXIT

log "discovery start (dry_run=${DRY_RUN})"
for tool in git curl; do
  command -v "${tool}" >/dev/null 2>&1 || { log "ERROR: ${tool} not found"; exit 1; }
done
[[ -x "${PYTHON}" ]] || { log "ERROR: python not found at ${PYTHON}"; exit 1; }
[[ -f "${SCAN}" ]] || { log "ERROR: private-data scan not found at ${SCAN}"; exit 1; }

# DOU blocks clients that read too fast; a blocked address must wait, not retry.
dou_status="$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 -A 'Mozilla/5.0' https://jobs.dou.ua/companies/ || true)"
if [[ "${dou_status}" != "200" ]]; then
  log "skip: jobs.dou.ua answered ${dou_status:-no response}"
  exit 0
fi

git -C "${ROOT}" fetch --quiet origin main
WORKTREE="$(mktemp -d "${TMPDIR:-/tmp}/radar-discovery.XXXXXX")"
rmdir "${WORKTREE}"
git -C "${ROOT}" worktree add --quiet --detach "${WORKTREE}" origin/main
cd "${WORKTREE}"

discover_args=()
[[ "${DRY_RUN}" == "1" ]] && discover_args+=(--dry-run)
if ! summary="$("${PYTHON}" scripts/discover_mobile_companies.py "${discover_args[@]+"${discover_args[@]}"}" 2>&1)"; then
  log "ERROR: discovery failed: $(printf '%s' "${summary}" | tail -n 1)"
  exit 1
fi
log "$(printf '%s' "${summary}" | head -n 1)"

changed="$(git status --porcelain | awk '{print $2}')"
if [[ -z "${changed}" ]]; then
  log "no changes"
  exit 0
fi
while IFS= read -r path; do
  allowed=0
  for file in "${ALLOWED_FILES[@]}"; do
    [[ "${path}" == "${file}" ]] && allowed=1
  done
  if [[ "${allowed}" != "1" ]]; then
    log "ERROR: unexpected change ${path}; nothing published"
    exit 1
  fi
done <<<"${changed}"

if ! "${PYTHON}" -m ruff check . >/dev/null; then
  log "ERROR: ruff failed; nothing published"
  exit 1
fi
if ! tests="$("${PYTHON}" -m pytest -q -p no:cacheprovider 2>&1 | tail -n 1)"; then
  log "ERROR: tests failed (${tests}); nothing published"
  exit 1
fi

added="$(printf '%s' "${summary}" | sed -nE 's/.*added: ([0-9]+).*/\1/p' | head -n 1)"
inspected="$(printf '%s' "${summary}" | sed -nE 's/.*inspected: ([0-9]+).*/\1/p' | head -n 1)"
git add -- "${ALLOWED_FILES[@]}"
if [[ "${added:-0}" -gt 0 ]]; then
  subject="chore(watchlist): register ${added} discovered iOS and mobile employers"
  reason="The weekly discovery run registered ${added} companies whose careers page names iOS or a mobile stack and parses with the watchlist collector."
else
  subject="chore(watchlist): record weekly discovery inspection dates"
  reason="The weekly discovery run registered no company; it records the inspection dates so the next run skips these companies until they are stale."
fi
git commit --quiet -F - <<EOF
${subject}

${reason} It inspected ${inspected:-0} catalog companies (new or last
checked more than 90 days ago) and changed only the discovery data files.

Validation: ruff check passed; pytest passed (${tests});
private-data-scan.py passed on the outgoing commit (pre-push hook).
Published by the weekly discovery job under the owner's standing
permission of 2026-09-22.
EOF

if [[ "${DRY_RUN}" == "1" ]]; then
  log "dry run: committed locally in ${WORKTREE}, not pushed"
  exit 0
fi
if ! "${PYTHON}" "${SCAN}" --repo . --range origin/main..HEAD >/dev/null; then
  log "ERROR: private-data scan failed; nothing published"
  exit 1
fi
# Collection runs persist their own state to main; replay this commit on top once.
if ! git push --quiet origin HEAD:main; then
  git fetch --quiet origin main
  if ! git rebase --quiet origin/main || ! git push --quiet origin HEAD:main; then
    git rebase --abort >/dev/null 2>&1 || true
    log "ERROR: push failed after one rebase; nothing published"
    exit 1
  fi
fi
log "pushed $(git rev-parse --short HEAD): ${subject}"
