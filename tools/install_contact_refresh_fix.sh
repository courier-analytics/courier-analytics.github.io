#!/usr/bin/env bash
set -euo pipefail
umask 077
[[ $(id -u) == 0 ]] || exit 1
if [[ $(systemctl show courier-contacts-refresh.service -p ActiveState --value) == activating ]]; then
 echo 'Contact refresh is running; let it finish before installing.'; exit 1
fi
base=/opt/courier-contacts
cp "$base/refresh_phones.py" "$base/refresh_phones.py.backup-$(date +%Y%m%d-%H%M%S)"
install -m 600 /opt/courier-analytics/dashboard-code/tools/refresh_contact_phones.py "$base/refresh_phones.py"
systemctl reset-failed courier-contacts-refresh.service
systemctl start --no-block courier-contacts-refresh.service
echo 'Three-shop contact refresh queued; full global directory export is separate and opt-in.'
