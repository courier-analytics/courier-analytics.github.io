#!/usr/bin/env bash
# Run from a checkout on the VPS. No credentials are stored in this repository.
set -euo pipefail
umask 077
source_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
test -r /root/curator-session.json || { echo 'Existing session file missing.' >&2; exit 1; }
mkdir -p /opt/courier-analytics
release=$(mktemp -d /opt/courier-analytics/site-XXXXXXXX)
mkdir -p "$release/data"
cp "$source_root/index.html" "$source_root/7745.html" "$source_root/4747.html" \
  "$source_root/dashboard-data.js" "$release/"
if [[ -r /opt/courier-analytics/current-site/data/dashboard.json ]]; then
  cp /opt/courier-analytics/current-site/data/dashboard.json "$release/data/dashboard.json"
else
  cp "$source_root/data/dashboard.json" "$release/data/dashboard.json"
fi
if [[ ! -x /opt/courier-analytics/import-venv/bin/python ]]; then
  python3 -m venv /opt/courier-analytics/import-venv
fi
/opt/courier-analytics/import-venv/bin/python -m pip install --disable-pip-version-check -r "$source_root/tools/requirements.txt"
/opt/courier-analytics/import-venv/bin/python "$source_root/tools/refresh_dashboard.py" \
  --scopes "$source_root/tools/scopes.json" --feed "$release/data/dashboard.json"
chmod 755 "$release" "$release/data"
chmod 644 "$release"/*.html "$release/dashboard-data.js" "$release/data/dashboard.json"
python3 - "$source_root" "$release" <<'PY'
import os
from pathlib import Path
import sys
root = Path('/opt/courier-analytics')
targets = [('current-app', Path(sys.argv[1])), ('current-site', Path(sys.argv[2]))]
for name, _ in targets:
    link = root/name
    if link.exists() and not link.is_symlink():
        raise SystemExit('Existing directory preserved: '+str(link))
for name, destination in targets:
    temporary = root/(name+'.next-'+str(os.getpid()))
    temporary.symlink_to(destination)
    os.replace(temporary, root/name)
print('Validated local site: /opt/courier-analytics/current-site')
print('No GitHub publication or timer activation performed.')
PY
