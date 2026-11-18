#!/bin/bash
# 現場（ルーター無し）でも eth0 に固定IPが付くように、DHCP失敗時の予備プロファイルを作る。
#
#   自宅: eth0-auto (DHCP) が優先して使われる
#   現場: DHCP が DHCP_TIMEOUT 秒で失敗すると eth0-site (固定IP・ゲートウェイ無し) に切替
#
# 使い方: ./setup_site_network.sh [固定IP/プレフィックス]   (既定: 192.168.1.50/24)
#   ルーターの DHCP 割当範囲の外の、空いているアドレスを指定すること。
# 何度実行しても同じ結果になる（既存のプロファイルは上書き）。
set -euo pipefail

SITE_IP="${1:-192.168.1.50/24}"
LAN_CONN="eth0-auto"
SITE_CONN="eth0-site"
IFACE="eth0"
DHCP_TIMEOUT=30

if ! nmcli -t -f NAME connection show | grep -qx "$LAN_CONN"; then
  echo "接続 $LAN_CONN が見つかりません" >&2
  exit 1
fi

# DHCP 側: 優先度を上げ、IPv4 が取れなければ失敗扱い（→ 予備へ）。再試行は1回で予備へ移る
sudo nmcli connection modify "$LAN_CONN" \
  connection.autoconnect-priority 10 \
  connection.autoconnect-retries 1 \
  ipv4.dhcp-timeout "$DHCP_TIMEOUT" \
  ipv4.may-fail no

# 予備（現場用）: 固定IP、ゲートウェイ無し（インターネットは SIM）
if nmcli -t -f NAME connection show | grep -qx "$SITE_CONN"; then
  sudo nmcli connection modify "$SITE_CONN" ipv4.addresses "$SITE_IP"
else
  sudo nmcli connection add type ethernet ifname "$IFACE" con-name "$SITE_CONN" \
    connection.autoconnect yes \
    connection.autoconnect-priority 0 \
    ipv4.method manual \
    ipv4.addresses "$SITE_IP" \
    ipv4.never-default yes \
    ipv6.method link-local
fi

echo "設定完了:"
nmcli -f NAME,DEVICE,AUTOCONNECT,AUTOCONNECT-PRIORITY connection show | grep -E "NAME|$LAN_CONN|$SITE_CONN"
nmcli -g ipv4.addresses connection show "$SITE_CONN" | sed 's/^/  eth0-site の固定IP: /'
