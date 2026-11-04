#!/usr/bin/env bash
set -uo pipefail
systemctl reset-failed courier-onec-roster.service
# An explicit check must run the updated collector, not attach to an old automatic retry.
if systemctl restart courier-onec-roster.service; then
  systemctl start courier-refresh.service
  systemctl start courier-web-data.service
fi
python3 -m json.tool /opt/courier-analytics/private/onec-browser-status.json
