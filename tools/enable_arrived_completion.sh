#!/usr/bin/env bash
set -euo pipefail
cd /opt/courier-analytics/dashboard-code
[[ $(id -u) == 0 ]] || { echo 'Run on the dashboard VPS as root.'; exit 1; }
bash tools/update_private_frontend.sh
systemctl restart courier-refresh.service
systemctl start courier-web-data.service
systemd-run --no-block --property=Type=oneshot --unit=courier-completion-recalculate --collect --property=TimeoutStartSec=1800 /bin/bash /opt/courier-analytics/dashboard-code/tools/recalculate_completion.sh
echo 'Metric seven now uses actual arrivals. DS7745 history recalculation runs on the server and survives SSH disconnection.'
echo 'Progress: journalctl -u courier-completion-recalculate -n 20 --no-pager'
