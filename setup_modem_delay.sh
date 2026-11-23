#!/bin/bash
# ModemManager の起動を遅らせ、SIM モデム (Quectel EC25) の準備ができてから認識させる。
#
# 背景: 起動直後は EC25 の QMI ポート (cdc-wdm0) がまだ応答せず、ModemManager が
#       AT ポート (ttyUSB2) だけで登録してしまい、SIM のデータ通信がつながらない
#       ことが多い (毎日3時の再起動後)。数十秒待ってから起動すれば正しく認識できる。
#
# 使い方: ./setup_modem_delay.sh [待ち秒数]   (既定: 30)
# 元に戻す: sudo rm /etc/systemd/system/ModemManager.service.d/delay.conf && sudo systemctl daemon-reload
# 何度実行しても同じ結果になる。設定は次回起動時から有効（今動いている ModemManager は止めない）。
set -euo pipefail

DELAY="${1:-30}"
DIR=/etc/systemd/system/ModemManager.service.d
CONF="$DIR/delay.conf"

sudo mkdir -p "$DIR"
sudo tee "$CONF" >/dev/null <<CONF
# solar-camera: SIM モデムの準備を待ってから ModemManager を起動する
[Service]
ExecStartPre=/bin/sleep $DELAY
CONF
sudo systemctl daemon-reload

echo "設定しました: $CONF（起動前に ${DELAY} 秒待つ）"
systemctl show ModemManager -p ExecStartPre --no-pager | grep -o "argv\[\]=[^;]*" | sed 's/^/  /'
