#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="${RADAR_DISCOVERY_LAUNCHD_LABEL:-local.ios-vacancy-radar.discover-mobile}"
PLIST_DIR="${HOME}/Library/LaunchAgents"
PLIST_PATH="${PLIST_DIR}/${LABEL}.plist"
JOB_SCRIPT="${ROOT}/scripts/discover_mobile_weekly.sh"
BASH_BIN="$(command -v bash)"
GIT_BIN="$(command -v git)"
CURL_BIN="$(command -v curl)"
PATH_VALUE="$(dirname "${BASH_BIN}"):$(dirname "${GIT_BIN}"):$(dirname "${CURL_BIN}"):/usr/bin:/bin"
# Saturday 10:00 local time: outside the collection slots; launchd runs a missed
# slot when the Mac wakes.
WEEKDAY="${RADAR_DISCOVERY_WEEKDAY:-6}"
HOUR="${RADAR_DISCOVERY_HOUR:-10}"

usage() {
  echo "Usage: $0 install|uninstall|status"
  exit 2
}

if [[ "${1:-}" == "" ]]; then
  usage
fi

case "$1" in
  install)
    chmod +x "${JOB_SCRIPT}"
    mkdir -p "${PLIST_DIR}"
    cat >"${PLIST_PATH}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>WorkingDirectory</key>
  <string>${ROOT}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${BASH_BIN}</string>
    <string>${JOB_SCRIPT}</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>${PATH_VALUE}</string>
    <key>LANG</key>
    <string>en_US.UTF-8</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key>
    <integer>${WEEKDAY}</integer>
    <key>Hour</key>
    <integer>${HOUR}</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>${HOME}/Library/Logs/ios-vacancy-radar-discovery.launchd.out.log</string>
  <key>StandardErrorPath</key>
  <string>${HOME}/Library/Logs/ios-vacancy-radar-discovery.launchd.err.log</string>
</dict>
</plist>
EOF
    launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "${PLIST_PATH}"
    launchctl enable "gui/$(id -u)/${LABEL}" 2>/dev/null || true
    echo "Installed ${PLIST_PATH}"
    echo "Runs weekly (weekday ${WEEKDAY}, ${HOUR}:00 local); skips while jobs.dou.ua refuses this address."
    echo "Log: ~/Library/Logs/ios-vacancy-radar-discovery.log"
    ;;
  uninstall)
    launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
    rm -f "${PLIST_PATH}"
    echo "Removed ${LABEL}"
    ;;
  status)
    if [[ -f "${PLIST_PATH}" ]]; then
      echo "plist: ${PLIST_PATH}"
      launchctl print "gui/$(id -u)/${LABEL}" 2>/dev/null | head -n 40 || echo "loaded: no"
    else
      echo "not installed"
    fi
    ;;
  *)
    usage
    ;;
esac
