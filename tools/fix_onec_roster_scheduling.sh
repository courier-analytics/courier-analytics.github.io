#!/usr/bin/env bash
set -euo pipefail
[[ $(id -u) == 0 ]] || exit 1
base=/opt/courier-analytics
backup="$base/private/roster-unit-backup-$(date +%Y%m%d-%H%M%S)"
mkdir -m 700 "$backup"
cp /etc/systemd/system/courier-onec-roster.service "$backup/"
install -m 644 "$base/dashboard-code/tools/courier-onec-roster.service" /etc/systemd/system/courier-onec-roster.service
systemctl daemon-reload
systemctl reset-failed courier-onec-roster.service
systemctl start --no-block courier-onec-roster.service
echo 'Roster refresh queued. Busy shared lock is deferred, not a failure/restart loop.'
