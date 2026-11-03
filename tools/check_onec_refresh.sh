#!/usr/bin/env bash
set -uo pipefail
systemctl reset-failed courier-onec-roster.service
if systemctl start courier-onec-roster.service; then
  systemctl start courier-refresh.service
  systemctl start courier-web-data.service
fi
python3 -m json.tool /opt/courier-analytics/private/onec-browser-status.json
