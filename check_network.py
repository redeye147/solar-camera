#!/usr/bin/env python3
"""インターネット疎通を監視し、断のときだけ段階的に復旧・記録する。

構成の前提:
  - 主回線: SIMドングル (NetworkManager の gsm 接続, metric 700)
  - 予備  : eth0 (eth0-auto, metric 800)。現場ではカメラ用LAN
  経路の優先は NetworkManager の metric に任せ、本スクリプトは
  「どの経路でもいいのでインターネットに出られるか」だけを見る。

復旧の段階:
  1. SIM接続の張り直し (nmcli down/up)
  2. モデムのリセット (mmcli --reset)
  3. LAN接続の張り直し
  4. それでも断が続けば NET_REBOOT_AFTER_RUNS 回ごとに再起動

通知: 断の最中はConoHaへ送れないため、復旧時・経路変更時に
      network_alert.txt (直近 MAX_ALERT_LINES 行) を送る。

cron 例: */5 * * * * /usr/bin/python3 /home/pi/solar/check_network.py
"""
import fcntl, json, os, subprocess, sys, time
from datetime import datetime
import config

BASE = os.path.dirname(os.path.abspath(__file__))
ALERT = getattr(config, "NETWORK_ALERT_LOCAL", os.path.join(BASE, "network_alert.txt"))
STATE = getattr(config, "NETWORK_STATE", os.path.join(BASE, "network_state.json"))
LOCK = os.path.join(BASE, ".check_network.lock")

GSM_CONN = getattr(config, "GSM_CONNECTION", "nihontsushin")
LAN_CONN = getattr(config, "NM_CONNECTION", "eth0-auto")
TARGETS = getattr(config, "PING_TARGETS", ["1.1.1.1", "8.8.8.8"])
REBOOT_AFTER = getattr(config, "NET_REBOOT_AFTER_RUNS", 6)  # 0 で再起動しない

GRACE_CHECKS = 4        # 断と判定するまでの確認回数
GRACE_INTERVAL = 5      # 確認間隔(秒)
MAX_ALERT_LINES = 200


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    lines = []
    if os.path.exists(ALERT):
        with open(ALERT) as f:
            lines = f.readlines()
    lines.append(f"{now()} {msg}\n")
    with open(ALERT, "w") as f:
        f.writelines(lines[-MAX_ALERT_LINES:])
    print(msg)


def run(cmd, timeout=60):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None


def online():
    for t in TARGETS:
        r = run(["ping", "-c", "1", "-W", "3", t], timeout=10)
        if r and r.returncode == 0:
            return True
    return False


def confirmed_offline():
    """猶予時間内に一度でも疎通すれば False (一瞬の瞬断は無視)。"""
    for i in range(GRACE_CHECKS):
        if online():
            return False
        if i < GRACE_CHECKS - 1:
            time.sleep(GRACE_INTERVAL)
    return True


def route_dev():
    """インターネット向けに実際に使われているインターフェース名。"""
    r = run(["ip", "route", "get", TARGETS[0]])
    if not r or r.returncode != 0:
        return None
    parts = r.stdout.split()
    return parts[parts.index("dev") + 1] if "dev" in parts else None


def nmcli(*args, timeout=90):
    return run(["sudo", "nmcli", *args], timeout=timeout)


def step_sim_reconnect():
    nmcli("connection", "down", GSM_CONN)
    time.sleep(3)
    nmcli("connection", "up", GSM_CONN)


def step_modem_reset():
    run(["sudo", "mmcli", "-m", "any", "--reset"], timeout=30)
    time.sleep(60)  # モデム再認識待ち
    nmcli("connection", "up", GSM_CONN)


def step_lan_reconnect():
    nmcli("connection", "up", LAN_CONN)


RECOVERY_STEPS = [
    ("SIM再接続", step_sim_reconnect),
    ("モデムリセット", step_modem_reset),
    ("LAN再接続", step_lan_reconnect),
]


def recover():
    for name, fn in RECOVERY_STEPS:
        fn()
        time.sleep(10)
        if online():
            return name
    return None


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(s):
    with open(STATE, "w") as f:
        json.dump(s, f)


def send_alert_to_conoha():
    if not os.path.exists(ALERT):
        return
    run([
        "scp", "-i", config.SSH_KEY,
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=15",
        ALERT,
        f"{config.CONOHA_USER}@{config.CONOHA_HOST}:{config.CONOHA_NETWORK_ALERT}",
    ], timeout=60)


def minutes_since(ts):
    t = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    return int((datetime.now() - t).total_seconds() // 60)


def on_online(state):
    dev = route_dev()
    notify = False
    if state.get("down_since"):
        log(f"インターネット復旧 (経路: {dev}, 断 {minutes_since(state['down_since'])}分)")
        notify = True
    elif state.get("dev") and dev and dev != state["dev"]:
        log(f"経路変更 {state['dev']} → {dev}")
        notify = True
    save_state({"dev": dev})
    if notify:
        send_alert_to_conoha()


def on_offline(state):
    if not state.get("down_since"):
        state["down_since"] = now()
        log(f"インターネット断を検出 (経路: {route_dev()})")
    state["fail_runs"] = state.get("fail_runs", 0) + 1

    how = recover()
    if how:
        log(f"復旧処理成功: {how} (経路: {route_dev()})")
        on_online(state)
        return

    log(f"復旧処理失敗 ({state['fail_runs']}回目)")
    save_state(state)
    if REBOOT_AFTER and state["fail_runs"] % REBOOT_AFTER == 0:
        log("断が続いているため再起動します")
        run(["sudo", "reboot"])


def main():
    lock = open(LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(0)  # 前回の実行(復旧処理中)がまだ動いている

    state = load_state()
    if online() or not confirmed_offline():
        on_online(state)
    else:
        on_offline(state)


if __name__ == "__main__":
    main()
