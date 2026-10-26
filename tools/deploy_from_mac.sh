#!/usr/bin/env bash
# Run on the user's Mac; SSH handles passwords without exposing them to this script.
set -euo pipefail
umask 077

if [[ $(uname -s) != Darwin ]]; then
  echo 'Run this script on your Mac, not on the VPS.' >&2
  exit 1
fi

importer_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
importer_xlsx=$(osascript -e 'POSIX path of (choose file with prompt "Выбери XLSX — выгрузку слотов с сайта")')
test -r "$importer_xlsx"
importer_host=root@147.90.10.158
importer_ssh=(-o ServerAliveInterval=20 -o ServerAliveCountMax=3)

echo 'The Mac, Happ and existing reverse SSH tunnel must remain connected.'
echo 'Enter the HOSTKEY server password if SSH requests it. Do not send it to chat.'
importer_remote=$(ssh "${importer_ssh[@]}" "$importer_host" bash -s <<'REMOTE'
set -eu
umask 077
mkdir -p /opt/courier-analytics
mktemp -d /opt/courier-analytics/import-XXXXXXXX
REMOTE
)
if [[ ! "$importer_remote" =~ ^/opt/courier-analytics/import-[a-zA-Z0-9]+$ ]]; then
  echo 'Unexpected remote destination; stopping.' >&2
  exit 1
fi

scp "${importer_ssh[@]}" "$importer_dir/import_slots.py" \
  "$importer_dir/enrich_slots.py" "$importer_dir/run_import.sh" \
  "$importer_dir/requirements.txt" "$importer_host:$importer_remote/"
scp "${importer_ssh[@]}" "$importer_xlsx" "$importer_host:$importer_remote/report.xlsx"
ssh "${importer_ssh[@]}" "$importer_host" \
  "bash '$importer_remote/run_import.sh' '$importer_remote/report.xlsx'"
