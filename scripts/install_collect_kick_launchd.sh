#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="${IOS_HUNTER_LAUNCHD_LABEL:-local.ios-hunter.collect-kick}"
PLIST_DIR="${HOME}/Library/LaunchAgents"
PLIST_PATH="${PLIST_DIR}/${LABEL}.plist"
KICK_SCRIPT="${ROOT}/scripts/kick_collect_if_due.sh"
BASH_BIN="$(command -v bash)"
GIT_BIN="$(command -v git)"
GH_BIN="$(command -v gh)"
PYTHON_BIN="$(command -v python3)"
PATH_VALUE="$(dirname "${BASH_BIN}"):$(dirname "${GIT_BIN}"):$(dirname "${GH_BIN}"):$(dirname "${PYTHON_BIN}"):/usr/bin:/bin"

usage() {
  echo "Usage: $0 install|uninstall|status"
  exit 2
}

if [[ "${1:-}" == "" ]]; then
  usage
fi

case "$1" in
  install)
    chmod +x "${KICK_SCRIPT}"
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
    <string>${KICK_SCRIPT}</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>${PATH_VALUE}</string>
    <key>LANG</key>
    <string>en_US.UTF-8</string>
  </dict>
  <key>StartInterval</key>
  <integer>600</integer>
  <key>StandardOutPath</key>
  <string>${HOME}/Library/Logs/ios-hunter-collect-kick.launchd.out.log</string>
  <key>StandardErrorPath</key>
  <string>${HOME}/Library/Logs/ios-hunter-collect-kick.launchd.err.log</string>
</dict>
</plist>
EOF
    launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "${PLIST_PATH}"
    launchctl enable "gui/$(id -u)/${LABEL}" 2>/dev/null || true
    echo "Installed ${PLIST_PATH}"
    echo "Checks every 10 minutes; Python gates dispatch to overdue Kyiv slots between 09:15 and 21:00."
    echo "Log: ~/Library/Logs/ios-hunter-collect-kick.log"
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
