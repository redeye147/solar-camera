#!/bin/bash
# Raspberry Pi から ConoHa へサーバー側スクリプト（server/）と閲覧サイトの画面
# （index.html / monthly.html）を配置する。
#   cd ~/solar && server/deploy.sh
# - 初回のみ、既存の daily_report.py から Gmail 認証情報を取り出して
#   ~/.solar_mail.conf (chmod 600) を作る（パスワードは表示しない）
# - 既存のスクリプトは ~/backup_日時/ に退避してから入れ替える
#   元に戻すとき: ConoHa で cp -p ~/backup_日時/*.py ~/
set -euo pipefail
cd "$(dirname "$0")/.."
eval "$(python3 -c "import config;print(f'H={config.CONOHA_USER}@{config.CONOHA_HOST} K={config.SSH_KEY} W={config.CONOHA_REMOTE_BASE}')")"
SSH_OPTS=(-i "$K" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15)

ssh "${SSH_OPTS[@]}" "$H" 'bash -s' <<'REMOTE'
set -e
cd ~
if [ ! -f .solar_mail.conf ] && [ -f daily_report.py ]; then
  python3 - <<'PY'
import json, os, re
src = open(os.path.expanduser("~/daily_report.py")).read()
g = lambda k: re.search(rf'^{k}\s*=\s*["\'](.*?)["\']', src, re.M).group(1)
p = os.path.expanduser("~/.solar_mail.conf")
fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as f:
    json.dump({"user": g("GMAIL_USER"), "password": g("GMAIL_PASS"), "to": g("TO_ADDR")}, f)
print("メール設定を作成しました: ~/.solar_mail.conf（既存の daily_report.py から）")
PY
fi
test -f .solar_mail.conf || { echo "~/.solar_mail.conf がありません（server/mail.conf.example 参照）"; exit 1; }
b=backup_$(date +%Y%m%d_%H%M%S); mkdir -p "$b"
for f in mailer.py check_rpi.py daily_report.py; do
  if [ -e "$f" ]; then cp -p "$f" "$b/"; rm -f "$f"; fi
done
echo "既存スクリプトの退避先: ~/$b"
REMOTE

scp "${SSH_OPTS[@]}" server/mailer.py server/check_rpi.py server/daily_report.py "$H":
scp "${SSH_OPTS[@]}" index.html monthly.html "$H:$W/"   # 閲覧サイトの画面
echo "配置完了。動作確認:"
ssh "${SSH_OPTS[@]}" "$H" 'cd ~ && python3 check_rpi.py'
