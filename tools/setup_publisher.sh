#!/usr/bin/env bash
set -euo pipefail
umask 077
tools_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
mkdir -p /root/.ssh
chmod 700 /root/.ssh
publisher_key=/root/.ssh/courier-publisher
if [[ ! -e "$publisher_key" ]]; then
  ssh-keygen -q -t ed25519 -N '' -C courier-dashboard-publisher -f "$publisher_key"
fi
test -r "$publisher_key.pub"
chmod 600 "$publisher_key"
# Retrieve GitHub SSH host keys over verified HTTPS, not unauthenticated keyscan.
python3 - <<'PY'
import json
from pathlib import Path
import urllib.request
request = urllib.request.Request('https://api.github.com/meta',
                                 headers={'Accept': 'application/vnd.github+json',
                                          'User-Agent': 'courier-dashboard-setup'})
with urllib.request.urlopen(request, timeout=30) as response:
    keys = json.load(response).get('ssh_keys')
if not isinstance(keys, list) or not keys:
    raise SystemExit('GitHub did not return trusted SSH host keys')
allowed = ('ssh-ed25519 ', 'ecdsa-sha2-nistp256 ', 'ssh-rsa ')
if any(not isinstance(k, str) or not k.startswith(allowed) or '\n' in k or '\r' in k for k in keys):
    raise SystemExit('Invalid GitHub SSH host keys')
path = Path('/root/.ssh/courier-github-known-hosts')
path.write_text(''.join('github.com '+key+'\n' for key in keys))
path.chmod(0o600)
PY
install -m 644 "$tools_dir/courier-refresh.service" /etc/systemd/system/courier-refresh.service
install -m 644 "$tools_dir/courier-refresh.timer" /etc/systemd/system/courier-refresh.timer
systemctl daemon-reload
echo 'Add this PUBLIC key to GitHub repository Settings > Deploy keys, with write access:'
cat "$publisher_key.pub"
echo 'Timer installed but NOT enabled. Private key remains on this VPS.'
