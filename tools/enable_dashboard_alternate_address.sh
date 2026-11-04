#!/usr/bin/env bash
# Add an authenticated hostname on the existing VPS; preserve the original entry.
set -euo pipefail
umask 077
[[ $(id -u) == 0 ]] || { echo 'Run on the existing dashboard VPS as root.'; exit 1; }
host=courier-7745.147.90.10.158.nip.io
origin=courier-7745.147.90.10.158.sslip.io
site=/etc/caddy/sites-enabled/courier-dashboard-alternate.caddy
systemctl is-active --quiet courier-web.service
systemctl is-active --quiet caddy
resolved=$(getent ahostsv4 "$host" | awk '{print $1}' | sort -u)
[[ "$resolved" == 147.90.10.158 ]] || { echo 'Alternate hostname DNS is not as expected; no changes made.'; exit 1; }
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
