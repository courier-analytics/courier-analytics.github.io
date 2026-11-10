#!/usr/bin/env bash
set -euo pipefail
cd /opt/courier-analytics/dashboard-code
[[ $(id -u) == 0 ]] || exit 1
# User explicitly requested public names and shift details for DS7745.
install -d -m 755 /etc/courier-analytics
touch /etc/courier-analytics/open-details-7745.enabled
chmod 644 /etc/courier-analytics/open-details-7745.enabled
systemctl start --no-block courier-refresh.service
echo 'DS7745 named detail publication enabled. Refresh queued.'
echo 'Public HTML: https://courier-analytics.github.io/7745.html'
