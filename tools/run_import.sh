#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ $# -ne 1 ]]; then
  echo 'Usage: bash run_import.sh /private/path/report.xlsx' >&2
  exit 1
fi

importer_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
importer_root=${COURIER_IMPORT_ROOT:-/opt/courier-analytics}
importer_session=${COURIER_SESSION_FILE:-/root/curator-session.json}
importer_proxy=${COURIER_PROXY_URL:-socks5h://127.0.0.1:18080}

test -r "$1" || { echo 'XLSX file is not readable' >&2; exit 1; }
test -r "$importer_session" || { echo 'Existing session file is not readable' >&2; exit 1; }
mkdir -p "$importer_root/data"
if [[ ! -x "$importer_root/import-venv/bin/python" ]]; then
  python3 -m venv "$importer_root/import-venv"
fi
"$importer_root/import-venv/bin/python" -m pip install --disable-pip-version-check -r "$importer_dir/requirements.txt"
"$importer_root/import-venv/bin/python" "$importer_dir/enrich_slots.py" "$1" \
  --session "$importer_session" --proxy "$importer_proxy" \
  --output "$importer_root/data/enriched-summary.json"
