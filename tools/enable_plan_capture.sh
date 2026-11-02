#!/usr/bin/env bash
set -euo pipefail
umask 077
scripts=/opt/courier-analytics/dashboard-code/tools
printf 'Previous plan capture state:\n'
systemctl is-enabled courier-plan.timer || true
systemctl is-active courier-plan.timer || true
journalctl -u courier-plan.service -n 8 --no-pager || true
install -m 644 "$scripts/courier-plan.service" /etc/systemd/system/courier-plan.service
install -m 644 "$scripts/courier-plan.timer" /etc/systemd/system/courier-plan.timer
systemctl daemon-reload
systemctl enable --now courier-plan.timer
systemctl list-timers courier-plan.timer --no-pager
# Never start capture_plan.py now: snapshots are valid only in the 23:59 window.
flock -w 120 /opt/courier-analytics/refresh.lock /opt/courier-analytics/import-venv/bin/python "$scripts/check_plan_capture.py" --repair-yesterday
