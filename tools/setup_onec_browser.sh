#!/usr/bin/env bash
set -euo pipefail
umask 077
venv=/opt/courier-analytics/onec-venv
if [[ ! -x "$venv/bin/python" ]]; then
  python3 -m venv "$venv"
fi
"$venv/bin/python" -m pip install 'playwright>=1.48,<2'
"$venv/bin/python" -m playwright install --with-deps chromium
echo '1C browser runtime installed. No credentials requested or transmitted.'
