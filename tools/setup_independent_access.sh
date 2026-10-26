#!/usr/bin/env bash
# Interactive on the VPS: accepts a secret, checks access, then switches routes.
set -euo pipefail
umask 077
[[ ${EUID} -eq 0 ]] || { echo 'Run on the VPS as root.' >&2; exit 1; }
tools_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
python3 "$tools_dir/private_proxy_input.py"
bash "$tools_dir/install_server_proxy.sh" /root/courier-private-node.json
systemctl --no-ask-password start courier-refresh.service
systemctl --no-ask-password show courier-refresh.service -p Result -p ActiveState -p SubState
python3 "$tools_dir/independent_readiness.py"
echo 'Server proxy installed; refresh succeeded on the server route. Mac tunnel may now be closed for an independence test.'
echo 'Power BI source and automatic renewal of the primary session require separate verification.'
