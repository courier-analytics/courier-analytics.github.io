#!/usr/bin/env bash
set -euo pipefail
umask 077
[[ $(uname -s) == Darwin ]] || { echo 'Run on your Mac.' >&2; exit 1; }
dashboard_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
dashboard_host=root@147.90.10.158
dashboard_ssh=(-o ServerAliveInterval=20 -o ServerAliveCountMax=3)
echo 'Keep Happ and the existing reverse SSH tunnel connected. Enter the HOSTKEY password when SSH requests it.'
dashboard_remote=$(ssh "${dashboard_ssh[@]}" "$dashboard_host" bash -s <<'REMOTE'
set -eu
umask 077
mkdir -p /opt/courier-analytics
destination=$(mktemp -d /opt/courier-analytics/dashboard-XXXXXXXX)
mkdir -p "$destination/tools" "$destination/site/data"
echo "$destination"
REMOTE
)
[[ "$dashboard_remote" =~ ^/opt/courier-analytics/dashboard-[a-zA-Z0-9]+$ ]] || exit 1
scp "${dashboard_ssh[@]}" "$dashboard_root"/tools/*.py \
  "$dashboard_root/tools/requirements.txt" "$dashboard_root/tools/scopes.json" \
  "$dashboard_root/tools/courier-refresh.service" "$dashboard_root/tools/courier-refresh.timer" \
  "$dashboard_host:$dashboard_remote/tools/"
scp "${dashboard_ssh[@]}" "$dashboard_root/index.html" "$dashboard_root/7745.html" "$dashboard_root/4747.html" \
  "$dashboard_root/dashboard-data.js" "$dashboard_host:$dashboard_remote/site/"
scp "${dashboard_ssh[@]}" "$dashboard_root/data/dashboard.json" \
  "$dashboard_host:$dashboard_remote/site/data/dashboard.json"
ssh "${dashboard_ssh[@]}" "$dashboard_host" bash -s -- "$dashboard_remote" <<'REMOTE'
set -euo pipefail
umask 077
destination=$1
test -r /root/curator-session.json
if [[ ! -x /opt/courier-analytics/import-venv/bin/python ]]; then
  python3 -m venv /opt/courier-analytics/import-venv
fi
/opt/courier-analytics/import-venv/bin/python -m pip install --disable-pip-version-check -r "$destination/tools/requirements.txt"
if [[ -r /opt/courier-analytics/current-site/data/dashboard.json ]]; then
  cp /opt/courier-analytics/current-site/data/dashboard.json "$destination/site/data/dashboard.json"
fi
# This refresh must pass before changing any active pointers.
/opt/courier-analytics/import-venv/bin/python "$destination/tools/refresh_dashboard.py" \
  --scopes "$destination/tools/scopes.json" --feed "$destination/site/data/dashboard.json"
chmod 755 "$destination" "$destination/site" "$destination/site/data"
chmod 644 "$destination/site/index.html" "$destination/site/7745.html" "$destination/site/4747.html" \
  "$destination/site/dashboard-data.js" "$destination/site/data/dashboard.json"
python3 - "$destination" <<'PY'
import os
from pathlib import Path
import sys
target = Path(sys.argv[1])
root = Path('/opt/courier-analytics')
for name, destination in [('current-app', target), ('current-site', target/'site')]:
    link = root/name
    if link.exists() and not link.is_symlink():
        raise SystemExit('Existing real directory at '+str(link)+'; preserved.')
for name, destination in [('current-app', target), ('current-site', target/'site')]:
    temporary = root/(name+'.next-'+str(os.getpid()))
    temporary.symlink_to(destination)
    os.replace(temporary, root/name)
print('Validated local site:', root/'current-site')
print('No GitHub publication or timer activation performed.')
PY
REMOTE
