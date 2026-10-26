#!/usr/bin/env bash
# Validate live sources before replacing the running one-DS collector.
set -euo pipefail
umask 077
tools_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
python=/opt/courier-analytics/import-venv/bin/python
feed=/opt/courier-analytics/current-site/data/dashboard.json
private=/opt/courier-analytics/private
test -x "$python"
test -r "$feed"
mkdir -p "$private"
chmod 700 "$private"
exec 9>/opt/courier-analytics/refresh.lock
flock -w 120 9
# Read only: discovers all three scopes, checks roster and history schemas.
"$python" "$tools_dir/audit_sources.py" --output-dir "$private/audit"
candidate=$(mktemp "$private/.all-shops-feed-XXXXXXXX")
cp "$feed" "$candidate"
"$python" "$tools_dir/refresh_all_shops.py" --feed "$candidate"
# A failed publication leaves the existing active feed and timer configuration.
flock -w 120 /opt/courier-analytics/publish.lock "$python" "$tools_dir/publish_dashboard.py" --feed "$candidate"
"$python" - "$candidate" "$feed" "$tools_dir" <<'PY'
import json
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[3])
from enrich_slots import atomic_json
atomic_json(Path(sys.argv[2]), json.loads(Path(sys.argv[1]).read_text()))
Path(sys.argv[2]).chmod(0o644)
PY
rm -f -- "$candidate"
install -d -m 755 /etc/systemd/system/courier-refresh.service.d
cat > /etc/systemd/system/courier-refresh.service.d/all-shops.conf <<'UNIT'
[Service]
EnvironmentFile=-/etc/courier-analytics/proxy.env
ExecStart=
ExecStart=/usr/bin/flock -n /opt/courier-analytics/refresh.lock /opt/courier-analytics/import-venv/bin/python /opt/courier-analytics/current-app/tools/refresh_all_shops.py --feed /opt/courier-analytics/current-site/data/dashboard.json
UNIT
install -m 644 "$tools_dir/courier-plan.service" /etc/systemd/system/courier-plan.service
install -m 644 "$tools_dir/courier-plan.timer" /etc/systemd/system/courier-plan.timer
systemctl --no-ask-password daemon-reload
systemctl --no-ask-password reset-failed courier-refresh.service
systemctl --no-ask-password enable --now courier-refresh.timer courier-plan.timer
systemctl list-timers courier-refresh.timer courier-plan.timer --no-pager
echo 'Verified DS scopes enabled; unverified scopes remain unavailable.'
echo 'Plan-dependent metrics require a real snapshot from 23:59 the previous day.'
echo 'Existing Happ/SSH proxy route remains unchanged.'
