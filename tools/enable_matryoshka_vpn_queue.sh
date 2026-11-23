#!/usr/bin/env bash
set -euo pipefail
[[ $(id -u) == 0 ]] || exit 1
install -d -m 755 /etc/systemd/system/courier-matryoshka.service.d
cat > /etc/systemd/system/courier-matryoshka.service.d/vpn-queue.conf <<'UNIT'
[Service]
TimeoutStartSec=600
UNIT
systemctl daemon-reload
systemctl reset-failed courier-matryoshka.service
systemctl start --no-block courier-matryoshka.service
echo 'Matryoshka refresh queued with pool/attendance reads; existing VPN processes preserved.'
