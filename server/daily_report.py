#!/usr/bin/env python3
"""毎日のレポートメール（ConoHa の cron: 30 20 * * *）。

Raspberry Pi から追記されたネットワーク異常ログ (network_alert.txt) と
通信量レポート (traffic_report.txt) があればメールし、送信後に削除する。
どちらも無ければ送らない。
"""
import os
from datetime import datetime
import mailer

ALERT_FILE = "/var/www/html/solar/network_alert.txt"
TRAFFIC_FILE = "/var/www/html/solar/traffic_report.txt"
SITE = "https://solar.redeye-lab.com"


def read(path):
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def main():
    today = datetime.now().strftime("%Y/%m/%d")
    alert, traffic = read(ALERT_FILE), read(TRAFFIC_FILE)
    if not alert and not traffic:
        print("送信なし")
        return

    body = f"太陽光発電所 監視システム レポート\n日付：{today}\n\n"
    if alert:
        body += f"【ネットワーク異常ログ】\n{alert}\n"
    if traffic:
        body += f"\n{traffic}\n"
    body += f"---\n{SITE}"
    subject = (f"[要確認] 監視カメラ 異常あり {today}" if alert
               else f"[監視カメラ] レポート {today}")

    if mailer.send(subject, body):
        print("メール送信成功")
        for path, has in ((ALERT_FILE, alert), (TRAFFIC_FILE, traffic)):
            if has:
                os.remove(path)


if __name__ == "__main__":
    main()
