#!/bin/sh
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/trendradar"
if [ ! -x "$PY" ]; then
  echo "请先在仓库根目录执行：python -m venv .venv && .venv/bin/pip install -e ."
  exit 1
fi

PLIST="$HOME/Library/LaunchAgents/com.coin.trendradar.plist"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.coin.trendradar</string>
<key>ProgramArguments</key><array>
<string>$PY</string><string>daemon</string><string>--root</string><string>$ROOT</string>
</array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<key>WorkingDirectory</key><string>$ROOT</string>
<key>StandardOutPath</key><string>$ROOT/data/daemon.out.log</string>
<key>StandardErrorPath</key><string>$ROOT/data/daemon.err.log</string>
</dict></plist>
EOF

launchctl unload "$PLIST" >/dev/null 2>&1 || true
launchctl load "$PLIST"
echo "已安装：$PLIST"
echo "TrendRadar 会常驻；北京时间 13:00 后若当天未成功执行，会自动补跑。"
