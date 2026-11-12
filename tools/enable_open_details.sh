#!/usr/bin/env bash
set -euo pipefail
cd /opt/courier-analytics/dashboard-code
[[ $(id -u) == 0 ]] || exit 1
shop=${1:-7745}
case "$shop" in 7745|8889) ;; *) echo "Supported shops: 7745,8889"; exit 1 ;; esac
install -d -m 755 /etc/courier-analytics
touch /etc/courier-analytics/open-details-${shop}.enabled
chmod 644 /etc/courier-analytics/open-details-${shop}.enabled
systemctl start --no-block courier-refresh.service
echo "DS${shop} named detail publication enabled. Refresh queued."
echo "Public HTML: https://courier-analytics.github.io/${shop}.html"
