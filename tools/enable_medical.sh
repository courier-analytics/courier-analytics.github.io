#!/usr/bin/env bash
set -euo pipefail
scripts=/opt/courier-analytics/dashboard-code/tools
# Validate a fresh real response and publish it before enabling recurring work.
bash "$scripts/refresh_medical.sh"
install -m 644 "$scripts/courier-medical.service" /etc/systemd/system/courier-medical.service
install -m 644 "$scripts/courier-medical.timer" /etc/systemd/system/courier-medical.timer
systemctl daemon-reload
systemctl enable --now courier-medical.timer
systemctl list-timers courier-medical.timer --no-pager
echo 'Valid LMK aggregates published; hourly collection enabled.'
