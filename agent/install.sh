#!/bin/bash
# Installs the ingest agent as a launchd job on this Mac: it starts at login
# and restarts if it stops. Run again to update the script, URL or key.
#
#   agent/install.sh https://api.gwanwoo.dev      (asks for the ingest key)
#   agent/install.sh --uninstall
#
# Set PYTHON to use a python3 other than the built-in one.
set -euo pipefail

LABEL=dev.gwanwoo.rbcheck-agent
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
INSTALL_DIR="$HOME/Library/Application Support/RBCheck"
LOG="$HOME/Library/Logs/rbcheck-agent.log"

if [[ "${1:-}" == "--uninstall" ]]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  rm -rf "$INSTALL_DIR"
  echo "Removed $LABEL."
  exit 0
fi

API_URL="${1:?usage: agent/install.sh <api-url> | --uninstall}"
read -rsp "Ingest key (INGEST_API_KEY from the server's .env): " INGEST_KEY
echo
[[ -n "$INGEST_KEY" ]] || { echo "No key given." >&2; exit 1; }

# Full Disk Access is granted to the real interpreter, not a /usr/bin shim,
# so resolve it now and run that exact binary.
PYTHON_BIN="$("${PYTHON:-/usr/bin/python3}" -c 'import os, sys; print(os.path.realpath(sys.executable))')"

# Copy the script out of the repo so moving or editing the checkout can't break the job.
mkdir -p "$INSTALL_DIR" "$(dirname "$PLIST")" "$(dirname "$LOG")"
cp "$(dirname "$0")/ingest_agent.py" "$INSTALL_DIR/ingest_agent.py"

# plistlib does the XML escaping. The file holds the key, so only you can read it.
umask 077
"$PYTHON_BIN" - "$PLIST" "$LABEL" "$PYTHON_BIN" "$INSTALL_DIR/ingest_agent.py" "$LOG" "$API_URL" "$INGEST_KEY" <<'PY'
import plistlib, sys
plist, label, python, script, log, api_url, key = sys.argv[1:]
with open(plist, "wb") as f:
    plistlib.dump({
        "Label": label,
        "ProgramArguments": [python, script],
        "EnvironmentVariables": {"RBCHECK_API_URL": api_url, "RBCHECK_INGEST_KEY": key},
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 30,
        "StandardOutPath": log,
        "StandardErrorPath": log,
    }, f)
PY

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

cat <<MSG
Installed $LABEL. Log: $LOG

If the log shows "unable to open database file" or "authorization denied",
give Full Disk Access to this binary (System Settings → Privacy & Security →
Full Disk Access → +, then Cmd+Shift+G to paste the path):

    $PYTHON_BIN

then run: launchctl kickstart -k gui/$(id -u)/$LABEL

Keep the Mac awake: System Settings → Battery (or Energy) → turn on
"Prevent automatic sleeping when the display is off".
MSG
