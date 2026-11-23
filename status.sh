#!/bin/bash
# solarcam (Raspberry Pi) と ConoHa の状態を一覧表示する。
#   ~/solar/status.sh
cd "$(dirname "$0")" || exit 1
eval "$(python3 -c "import config;print(f'H={config.CONOHA_USER}@{config.CONOHA_HOST} K={config.SSH_KEY} CAM={config.CAMERA_HOST}')")"
ok() { echo "  ✅ $*"; }
ng() { echo "  ❌ $*"; }
na() { echo "  ー $*"; }

echo "===== Raspberry Pi (solarcam) ====="
echo "  時刻: $(date '+%F %T') / 起動: $(uptime -s)"
if [ -z "$(git status --porcelain --untracked-files=no)" ]; then
  ok "コード: $(git log --oneline -1 | cut -c1-60)（GitHub の main と同じ）"
else
  ng "コード: ローカルで変更あり（git status で確認）"
fi

echo "[ネットワーク]"
echo "  eth0: $(nmcli -g GENERAL.CONNECTION device show eth0 2>/dev/null) $(ip -4 -br addr show eth0 | awk '{print $3}')"
ip route show default | sed 's/^/  経路: /'
ping -c1 -W3 -I eth0 8.8.8.8 >/dev/null 2>&1 && ok "LAN 経由でインターネットに出られる" \
  || na "LAN 経由のインターネットなし（現場ではこれが正常）"
ping -c1 -W3 -I wwan0 8.8.8.8 >/dev/null 2>&1 && ok "SIM 経由でインターネットに出られる" \
  || ng "SIM 経由で通信できない"
ts=$(tailscale status --peers=false 2>/dev/null | head -1)
[ -n "$ts" ] && ok "Tailscale: $(echo "$ts" | awk '{print $1, $2}')" || ng "Tailscale が動いていない"

echo "[カメラ・撮影]"
nc -z -w 3 "$CAM" 554 2>/dev/null && ok "カメラ $CAM に届く" || ng "カメラ $CAM に届かない"
last_ok=$(grep "撮影完了" capture.log 2>/dev/null | tail -1 | cut -c1-19)
last_ng=$(grep "リトライ上限" capture.log 2>/dev/null | tail -1 | cut -c1-19)
echo "  最後の撮影成功: ${last_ok:-なし} / 最後の撮影失敗: ${last_ng:-なし}"
n=$(ls retry/*.jpg 2>/dev/null | wc -l)
[ "$n" -eq 0 ] && ok "再送待ちの画像なし" || ng "再送待ちの画像 ${n} 枚（retry/）"
p=0; [ -f network_alert_pending.txt ] && p=$(wc -l < network_alert_pending.txt)
[ "$p" -eq 0 ] && ok "未送信の異常通知なし" || ng "未送信の異常通知 ${p} 件"

echo "[cron]"
crontab -l 2>/dev/null | grep -vE '^\s*(#|$)' | sed -E 's#/usr/bin/python3 /home/pi/solar/##; s#>>.*##; s/^/  /'

echo
echo "===== ConoHa ====="
ssh -i "$K" -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new "$H" 'bash -s' <<'REMOTE' || ng "ConoHa に接続できない"
ok() { echo "  ✅ $*"; }
ng() { echo "  ❌ $*"; }
W=/var/www/html/solar
latest=$(ls "$W/images" | grep -E '^[0-9]{8}_[0-9]{4}\.jpg$' | sort | tail -1)
echo "  最新画像: ${latest:-なし}（今日 $(ls "$W/images" | grep -c "^$(date +%Y%m%d)_") 枚）"
[ -e "$W/trigger" ] && echo "  ー 手動撮影のトリガーあり（2分以内に撮影される）" || ok "手動撮影のトリガーなし（待機中）"
systemctl is-active --quiet solar-trigger && ok "「今すぐ撮影」の受け口（solar-trigger）稼働中" || ng "solar-trigger が止まっている"
curl -s -m 5 -o /dev/null https://solar.redeye-lab.com/ -w '%{http_code}' | grep -q 200 && ok "閲覧サイト応答あり" || ng "閲覧サイトが応答しない"
[ -f ~/.solar_mail.conf ] && ok "メール設定あり（~/.solar_mail.conf）" || ng "メール設定なし"
st=$(cat ~/check_rpi_state.json 2>/dev/null)
case "$st" in *alerted*true*) ng "撮影停止アラート発信中: $st" ;; *) ok "撮影停止アラートなし" ;; esac
echo "  停止監視の最終確認: $(tail -1 ~/check_rpi.log 2>/dev/null)"
a=0; [ -f "$W/network_alert.txt" ] && a=$(wc -l < "$W/network_alert.txt")
echo "  今夜20:30のメールに載る異常: ${a} 件"
echo "  ディスク使用率: $(df -h / | awk 'NR==2{print $5}')"
echo "[cron]"
crontab -l 2>/dev/null | grep -vE '^\s*(#|$)' | sed -E 's#/usr/bin/python3 /home/solar/##; s#>>.*##; s/^/  /'
REMOTE
