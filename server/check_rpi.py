#!/usr/bin/env python3
"""撮影停止の監視（ConoHa の cron で毎時実行: 0 * * * *）。

撮影予定（START_HOUR〜END_HOUR 時の毎時0分）と最新画像の時刻を比べ、
予定時刻から GRACE_MIN 分過ぎても届かなかった回数が MISS_THRESHOLD 回に
なったら停止アラートを1回送る。画像が届き始めたら復旧を通知する。
夜間は撮影予定が無いので、朝4時に前日20時の画像を見て誤報することはない。

  check_rpi.py         通常の監視
  check_rpi.py --test  テストメールを送る（設定確認用）
"""
import glob, json, os, re, sys
from datetime import datetime, timedelta
import mailer

IMAGE_DIR = "/var/www/html/solar/images"
STATE = os.path.expanduser("~/check_rpi_state.json")
START_HOUR, END_HOUR = 4, 20
GRACE_MIN = 10
MISS_THRESHOLD = 2
SITE = "https://solar.redeye-lab.com"
NAME_RE = re.compile(r"(\d{8}_\d{4})\.jpg$")


def log(msg):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}", flush=True)


def latest_image(image_dir=IMAGE_DIR):
    """(ファイル名, 撮影時刻) を返す。無ければ (None, None)。"""
    names = [m.group(1) for f in glob.glob(f"{image_dir}/*.jpg")
             if (m := NAME_RE.search(os.path.basename(f)))]
    if not names:
        return None, None
    name = max(names)
    return f"{name}.jpg", datetime.strptime(name, "%Y%m%d_%H%M")


def missed_slots(last, now):
    """last より後で、届いているはずなのに届いていない撮影予定の回数。"""
    t = last.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    deadline = now - timedelta(minutes=GRACE_MIN)
    missed = 0
    while t <= deadline and missed < 1000:
        if START_HOUR <= t.hour <= END_HOUR:
            missed += 1
        t += timedelta(hours=1)
    return missed


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(s):
    with open(STATE, "w") as f:
        json.dump(s, f)


def main(now=None):
    now = now or datetime.now()
    name, last = latest_image()
    missed = missed_slots(last, now) if last else MISS_THRESHOLD
    state = load_state()
    log(f"状態確認: 最新画像 {name or 'なし'} / 未着 {missed} 回")

    if missed >= MISS_THRESHOLD and not state.get("alerted"):
        body = (f"太陽光発電所 監視カメラ 停止アラート\n"
                f"確認日時：{now:%Y/%m/%d %H:%M}\n\n"
                f"最新画像：{name or 'なし'}\n"
                f"予定どおり届いていない撮影：{missed} 回\n\n"
                f"Raspberry Pi・カメラ・SIM通信のいずれかが止まっている可能性があります。\n"
                f"  1. ssh pi@solarcam（Tailscale）で接続し tail ~/solar/capture.log を確認\n"
                f"  2. 接続できない場合は現地で電源を確認\n\n"
                f"カメラページ：{SITE}")
        if mailer.send(f"[緊急] 監視カメラ停止の可能性 {now:%Y/%m/%d %H:%M}", body):
            state.update(alerted=True, alerted_at=f"{now:%Y-%m-%d %H:%M}")
            log("停止アラート送信")
    elif missed < MISS_THRESHOLD and state.get("alerted"):
        body = (f"太陽光発電所 監視カメラ 撮影再開\n"
                f"確認日時：{now:%Y/%m/%d %H:%M}\n\n"
                f"最新画像：{name}\n"
                f"停止アラート：{state.get('alerted_at', '-')}\n\n"
                f"カメラページ：{SITE}")
        if mailer.send(f"[復旧] 監視カメラ撮影再開 {now:%Y/%m/%d %H:%M}", body):
            state = {}
            log("復旧通知送信")
    save_state(state)


if __name__ == "__main__":
    if "--test" in sys.argv:
        ok = mailer.send("[テスト] 監視カメラ 通知テスト",
                         f"check_rpi.py からのテストメールです。\n{datetime.now():%Y/%m/%d %H:%M}")
        print("テストメール送信成功" if ok else "テストメール送信失敗")
        sys.exit(0 if ok else 1)
    main()
