#!/bin/bash
# タイマーコンセントの電源断（2:50〜2:55）に備えて SD カードを保護する。
# cron（pi ユーザー）から root で実行: 40 2 * * * sudo /home/pi/solar/power_cut_prepare.sh
#
# タイマーの時計の誤差（±4分/6か月程度）に備え、前後に余裕を取る:
#   2:40 読み取り専用 → 2:50 電源断（10分前倒しまで安全）→ 2:55 復電
#   → 3:10 までに電源が切れなければ自分で再起動（20分遅れまで安全）
#
#   1. 書き込みを全部終え、SD カードを読み取り専用にする（Pi は動いたまま）
#      → この状態で電源が切れても SD カードは壊れない
#   2. WAIT 秒（既定 30 分）たっても電源が切れなければ、自分で再起動する
#      → タイマー未設置・故障・時刻ずれでも、Pi が止まったままにならない
#        （単純な shutdown だと、電源が入れ直されるまで起動しない）
set -u
WAIT="${1:-1800}"
LOG=/home/pi/solar/network.log

echo "$(date '+%F %T') 電源断の準備: SDカードを読み取り専用にします（${WAIT}秒以内に電源が切れなければ再起動）" >> "$LOG"
fake-hwclock save 2>/dev/null   # 再起動後に使う時刻を保存（NTP で正確な時刻に直るまでのつなぎ）
sync
echo s > /proc/sysrq-trigger    # ディスクへ書き出し
sleep 2
echo u > /proc/sysrq-trigger    # 全ファイルシステムを読み取り専用に再マウント
sleep "$WAIT"
# ここまで来た = 電源が切れなかった。読み取り専用のまま安全に再起動する
echo b > /proc/sysrq-trigger
