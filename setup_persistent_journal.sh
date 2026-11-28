#!/bin/bash
# システムのログ（journal）を SD カードに保存し、再起動しても消えないようにする。
#
# 背景: Raspberry Pi OS はログをメモリにだけ置くため、再起動すると消える。
#       回線監視は断が続くと再起動するので、USB の切断・電圧低下・モデムの
#       エラーなど「なぜ止まったか」の証拠が残らない（現場では調べる手段がない）。
#
# 使い方:   ./setup_persistent_journal.sh          有効にする（上限 50MB）
#           ./setup_persistent_journal.sh --undo   元に戻す（保存したログも消す）
# 見方:     journalctl --list-boots                 残っている起動の一覧
#           journalctl -b -1 -k                     1つ前の起動のカーネルログ（USB・電圧）
#           journalctl -b -1 -u ModemManager        1つ前の起動のモデムのログ
# 何度実行しても同じ結果になる。すぐに有効になる（再起動は不要）。
set -euo pipefail

DIR=/etc/systemd/journald.conf.d
CONF="$DIR/90-solar-persistent.conf"   # RPi OS の 40-rpi-volatile-storage.conf より後に読まれる名前

if [ "${1:-}" = "--undo" ]; then
  sudo rm -f "$CONF"
  sudo rm -rf /var/log/journal          # このフォルダがあると保存が続くので消す
  sudo systemctl restart systemd-journald
  echo "元に戻しました（ログはメモリのみ・再起動で消える）"
  exit 0
fi

sudo mkdir -p "$DIR"
sudo tee "$CONF" >/dev/null <<'CONF'
# solar-camera: 再起動後も原因を調べられるよう、ログを SD カードに残す
[Journal]
Storage=persistent
SystemMaxUse=50M
SystemKeepFree=1G
CONF
sudo mkdir -p /var/log/journal
sudo systemd-tmpfiles --create --prefix /var/log/journal
sudo systemctl restart systemd-journald
sudo journalctl --flush                 # メモリにある今回の起動分も SD カードへ移す

echo "設定しました: $CONF（上限 50MB）"
journalctl --disk-usage | sed 's/^/  /'
