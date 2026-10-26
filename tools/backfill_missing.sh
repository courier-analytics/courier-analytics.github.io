#!/usr/bin/env bash
set -euo pipefail
umask 077
tools_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
python=/opt/courier-analytics/import-venv/bin/python
feed=/opt/courier-analytics/current-site/data/dashboard.json
private=/opt/courier-analytics/private
exec 9>/opt/courier-analytics/refresh.lock
flock -w 120 9
candidate=$(mktemp "$private/.backfill-feed-XXXXXXXX")
trap 'rm -f -- "$candidate"' EXIT
cp "$feed" "$candidate"
"$python" "$tools_dir/backfill_dashboard.py" --feed "$candidate" "$@"
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
echo 'Missing API-backed dates published for all DS. Existing timers unchanged.'
