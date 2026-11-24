#!/bin/bash
# crontab の毎日の再起動を、タイマーコンセント対応の方式に切り替える（何度実行しても同じ）。
#   旧: 0 3 * * * sudo /sbin/reboot
#   新: 45 2 * * * sudo /home/pi/solar/power_cut_prepare.sh
#       （2:45 に SD を読み取り専用 → 2:50〜2:55 にタイマーが電源断。
#         タイマーが無い/動かない場合は 3:05 に自分で再起動）
# 元に戻す: ./setup_power_timer.sh --revert
set -euo pipefail
NEW='45 2 * * * sudo /home/pi/solar/power_cut_prepare.sh'
OLD='0 3 * * * sudo /sbin/reboot'

current=$(crontab -l 2>/dev/null)
if [ "${1:-}" = "--revert" ]; then
  printf '%s\n' "$current" | grep -vF "power_cut_prepare.sh" | { cat; echo "$OLD"; } | crontab -
  echo "元に戻しました（毎日 3:00 に再起動）"
else
  printf '%s\n' "$current" | grep -vF "$OLD" | grep -vF "power_cut_prepare.sh" | { cat; echo "$NEW"; } | crontab -
  echo "切り替えました（毎日 2:45 に SD を読み取り専用 → 電源断を待つ／無ければ 3:05 に再起動）"
fi
crontab -l | grep -E "reboot|power_cut" | sed 's/^/  /'
