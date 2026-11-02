#!/usr/bin/env bash
set -euo pipefail
umask 077
if [[ "$(uname -s)" != Darwin ]]; then
  echo 'Run this comparison in Terminal on the Mac.' >&2
  exit 1
fi
if [[ ! -x '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' ]]; then
  echo 'Google Chrome is required in Applications.' >&2
  exit 1
fi
root="$HOME/Library/Application Support/CourierOneCCheck"
mkdir -p "$root"
chmod 700 "$root"
source_url=https://raw.githubusercontent.com/courier-analytics/courier-analytics.github.io/main/tools
for script in onec_browser.py prepare_openvpn.py; do
  curl --fail --silent --show-error --output "$root/$script.tmp" "$source_url/$script"
  mv "$root/$script.tmp" "$root/$script"
done
if [[ ! -x "$root/venv/bin/python" ]]; then
  python3 -m venv "$root/venv"
fi
"$root/venv/bin/python" -m pip install --quiet 'playwright>=1.48,<2'
echo 'Uses your installed Chrome in a separate temporary session. Corporate VPN must be connected. 1C credentials are held only in memory and are not saved on the Mac.'
exec "$root/venv/bin/python" "$root/onec_browser.py" </dev/tty
