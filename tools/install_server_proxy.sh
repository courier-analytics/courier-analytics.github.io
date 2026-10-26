#!/usr/bin/env bash
# Run on the VPS with a private JSON export. The old SSH proxy is not stopped.
set -euo pipefail
umask 077
[[ ${EUID} -eq 0 ]] || { echo 'Run as root on the VPS.' >&2; exit 1; }
[[ $# -eq 1 && -r "$1" ]] || { echo 'Usage: bash install_server_proxy.sh /root/private-node.json' >&2; exit 1; }
tools_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
private_export=$1
stage=$(mktemp -d /root/courier-proxy-setup-XXXXXXXX)
chmod 700 "$stage"
chmod 600 "$private_export"
python3 "$tools_dir/prepare_proxy_config.py" "$private_export" "$stage/config.json"
python3 "$tools_dir/download_xray.py" "$stage/xray"
if ! "$stage/xray" run -test -config "$stage/config.json" >"$stage/config-check.log" 2>&1; then
  echo "Xray rejected the configuration. Private diagnostics: $stage/config-check.log" >&2
  exit 1
fi

if ! getent passwd courier-proxy >/dev/null; then
  useradd --system --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin courier-proxy
fi
install -d -m 755 /usr/local/lib/courier-proxy
install -d -m 750 -o root -g courier-proxy /etc/courier-proxy
unit=/etc/systemd/system/courier-proxy.service
binary=/usr/local/lib/courier-proxy/xray
config=/etc/courier-proxy/config.json
was_active=no
systemctl is-active --quiet courier-proxy.service && was_active=yes
for file in "$unit" "$binary" "$config"; do
  if [[ -e "$file" ]]; then
    cp -a -- "$file" "$stage/$(basename "$file").previous"
  fi
done
rollback() {
  trap - ERR
  systemctl stop courier-proxy.service >/dev/null 2>&1 || true
  for file in "$unit" "$binary" "$config"; do
    previous="$stage/$(basename "$file").previous"
    if [[ -e "$previous" ]]; then
      cp -a -- "$previous" "$file"
    else
      rm -f -- "$file"
    fi
  done
  systemctl daemon-reload
  if [[ "$was_active" == yes ]]; then
    systemctl start courier-proxy.service || true
  fi
  echo "New proxy check failed. Previous proxy files restored; Mac tunnel was not changed. Private diagnostics: $stage" >&2
}
trap rollback ERR
install -m 755 "$stage/xray" "$binary"
install -m 640 -o root -g courier-proxy "$stage/config.json" "$config"
install -m 644 "$tools_dir/courier-proxy.service" "$unit"
systemctl daemon-reload
systemctl restart courier-proxy.service

# Give the socket time to bind. The request carries no account token.
proxy_http=$(curl --proxy socks5h://127.0.0.1:18081 --noproxy '' \
  --retry 3 --retry-connrefused --retry-delay 1 \
  --connect-timeout 10 --max-time 30 --silent --show-error \
  --output /dev/null --write-out '%{http_code}' \
  https://couriers-schedules.vkusvill.ru/v1/shops)
[[ "$proxy_http" == 401 || "$proxy_http" == 200 ]]
# Real authenticated read through the new proxy before changing the timer's route.
/opt/courier-analytics/import-venv/bin/python "$tools_dir/verify_server_proxy.py" \
  --proxy socks5h://127.0.0.1:18081 >"$stage/api-check.log"
trap - ERR

# All connection tests passed. Switch collection without changing system routes.
install -d -m 700 /etc/courier-analytics
proxy_env=$(mktemp /etc/courier-analytics/.proxy-env-XXXXXXXX)
printf '%s\n' 'COURIER_PROXY_URL=socks5h://127.0.0.1:18081' > "$proxy_env"
chmod 600 "$proxy_env"
mv -f -- "$proxy_env" /etc/courier-analytics/proxy.env
install -d -m 755 /etc/systemd/system/courier-refresh.service.d
install -d -m 755 /etc/systemd/system/courier-plan.service.d
printf '%s\n' '[Unit]' 'Wants=courier-proxy.service' 'After=courier-proxy.service' \
  > /etc/systemd/system/courier-refresh.service.d/proxy.conf
printf '%s\n' '[Unit]' 'Wants=courier-proxy.service' 'After=courier-proxy.service' \
  > /etc/systemd/system/courier-plan.service.d/proxy.conf
systemctl daemon-reload
systemctl enable courier-proxy.service
echo 'Server proxy verified, loopback only: 127.0.0.1:18081.'
echo 'Collector switched to the server proxy. SSH and default routes unchanged.'
echo 'Mac tunnel remains available as fallback on port 18080.'
echo 'Next: run courier-refresh.service and verify logs, then test with the Mac tunnel closed.'
