#!/usr/bin/env bash
# Installs a separate authenticated HTTPS site; does not alter public Pages or collector credentials.
set -euo pipefail
umask 077
[[ $(id -u) == 0 ]] || { echo 'Run on the VPS as root.'; exit 1; }
host=courier-7745.147.90.10.158.sslip.io
scripts=/opt/courier-analytics/dashboard-code/tools
repo=/opt/courier-analytics/dashboard-code
root=/opt/courier-dashboard
if ! systemctl is-active --quiet courier-web && [[ -n $(ss -H -ltn '( sport = :8099 )') ]]; then
  echo 'Port 8099 is already used. Existing service was preserved.'
  exit 1
fi
if ! systemctl is-active --quiet caddy && [[ -n $(ss -H -ltn '( sport = :80 or sport = :443 )') ]]; then
  echo 'Ports 80/443 are already used by another web server. Existing services were preserved.'
  ss -ltnp '( sport = :80 or sport = :443 )'
  exit 1
fi
getent ahostsv4 "$host" | awk '{print $1}' | sort -u | grep -qx '147.90.10.158' || { echo 'Hostname does not resolve to this VPS.'; exit 1; }
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv caddy curl
id courier-web >/dev/null 2>&1 || useradd --system --home /var/lib/courier-dashboard --shell /usr/sbin/nologin courier-web
install -d -m 755 "$root" "$root/app" "$root/site" "$root/site/data"
install -d -o root -g courier-web -m 750 /etc/courier-dashboard
install -d -o courier-web -g courier-web -m 700 /var/lib/courier-dashboard
install -d -o root -g courier-web -m 2750 "$root/details"
install -m 644 "$scripts/private_web/app.py" "$scripts/private_web/sync_data.py" "$scripts/private_web/requirements.txt" "$root/app/"
(
  umask 022
  python3 -m venv "$root/venv"
  "$root/venv/bin/pip" --disable-pip-version-check -q install -r "$root/app/requirements.txt"
)
"$root/venv/bin/python" - "$repo" "$root/site" <<'PY'
from pathlib import Path
import shutil,sys
sys.path.insert(0,'/opt/courier-dashboard/app')
from app import FILES
source,target=map(Path,sys.argv[1:])
for name in FILES:
    text=(source/name).read_text()
    if name.endswith('.html'):
        text=text.replace('</head>','<script>window.courierPrivate=true;</script></head>')
        text=text.replace('</body>','<script src="/private-session.js"></script><script src="/private-details.js"></script>\n</body>')
    path=target/name;path.write_text(text);path.chmod(0o644)
shutil.copyfile(source/'tools/private_web/private-session.js',target/'private-session.js')
(target/'private-session.js').chmod(0o644)
shutil.copyfile(source/'tools/private_web/private-details.js',target/'private-details.js')
(target/'private-details.js').chmod(0o644)
PY
"$root/venv/bin/python" - "$host" <<'PY'
import json,secrets,sys
from pathlib import Path
p=Path('/etc/courier-dashboard/settings.json')
d=json.loads(p.read_text()) if p.exists() else {'secret':secrets.token_hex(32)}
d.update(host=sys.argv[1],users='/etc/courier-dashboard/users.json',database='/var/lib/courier-dashboard/auth.sqlite3',site_root='/opt/courier-dashboard/site',data_root='/opt/courier-dashboard/site/data')
p.write_text(json.dumps(d));p.chmod(0o640)
PY
if [[ ! -s /etc/courier-dashboard/users.json ]]; then
  "$root/venv/bin/python" "$root/app/app.py" --add-user </dev/tty
fi
chown root:courier-web /etc/courier-dashboard/settings.json /etc/courier-dashboard/users.json
chmod 640 /etc/courier-dashboard/settings.json /etc/courier-dashboard/users.json
"$root/venv/bin/python" "$root/app/sync_data.py"
cat > /etc/systemd/system/courier-web.service <<'UNIT'
[Unit]
Description=Authenticated private courier dashboard
After=network.target
[Service]
User=courier-web
Group=courier-web
WorkingDirectory=/opt/courier-dashboard/app
Environment=COURIER_WEB_SETTINGS=/etc/courier-dashboard/settings.json
ExecStart=/opt/courier-dashboard/venv/bin/gunicorn --bind 127.0.0.1:8099 --workers 2 --threads 2 --timeout 30 app:create_app()
Restart=on-failure
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/courier-dashboard
[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/systemd/system/courier-web-data.service <<'UNIT'
[Unit]
Description=Refresh protected copies of public courier aggregates
[Service]
Type=oneshot
User=root
UMask=0077
ExecStart=/opt/courier-dashboard/venv/bin/python /opt/courier-dashboard/app/sync_data.py
UNIT
cat > /etc/systemd/system/courier-web-data.timer <<'UNIT'
[Unit]
Description=Update private dashboard aggregates every minute
[Timer]
OnBootSec=1min
OnUnitInactiveSec=1min
Unit=courier-web-data.service
[Install]
WantedBy=timers.target
UNIT
install -d -m 755 /etc/caddy/sites-enabled
cat > /etc/caddy/sites-enabled/courier-dashboard.caddy <<SITE
$host {
    encode gzip zstd
    header Strict-Transport-Security "max-age=31536000"
    reverse_proxy 127.0.0.1:8099
}
SITE
chmod 644 /etc/caddy/sites-enabled/courier-dashboard.caddy
if ! grep -Fq 'import /etc/caddy/sites-enabled/*.caddy' /etc/caddy/Caddyfile; then
  cp -p /etc/caddy/Caddyfile /etc/courier-dashboard/Caddyfile.before-dashboard
  printf '\nimport /etc/caddy/sites-enabled/*.caddy\n' >> /etc/caddy/Caddyfile
fi
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
systemctl daemon-reload
systemctl enable --now courier-web.service courier-web-data.timer caddy
systemctl restart courier-web.service
if command -v ufw >/dev/null && ufw status | grep -q '^Status: active'; then
  ufw allow 80/tcp
  ufw allow 443/tcp
fi
systemctl reload caddy
# Direct loopback verifies authentication without exposing this port publicly.
code=$(curl --retry 10 --retry-connrefused --retry-delay 1 -s -o /dev/null -w '%{http_code}' -H "Host: $host" -H 'X-Forwarded-Proto: https' http://127.0.0.1:8099/api/session)
[[ "$code" == 401 ]] || { echo 'Authentication preflight failed.'; exit 1; }
echo "Protected site: https://$host"
echo 'Caddy is obtaining the HTTPS certificate. Login uses the credentials entered above.'
echo 'The existing public GitHub Pages site still contains aggregate data only.'
