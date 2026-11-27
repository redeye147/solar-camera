#!/bin/bash
# 遠隔設置向けの自動更新（cron: 30 21 * * *）。GitHub の main に更新があれば、
# 安全を確かめながら適用し、だめなら自動で元の版に戻す。
#
#   1. 一時停止ファイル（.no_auto_update）があれば何もしない
#   2. 更新が無ければ何もしない
#   3. 更新前の健康診断（ネット・ConoHa・カメラ・Tailscale）。異常なら更新しない
#   4. 新しい版の文法チェック（Python・sh）。誤りがあれば更新しない
#   5. 適用（fast-forward のみ）
#   6. 約6分待ち（check_network・poll が新しいコードで動く）、健康診断と
#      ログのエラー（Traceback）を確認。だめなら元の版に戻す
#   7. server/ や画面のファイルが変わっていれば ConoHa へ配置（deploy.sh）
#   結果は異常通知（20:30 のメール）で知らせる。
#
# 使い方:
#   ./auto_update.sh --install   crontab に登録（何度実行しても1行だけ）
#   ./auto_update.sh             今すぐ実行（通常は cron から）
#   touch ~/solar/.no_auto_update で一時停止、rm で再開
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
CRON_LINE="30 21 * * * $DIR/auto_update.sh >> $DIR/update.log 2>&1"

if [ "${1:-}" = "--install" ]; then
  current=$(crontab -l 2>/dev/null)   # 先に全部読んでから書き込む（他の行を消さないため）
  { printf '%s\n' "$current" | grep -vF "auto_update.sh" | grep -v '^$'; echo "$CRON_LINE"; } | crontab -
  echo "登録しました:"; crontab -l | grep auto_update.sh | sed 's/^/  /'
  exit 0
fi

# 更新で自分自身が書き換わっても影響しないよう、一時コピーから実行し直す
if [ -z "${AUTO_UPDATE_COPY:-}" ]; then
  tmp=$(mktemp /tmp/auto_update.XXXXXX.sh)
  cp "$0" "$tmp" && chmod +x "$tmp"
  AUTO_UPDATE_COPY=1 AUTO_UPDATE_DIR="$DIR" exec "$tmp" "$@"
fi
DIR="${AUTO_UPDATE_DIR:-$DIR}"
cd "$DIR" || exit 1
trap 'rm -f "$0"' EXIT

WAIT_AFTER_UPDATE="${WAIT_AFTER_UPDATE:-370}"   # 秒。check_network（5分毎）が1回以上動くまで
LOGS="network.log poll.log capture.log"

ts() { date '+%F %T'; }
log() { echo "$(ts) $*"; }
notify() {   # 異常通知（check_network.py が次の実行で ConoHa へ送り、20:30 のメールに載る）
  local line="$(ts) $*"
  echo "$line"
  echo "$line" >> network_alert.txt
  echo "$line" >> network_alert_pending.txt
}

exec 9>"$DIR/.auto_update.lock"
flock -n 9 || { log "前回の自動更新がまだ動いているため終了"; exit 0; }

if [ -e .no_auto_update ]; then
  log "一時停止中（.no_auto_update あり）"; exit 0
fi

eval "$(python3 -c "import config;print(f'H={config.CONOHA_USER}@{config.CONOHA_HOST} K={config.SSH_KEY} CAM={config.CAMERA_HOST}')")"

health() {   # 正常なら 0。だめな項目を表示する
  local ng=""
  ping -c1 -W3 1.1.1.1 >/dev/null 2>&1 || ping -c1 -W3 8.8.8.8 >/dev/null 2>&1 || ng="$ng インターネット"
  ssh -i "$K" -o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new "$H" true \
    >/dev/null 2>&1 || ng="$ng ConoHa"
  nc -z -w 5 "$CAM" 554 >/dev/null 2>&1 || ng="$ng カメラ"
  tailscale status --peers=false >/dev/null 2>&1 || ng="$ng Tailscale"
  [ -z "$ng" ] && return 0
  echo "$ng"; return 1
}

health_retry() {   # 一時的な不調を除くため、1分おきに最大3回試す
  local i out
  for i in 1 2 3; do
    out=$(health) && return 0
    [ "$i" -lt 3 ] && sleep 60
  done
  echo "$out"; return 1
}

if ! git fetch -q origin main; then
  log "GitHub から取得できないため終了"; exit 0
fi
OLD=$(git rev-parse HEAD)
NEW=$(git rev-parse origin/main)
if [ "$OLD" = "$NEW" ]; then
  log "更新なし（$(git log -1 --format=%h)）"; exit 0
fi
if ! git merge-base --is-ancestor "$OLD" "$NEW"; then
  notify "自動更新を中止: 手元の版が GitHub の main より先に進んでいます（手動で確認してください）"; exit 0
fi
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  notify "自動更新を中止: Pi 上でファイルが直接変更されています（git status で確認してください）"; exit 0
fi

# 3. 更新前の健康診断
if ! out=$(health_retry); then
  notify "自動更新を見送り: 更新前から異常があります（${out# }）"; exit 0
fi

# 4. 新しい版の文法チェック（適用前に一時フォルダで）
work=$(mktemp -d)
git archive "$NEW" | tar -x -C "$work"
if ! err=$(python3 - "$work" <<'EOF' 2>&1
import pathlib, sys
bad = []
for p in pathlib.Path(sys.argv[1]).rglob("*.py"):
    try:
        compile(p.read_text(encoding="utf-8"), str(p), "exec")
    except SyntaxError as e:
        bad.append(f"{p.name}:{e.lineno}")
if bad:
    print(" ".join(bad)); sys.exit(1)
EOF
); then
  rm -rf "$work"; notify "自動更新を見送り: 新しい版に Python の文法エラー（$err）"; exit 0
fi
for f in $(cd "$work" && find . -name '*.sh'); do
  if ! bash -n "$work/$f" 2>/dev/null; then
    rm -rf "$work"; notify "自動更新を見送り: 新しい版に sh の文法エラー（$f）"; exit 0
  fi
done
rm -rf "$work"

# 5. 適用（ログの現在の大きさを記録しておき、更新後に増えた部分だけを調べる）
declare -A size
for f in $LOGS; do size[$f]=$( [ -f "$f" ] && stat -c %s "$f" || echo 0 ); done
CHANGED=$(git diff --name-only "$OLD" "$NEW")
git merge -q --ff-only "$NEW" || { notify "自動更新を中止: 適用に失敗"; exit 0; }
log "適用: $(git log -1 --format=%h "$OLD") → $(git log -1 --format='%h %s' "$NEW")"

# 6. 新しいコードがひと回り動くのを待ってから確認
sleep "$WAIT_AFTER_UPDATE"
problem=""
if ! out=$(health_retry); then problem="健康診断で異常（${out# }）"; fi
for f in $LOGS; do
  [ -f "$f" ] || continue
  if tail -c +"$(( ${size[$f]} + 1 ))" "$f" | grep -q "Traceback"; then
    problem="${problem:+$problem・}${f} にエラー"
  fi
done

if [ -n "$problem" ]; then
  git reset -q --hard "$OLD"
  notify "自動更新を元に戻しました: $(git log -1 --format=%h "$NEW") で問題（${problem}）。$(git log -1 --format=%h "$OLD") に戻しました"
  exit 0
fi

# 7. ConoHa 側のファイルが変わっていれば配置
if echo "$CHANGED" | grep -qE '^(server/|index\.html|monthly\.html)'; then
  if server/deploy.sh >/dev/null 2>&1; then
    log "ConoHa へ配置しました"
  else
    notify "自動更新: ConoHa への配置に失敗（Pi は更新済み。server/deploy.sh を手動で確認してください）"
  fi
fi
notify "自動更新しました: $(git log -1 --format=%h "$OLD") → $(git log -1 --format='%h %s' "$NEW")"
