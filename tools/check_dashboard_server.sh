#!/usr/bin/env bash
# Read-only diagnostics. Run on the existing dashboard VPS as root.
set -uo pipefail
host=courier-7745.147.90.10.158.sslip.io
printf '\nServices\n'
for service in caddy courier-web; do
  printf '%s: ' "$service"
  systemctl is-active "$service" || true
 done
printf '\nWeb listeners\n'
ss -ltnp '( sport = :80 or sport = :443 or sport = :8099 )'
printf '\nLocal app (expected 200, 401, 401)\n'
for path in login api/session data/dashboard.json; do
  printf '%s: ' "$path"
  curl --connect-timeout 3 --max-time 8 -sS -o /dev/null -w '%{http_code}\n' -H "Host: $host" -H 'X-Forwarded-Proto: https' "http://127.0.0.1:8099/$path" || true
 done
printf '\nLocal HTTPS through Caddy (expected 200, 401, 401)\n'
for path in login api/session data/dashboard.json; do
  printf '%s: ' "$path"
  curl --connect-timeout 3 --max-time 8 --resolve "$host:443:127.0.0.1" -sS -o /dev/null -w '%{http_code}\n' "https://$host/$path" || true
 done
printf '\nUFW status and web rules\n'
if command -v ufw >/dev/null; then
  ufw status | awk '/^Status:|(^|[[:space:]])(80|443)(\/tcp|\/udp|[[:space:]])/'
fi
printf '\nCaddy validation\n'
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
printf '\nNo configuration, credentials, collectors or firewall rules changed.\n'
