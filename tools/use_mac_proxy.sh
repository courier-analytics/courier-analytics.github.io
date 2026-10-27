#!/usr/bin/env bash
# Restore the established Mac/Happ reverse-tunnel route after a real API check.
set -euo pipefail
umask 077
tools_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
python=/opt/courier-analytics/import-venv/bin/python
"$python" "$tools_dir/verify_server_proxy.py" --proxy socks5h://127.0.0.1:18080
install -d -m 700 /etc/courier-analytics
temporary=$(mktemp /etc/courier-analytics/.mac-proxy-XXXXXXXX)
trap 'rm -f -- "$temporary"' EXIT
printf '%s\n' 'COURIER_PROXY_URL=socks5h://127.0.0.1:18080' > "$temporary"
chmod 600 "$temporary"
mv -f -- "$temporary" /etc/courier-analytics/proxy.env
systemctl --no-ask-password daemon-reload
systemctl --no-ask-password reset-failed courier-refresh.service
systemctl --no-ask-password enable --now courier-refresh.timer
systemctl --no-ask-password start courier-refresh.service
systemctl --no-ask-password show courier-refresh.service -p Result -p ActiveState -p SubState
journalctl -u courier-refresh.service -n 8 --no-pager
echo 'Mac/Happ proxy restored on 18080. Keep the Mac, Happ and reverse SSH tunnel running.'
