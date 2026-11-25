#!/usr/bin/env bash
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo 'Run as root'; exit 1; }
cd /opt/courier-analytics/dashboard-code
/opt/courier-analytics/import-venv/bin/python -m py_compile tools/collect_matryoshka_grafana.py tools/probe_grafana.py
[ -f /root/courier-grafana.json ]
[ -f /opt/courier-analytics/private/matryoshka-monitor.json ]
umask 077
backup="/opt/courier-analytics/private/grafana-units-$(date +%Y%m%d%H%M%S)"
mkdir -p "$backup"
for unit in courier-matryoshka-grafana.service courier-matryoshka-grafana.timer; do
 if [ -f "/etc/systemd/system/$unit" ]; then cp -p "/etc/systemd/system/$unit" "$backup/"; fi
done
cat > /etc/systemd/system/courier-matryoshka-grafana.service <<'UNIT'
[Unit]
Description=Collect Matryoshka participant orders from Grafana
After=network-online.target
[Service]
Type=oneshot
WorkingDirectory=/opt/courier-analytics/dashboard-code
ExecStart=/opt/courier-analytics/import-venv/bin/python tools/collect_matryoshka_grafana.py
UMask=0077
TimeoutStartSec=12min
Restart=no
Nice=5
UNIT
cat > /etc/systemd/system/courier-matryoshka-grafana.timer <<'UNIT'
[Unit]
Description=Read Matryoshka orders every five minutes
[Timer]
OnCalendar=*-*-* *:0/5:00
AccuracySec=1s
Persistent=false
[Install]
WantedBy=timers.target
UNIT
systemd-analyze verify /etc/systemd/system/courier-matryoshka-grafana.service /etc/systemd/system/courier-matryoshka-grafana.timer
systemctl daemon-reload
systemctl enable --now courier-matryoshka-grafana.timer
systemctl start --no-block courier-matryoshka-grafana.service
systemctl list-timers courier-matryoshka-grafana.timer --no-pager
