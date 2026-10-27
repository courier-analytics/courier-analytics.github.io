#!/usr/bin/env bash
set -euo pipefail
umask 077
[[ ${EUID} -eq 0 ]] || { echo 'Run on the VPS as root.' >&2; exit 1; }
tools_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec 8>/opt/courier-analytics/proxy-repair.lock
flock -w 5 8
python3 "$tools_dir/find_server_proxy.py"
bash "$tools_dir/install_server_proxy.sh" /root/courier-private-node.json
bash "$tools_dir/recover_server_route.sh"
python3 "$tools_dir/independent_readiness.py"
