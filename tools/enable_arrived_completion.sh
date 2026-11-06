#!/usr/bin/env bash
set -euo pipefail
cd /opt/courier-analytics/dashboard-code
[[ $(id -u) == 0 ]] || { echo 'Run on the dashboard VPS as root.'; exit 1; }
bash tools/update_private_frontend.sh
install -d -m 755 /etc/systemd/system/courier-refresh.service.d
cat > /etc/systemd/system/courier-refresh.service.d/zzzz-refresh-lock-wait.conf <<'UNIT'
[Service]
TimeoutStartSec=1200
ExecStart=
ExecStart=/usr/bin/flock -w 180 /opt/courier-analytics/refresh.lock /opt/courier-analytics/import-venv/bin/python /opt/courier-analytics/dashboard-code/tools/refresh_recent_days.py --feed /opt/courier-analytics/current-site/data/dashboard.json
ExecStartPost=
ExecStartPost=/usr/bin/flock -w 120 /opt/courier-analytics/publish.lock /opt/courier-analytics/import-venv/bin/python /opt/courier-analytics/dashboard-code/tools/publish_dashboard.py --feed /opt/courier-analytics/current-site/data/dashboard.json
UNIT
systemctl daemon-reload
systemctl reset-failed courier-refresh.service
if ! /usr/bin/flock -n /opt/courier-analytics/refresh.lock /usr/bin/true; then
  echo 'Another update currently holds refresh.lock. Waiting up to three minutes.'
  lslocks -o PID,COMMAND,PATH | awk 'NR==1 || $3=="/opt/courier-analytics/refresh.lock"' || true
fi
if ! systemctl restart courier-refresh.service; then
  echo 'Recent-day update failed; inspect the journal below. Historical recalculation will still be queued independently.'
  journalctl -u courier-refresh.service -n 25 --no-pager
fi
if ! systemctl start courier-web-data.service; then
  echo 'Protected data copy is not ready yet; the historical job will retry synchronization after recalculation.'
fi
case "$(systemctl show courier-completion-recalculate.service -p ActiveState --value 2>/dev/null)" in
  active|activating|reloading) echo 'Historical recalculation is already queued or running.' ;;
  *) systemd-run --no-block --property=Type=oneshot --unit=courier-completion-recalculate --collect --property=TimeoutStartSec=1800 /bin/bash /opt/courier-analytics/dashboard-code/tools/recalculate_completion.sh ;;
esac
echo 'Arrived-only formula installed. DS7745 history recalculation is queued independently of SSH.'
echo 'Progress: journalctl -u courier-completion-recalculate -n 20 --no-pager'
