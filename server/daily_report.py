#!/usr/bin/env python3
"""毎日のレポートメール（ConoHa の cron: 30 20 * * *）。

Raspberry Pi から追記されたネットワーク異常ログ (network_alert.txt) と
通信量レポート (traffic_report.txt) があればメールし、送信後は
~/archive/ に全件を追記保存してから元のファイルを削除する。
どちらも無ければ送らない。

メールに載せる異常ログは、直近 MAIL_MAX_DAYS 日以内・最新 MAIL_MAX_LINES 件まで。
それ以外は件数だけ記載する（全件は ~/archive/network_alert.log に残る）。
"""
import os, re
from datetime import datetime, timedelta
import mailer

ALERT_FILE = "/var/www/html/solar/network_alert.txt"
TRAFFIC_FILE = "/var/www/html/solar/traffic_report.txt"
ARCHIVE_DIR = os.path.expanduser("~/archive")
SITE = "https://solar.redeye-lab.com"
MAIL_MAX_LINES = 20
MAIL_MAX_DAYS = 60
TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


def read(path):
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def summarize_alerts(text, now):
    """メール用に、古い行と多すぎる行を省いた本文を返す。"""
    lines = [l for l in text.splitlines() if l.strip()]
    cutoff = now - timedelta(days=MAIL_MAX_DAYS)
    recent, old = [], 0
    for l in lines:
        m = TS_RE.match(l)
        if m and datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S") < cutoff:
            old += 1
        else:
            recent.append(l)
    shown = recent[-MAIL_MAX_LINES:]
    hidden = len(recent) - len(shown)
    notes = []
    if hidden:
        notes.append(f"ほか {hidden} 件は省略（最新 {MAIL_MAX_LINES} 件のみ表示）")
    if old:
        notes.append(f"{MAIL_MAX_DAYS} 日より前の {old} 件は省略")
    body = "\n".join(shown)
    if notes:
        body += "\n※ " + " / ".join(notes) + "。全件はサーバーの ~/archive/network_alert.log に保存"
    return f"【ネットワーク異常ログ】全 {len(lines)} 件\n{body}\n"


def archive(path, name, now):
    """元ファイルの内容を ~/archive/<name> に追記してから削除する。"""
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    with open(path, encoding="utf-8") as src, \
         open(os.path.join(ARCHIVE_DIR, name), "a", encoding="utf-8") as dst:
        dst.write(f"# ---- {now:%Y-%m-%d %H:%M} 送信分 ----\n")
        dst.write(src.read().rstrip("\n") + "\n")
    os.remove(path)


def main(now=None):
    now = now or datetime.now()
    today = now.strftime("%Y/%m/%d")
    alert, traffic = read(ALERT_FILE), read(TRAFFIC_FILE)
    if not alert and not traffic:
        print("送信なし")
        return

    body = f"太陽光発電所 監視システム レポート\n日付：{today}\n\n"
    if alert:
        body += summarize_alerts(alert, now)
    if traffic:
        body += f"\n{traffic}\n"
    body += f"---\n{SITE}"
    subject = (f"[要確認] 監視カメラ 異常あり {today}" if alert
               else f"[監視カメラ] レポート {today}")

    if mailer.send(subject, body):
        print("メール送信成功")
        if alert:
            archive(ALERT_FILE, "network_alert.log", now)
        if traffic:
            archive(TRAFFIC_FILE, "traffic_report.log", now)


if __name__ == "__main__":
    main()
