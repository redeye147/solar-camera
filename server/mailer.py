#!/usr/bin/env python3
"""ConoHa 側スクリプト共通のメール送信。

認証情報はリポジトリに置かず、~/.solar_mail.conf (JSON, chmod 600) から読む:
  {"user": "xxx@gmail.com", "password": "Gmailのアプリパスワード", "to": "xxx@gmail.com"}
"""
import json, os, smtplib
from email.header import Header
from email.mime.text import MIMEText

CONF = os.environ.get("SOLAR_MAIL_CONF", os.path.expanduser("~/.solar_mail.conf"))


def send(subject, body):
    """送信できたら True。失敗時は理由を表示して False。"""
    try:
        with open(CONF) as f:
            conf = json.load(f)
    except (OSError, ValueError) as e:
        print(f"メール設定を読めません ({CONF}): {e}")
        return False
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = conf["user"]
    msg["To"] = conf.get("to", conf["user"])
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30,
                              local_hostname=conf.get("local_hostname", "solarcam")) as smtp:
            smtp.login(conf["user"], conf["password"])
            smtp.send_message(msg)
        return True
    except Exception as e:
        print(f"メール送信失敗: {type(e).__name__}: {e}")
        return False
