#!/usr/bin/env bash
set -euo pipefail
scripts=/opt/courier-analytics/dashboard-code/tools
install -m 644 "$scripts/courier-plan.service" /etc/systemd/system/courier-plan.service
install -m 644 "$scripts/courier-plan-check.service" /etc/systemd/system/courier-plan-check.service
systemctl daemon-reload
if ! systemctl start courier-plan-check.service; then
  journalctl -u courier-plan-check.service -n 16 --no-pager
  exit 1
fi
journalctl -u courier-plan-check.service -n 8 --no-pager
systemctl reset-failed courier-plan.service || true
systemctl enable --now courier-plan.timer
systemctl list-timers courier-plan.timer --no-pager
echo 'Tomorrow source verified through service environment. No snapshot invented. Capture remains scheduled for 23:59 Moscow.'
