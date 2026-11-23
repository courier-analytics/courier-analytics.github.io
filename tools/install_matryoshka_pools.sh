#!/usr/bin/env bash
set -euo pipefail
umask 077
[[ $(id -u) == 0 ]] || exit 1
cat > /etc/systemd/system/courier-matryoshka-pools.service <<'UNIT'
[Unit]
Description=Read-only Matryoshka courier order pools from 1C
After=network-online.target
[Service]
Type=oneshot
UMask=0077
EnvironmentFile=-/etc/courier-analytics/proxy.env
ExecStart=/opt/courier-analytics/import-venv/bin/python /opt/courier-analytics/dashboard-code/tools/matryoshka_pools.py
TimeoutStartSec=3600
StandardOutput=append:/opt/courier-analytics/private/matryoshka-pools-worker.log
StandardError=append:/opt/courier-analytics/private/matryoshka-pools-worker.log
UNIT
cat > /etc/systemd/system/courier-matryoshka-pools.timer <<'UNIT'
[Unit]
Description=Refresh Matryoshka order pools
[Timer]
OnBootSec=3min
OnUnitInactiveSec=15min
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now courier-matryoshka-pools.timer
systemctl restart courier-attendance-bot.service
systemctl start --no-block courier-matryoshka-pools.service
echo 'Read-only pool collection started. Use /matreshka after the first collection.'
