#!/bin/zsh
# install_nightly.command — double-click to install the Riftvor nightly
# heartbeat as a launchd agent (daily 02:30). Mirrors the paper-bot
# install_autorun.command pattern. Uninstall:
#   launchctl unload ~/Library/LaunchAgents/com.riftvor.nightly.plist
#   rm ~/Library/LaunchAgents/com.riftvor.nightly.plist
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST="$HOME/Library/LaunchAgents/com.riftvor.nightly.plist"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.riftvor.nightly</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>${DIR}/run_nightly.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>2</integer>
    <key>Minute</key><integer>30</integer>
  </dict>
  <key>StandardOutPath</key><string>${DIR}/state/nightly_launchd.log</string>
  <key>StandardErrorPath</key><string>${DIR}/state/nightly_launchd.log</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Installed: Riftvor nightly heartbeat at 02:30 daily."
echo "Log: ${DIR}/state/nightly.log"
