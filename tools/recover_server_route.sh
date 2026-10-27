#!/usr/bin/env bash
# Recover an already installed server proxy without importing credentials again.
set -euo pipefail
umask 077
tools_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
python=/opt/courier-analytics/import-venv/bin/python
private=/opt/courier-analytics/private
feed=/opt/courier-analytics/current-site/data/dashboard.json
mkdir -p "$private"
stage=$(mktemp -d "$private/route-recovery-XXXXXXXX")
exec 9>/opt/courier-analytics/refresh.lock
flock -w 120 9
"$python" - "$tools_dir" <<'PY'
import socket, sys
sys.path.insert(0, sys.argv[1])
from proxy_config import configured_proxy
print('Configured collector proxy: '+configured_proxy(), flush=True)
for port in (18080, 18081):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=2):
            print(f'Local port {port}: accepting connections', flush=True)
    except OSError:
        print(f'Local port {port}: unavailable', flush=True)
PY
if ! "$python" "$tools_dir/verify_server_proxy.py" --proxy socks5h://127.0.0.1:18081; then
  echo 'Server proxy did not pass authenticated verification. Route unchanged.' >&2
  exit 1
fi
cp "$feed" "$stage/feed.json"
echo 'Collecting current metrics through server port 18081; the Mac proxy is not used.'
if ! "$python" "$tools_dir/refresh_all_shops.py" --proxy socks5h://127.0.0.1:18081 \
  --active-base --feed "$stage/feed.json" > "$stage/refresh.log" 2>&1; then
  echo "Candidate collection failed. Existing site and route preserved; private diagnostics: $stage/refresh.log" >&2
  exit 1
fi
flock -w 120 /opt/courier-analytics/publish.lock "$python" "$tools_dir/publish_dashboard.py" --feed "$stage/feed.json"
install -d -m 700 /etc/courier-analytics
if [[ -f /etc/courier-analytics/proxy.env ]]; then
  cp -a /etc/courier-analytics/proxy.env "$stage/proxy.env.previous"
fi
printf '%s\n' 'COURIER_PROXY_URL=socks5h://127.0.0.1:18081' > "$stage/proxy.env"
install -m 600 "$stage/proxy.env" /etc/courier-analytics/proxy.env
install -d -m 755 /etc/systemd/system/courier-refresh.service.d /etc/systemd/system/courier-plan.service.d
if [[ -f /etc/systemd/system/courier-refresh.service.d/all-shops.conf ]]; then
  cp -a /etc/systemd/system/courier-refresh.service.d/all-shops.conf "$stage/all-shops.conf.previous"
fi
cat > /etc/systemd/system/courier-refresh.service.d/all-shops.conf <<UNIT
[Unit]
Wants=courier-proxy.service
After=courier-proxy.service
[Service]
EnvironmentFile=-/etc/courier-analytics/proxy.env
ExecStart=
ExecStart=/usr/bin/flock -n /opt/courier-analytics/refresh.lock $python $tools_dir/refresh_all_shops.py --feed $feed
UNIT
cat > /etc/systemd/system/courier-plan.service.d/proxy.conf <<'UNIT'
[Unit]
Wants=courier-proxy.service
After=courier-proxy.service
[Service]
EnvironmentFile=-/etc/courier-analytics/proxy.env
UNIT
"$python" - "$stage/feed.json" "$feed" "$tools_dir" <<'PY'
from pathlib import Path
import json, sys
sys.path.insert(0, sys.argv[3])
from enrich_slots import atomic_json
atomic_json(Path(sys.argv[2]), json.loads(Path(sys.argv[1]).read_text()))
Path(sys.argv[2]).chmod(0o644)
PY
systemctl --no-ask-password daemon-reload
systemctl --no-ask-password reset-failed courier-refresh.service
systemctl --no-ask-password enable --now courier-proxy.service courier-refresh.timer
flock -u 9
systemctl --no-ask-password start courier-refresh.service
systemctl --no-ask-password show courier-refresh.service -p Result -p ActiveState -p SubState
TZ=Europe/Moscow systemctl --no-ask-password list-timers courier-refresh.timer --no-pager
echo 'Fresh data published and scheduled refresh verified through server proxy 18081.'
