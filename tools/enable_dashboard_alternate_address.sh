#!/usr/bin/env bash
# Add an authenticated hostname on an already assigned IPv4; preserve the original entry.
set -euo pipefail
umask 077
[[ $(id -u) == 0 ]] || { echo 'Run on the existing dashboard VPS as root.'; exit 1; }
[[ $# -le 1 ]] || { echo 'Usage: bash enable_dashboard_alternate_address.sh [ASSIGNED_PUBLIC_IPV4]'; exit 1; }
public_ip=${1:-147.90.10.158}
python3 - "$public_ip" <<'PY'
import ipaddress,json,subprocess,sys
address=ipaddress.IPv4Address(sys.argv[1])
if not address.is_global:raise SystemExit('Pass a public IPv4 assigned to this VPS.')
interfaces=json.loads(subprocess.check_output(['ip','-j','-4','addr','show'],text=True))
assigned={a.get('local') for interface in interfaces for a in interface.get('addr_info',[])}
if str(address) not in assigned:
    raise SystemExit('IPv4 is not assigned inside this VPS. Obtain provider network settings first; no network or website changes made.')
PY
host=courier-7745.$public_ip.nip.io
origin=courier-7745.147.90.10.158.sslip.io
site=/etc/caddy/sites-enabled/courier-dashboard-alternate.caddy
if [[ "$public_ip" != 147.90.10.158 ]]; then
  site=/etc/caddy/sites-enabled/courier-dashboard-secondary-${public_ip//./-}.caddy
fi
systemctl is-active --quiet courier-web.service
systemctl is-active --quiet caddy
resolved=$(getent ahostsv4 "$host" | awk '{print $1}' | sort -u)
[[ "$resolved" == "$public_ip" ]] || { echo 'Alternate hostname DNS is not as expected; no changes made.'; exit 1; }
grep -Fq 'import /etc/caddy/sites-enabled/*.caddy' /etc/caddy/Caddyfile || {
  echo 'Expected Caddy include is absent; no changes made.'; exit 1;
}
for path in api/session data/dashboard.json; do
  code=$(curl --connect-timeout 3 --max-time 8 -sS -o /dev/null -w '%{http_code}' -H "Host: $origin" -H 'X-Forwarded-Proto: https' "http://127.0.0.1:8099/$path")
  [[ "$code" == 401 ]] || { echo 'Origin authentication check failed; no changes made.'; exit 1; }
done
[[ ! -e "$site" ]] || { echo "Alternate entry already configured: https://$host/7745.html"; exit 0; }
stage=$(mktemp /etc/caddy/.courier-alternate.XXXXXX)
trap 'rm -f "$stage" "$stage.config"' EXIT
cat > "$stage" <<SITE
$host {
    header Strict-Transport-Security "max-age=31536000"
    reverse_proxy 127.0.0.1:8099 {
        header_up Host $origin
    }
}
SITE
cat /etc/caddy/Caddyfile > "$stage.config"
printf '\nimport %s\n' "$stage" >> "$stage.config"
caddy validate --config "$stage.config" --adapter caddyfile
install -m 644 "$stage" "$site"
if ! systemctl reload caddy; then
  rm -f "$site"
  echo 'Caddy reload failed; the alternate config was withdrawn and original entry preserved.'
  exit 1
fi
printf 'Alternate HTML dashboard: https://%s/7745.html\n' "$host"
echo 'Allow up to two minutes for HTTPS certificate issuance, then open with Happ disabled.'
echo 'Same login/password, HTML pages and data. Existing origin and collection jobs unchanged.'
