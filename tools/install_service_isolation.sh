#!/usr/bin/env bash
set -euo pipefail
umask 077
[[ $(id -u) == 0 ]] || { echo 'Run on server as root'; exit 1; }
cd /opt/courier-analytics/dashboard-code
python=/opt/courier-analytics/import-venv/bin/python
backup=/opt/courier-analytics/private/service-isolation-$(date +%Y%m%d-%H%M%S)
mkdir -m 700 "$backup"
"$python" tools/service_isolation_audit.py > "$backup/inventory-before.json"
"$python" - <<'PY'
import sqlite3
from pathlib import Path
path=Path('/opt/courier-analytics/private/attendance-bot/cases.sqlite3')
if path.exists():
 with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as db:
  if db.execute("SELECT count(*) FROM cases WHERE state='applying'").fetchone()[0]:raise SystemExit('1C write in progress. Finish it before installing isolation.')
PY
# Keep the obsolete receiver off; one receiver owns the existing bot token.
systemctl stop courier-matryoshka-commands.service
systemctl disable courier-matryoshka-commands.service
for unit in courier-attendance-bot.service courier-matryoshka.service courier-matryoshka-pools.service courier-medical.service; do
 if [[ $(systemctl show "$unit" -p LoadState --value) == not-found ]]; then continue; fi
 target=/etc/systemd/system/$unit.d
 mkdir -p "$target"
 if [[ -f "$target/resource-isolation.conf" ]]; then cp "$target/resource-isolation.conf" "$backup/$unit.conf"; fi
 cat > "$target/resource-isolation.conf" <<'UNIT'
[Service]
CPUAccounting=yes
MemoryAccounting=yes
TasksAccounting=yes
CPUWeight=50
IOWeight=50
Nice=5
UNIT
 case "$unit" in
 courier-medical.service|courier-matryoshka.service) printf '\nTimeoutStartSec=900\n' >> "$target/resource-isolation.conf" ;;
 courier-matryoshka-pools.service) printf '\nTimeoutStartSec=3600\n' >> "$target/resource-isolation.conf" ;;
 esac
done
cat > /etc/systemd/system/courier-service-health.service <<'UNIT'
[Unit]
Description=Private service health inventory
[Service]
Type=oneshot
UMask=0077
ExecStart=/opt/courier-analytics/import-venv/bin/python /opt/courier-analytics/dashboard-code/tools/service_health_snapshot.py
TimeoutStartSec=60
Nice=10
UNIT
cat > /etc/systemd/system/courier-service-health.timer <<'UNIT'
[Unit]
Description=Check service health every two minutes
[Timer]
OnBootSec=2min
OnUnitInactiveSec=2min
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now courier-service-health.timer
systemctl start --no-block courier-service-health.service
systemctl restart courier-attendance-bot.service
"$python" tools/service_isolation_audit.py > "$backup/inventory-after.json"
echo "Isolation installed. Private service inventory: $backup/inventory-after.json"
echo 'Shared corporate VPN lease now covers Superset, 1C and Power BI entry points.'
echo 'Already running collectors finish with their existing code; do not kill their VPN.'
systemctl show courier-attendance-bot.service -p ActiveState -p SubState -p Result
