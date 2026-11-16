#!/usr/bin/env bash
set -euo pipefail
if [[ "$EUID" != 0 ]]; then echo 'Run on the VPS as root'; exit 1; fi
base=/opt/courier-analytics
scripts="$base/dashboard-code/tools"
test -f /etc/superset-telegram/telegram.json
test -f /etc/superset-telegram/test-group.json
test -f "$scripts/run_matryoshka_monitor.py"
install -d -m 700 "$base/private"
cat > /etc/systemd/system/courier-matryoshka.service <<'UNIT'
[Unit]
Description=Collect Matryoshka orders and notify the test Telegram group
After=network-online.target
Wants=network-online.target
[Service]
Type=oneshot
UMask=0077
TimeoutStartSec=240
ExecStart=/usr/bin/flock -n /opt/courier-analytics/matryoshka.lock /usr/bin/python3 /opt/courier-analytics/dashboard-code/tools/run_matryoshka_monitor.py --send
UNIT
cat > /etc/systemd/system/courier-matryoshka.timer <<'UNIT'
[Unit]
Description=Check Matryoshka order thresholds every five minutes
[Timer]
OnBootSec=2min
OnUnitInactiveSec=5min
AccuracySec=15s
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now courier-matryoshka.timer
systemctl start --no-block courier-matryoshka.service
echo 'Matryoshka timer enabled. Check: journalctl -u courier-matryoshka.service -n 30 --no-pager'
