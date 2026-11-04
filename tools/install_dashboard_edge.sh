#!/usr/bin/env bash
# Run on a separate, reachable Ubuntu/Debian VPS. Keep the current origin intact.
set -euo pipefail
umask 077
[[ $(id -u) == 0 ]] || { echo 'Run on the new entry VPS as root.'; exit 1; }
[[ $# == 2 ]] || { echo 'Usage: bash install_dashboard_edge.sh dashboard.example.ru NEW_PUBLIC_IPV4'; exit 1; }
host=$1
public_ip=$2
origin=courier-7745.147.90.10.158.sslip.io
python3 - "$host" "$public_ip" <<'PY'
import ipaddress,re,sys
host,address=sys.argv[1:]
if len(host)>253 or not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}',host):
    raise SystemExit('Pass a lowercase DNS hostname, without scheme, path or port.')
ip=ipaddress.IPv4Address(address)
if not ip.is_global or str(ip)=='147.90.10.158':
    raise SystemExit('Use the public IPv4 of a separate entry server.')
PY
if [[ -n $(ss -H -ltn '( sport = :80 or sport = :443 )') ]]; then
  echo 'Ports 80/443 are already in use. Existing services were preserved.'
  exit 1
fi
resolved=$(getent ahostsv4 "$host" | awk '{print $1}' | sort -u)
[[ "$resolved" == "$public_ip" ]] || {
  echo 'Point the hostname A record at the new entry IPv4 before installation.'; exit 1;
}
# The edge requires an outbound route to the existing origin before any setup.
if command -v curl >/dev/null; then
  code=$(curl --connect-timeout 10 --max-time 25 -sS -o /dev/null -w '%{http_code}' "https://$origin/login")
  [[ "$code" == 200 ]] || { echo 'Existing origin is unreachable from this entry server.'; exit 1; }
fi
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y caddy curl
code=$(curl --connect-timeout 10 --max-time 25 -sS -o /dev/null -w '%{http_code}' "https://$origin/api/session")
[[ "$code" == 401 ]] || { echo 'Origin authentication preflight failed. Edge was not configured.'; exit 1; }
install -d -m 755 /etc/caddy/sites-enabled
# Caddy's packaged default may start during apt installation. Do not overwrite it.
[[ ! -e /etc/caddy/sites-enabled/courier-dashboard-edge.caddy ]] || {
  echo 'Edge configuration already exists; inspect it instead of overwriting.'; exit 1;
}
cat > /etc/caddy/sites-enabled/courier-dashboard-edge.caddy <<SITE
$host {
    header Strict-Transport-Security "max-age=31536000"
    reverse_proxy https://$origin {
        header_up Host $origin
    }
}
SITE
chmod 644 /etc/caddy/sites-enabled/courier-dashboard-edge.caddy
if ! grep -Fq 'import /etc/caddy/sites-enabled/*.caddy' /etc/caddy/Caddyfile; then
  cp -p /etc/caddy/Caddyfile /etc/caddy/Caddyfile.before-courier-edge
  printf '\nimport /etc/caddy/sites-enabled/*.caddy\n' >> /etc/caddy/Caddyfile
fi
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
if command -v ufw >/dev/null && ufw status | grep -q '^Status: active'; then
  ufw allow 80/tcp
  ufw allow 443/tcp
fi
systemctl enable --now caddy
systemctl reload caddy
printf 'Entry address: https://%s/7745.html\n' "$host"
echo 'Existing dashboard login and password apply. Wait for HTTPS certificate issuance.'
echo 'Verify the new address from the user network with Happ disabled before switching links.'
echo 'Origin authentication, collection jobs and the old address were preserved.'
