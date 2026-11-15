#!/usr/bin/env python3
"""eth0 の疎通を監視し、本当に切れているときだけ再接続・通知する。

DHCP更新などで eth0 の IP が一瞬消えるだけのケースは、猶予時間内に
復帰すれば障害とみなさない（誤検知で毎時アラートが飛ぶのを防ぐ）。
"""
import subprocess, time, os
from datetime import datetime
import config

ALERT = getattr(config, "NETWORK_ALERT_LOCAL", "/home/pi/solar/network_alert.txt")
IFACE = getattr(config, "NET_IFACE", "eth0")
NM_CONN = getattr(config, "NM_CONNECTION", "eth0-auto")

GRACE_CHECKS = 4        # 切断判定までの再確認回数
GRACE_INTERVAL = 5      # 再確認の間隔(秒)
MAX_ALERT_LINES = 200   # 通知ファイルに残す最大行数


def log(msg):
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}\n"
    lines = []
    if os.path.exists(ALERT):
        with open(ALERT) as f:
            lines = f.readlines()
    lines.append(line)
    with open(ALERT, "w") as f:
        f.writelines(lines[-MAX_ALERT_LINES:])


def has_ip():
    r = subprocess.run(["ip", "-4", "addr", "show", IFACE],
                       capture_output=True, text=True)
    return "inet " in r.stdout


def gateway_reachable():
    r = subprocess.run(["ip", "route", "show", "default", "dev", IFACE],
                       capture_output=True, text=True)
    parts = r.stdout.split()
    if "via" not in parts:
        return False
    gw = parts[parts.index("via") + 1]
    return subprocess.run(["ping", "-c", "1", "-W", "2", gw],
                          capture_output=True).returncode == 0


def is_healthy():
    return has_ip() and gateway_reachable()


def confirmed_down():
    """猶予時間内に一度でも復帰すれば False。"""
    for i in range(GRACE_CHECKS):
        if is_healthy():
            return False
        if i < GRACE_CHECKS - 1:
            time.sleep(GRACE_INTERVAL)
    return True


def restart_iface():
    subprocess.run(["sudo", "nmcli", "connection", "down", NM_CONN],
                   capture_output=True)
    time.sleep(3)
    r = subprocess.run(["sudo", "nmcli", "connection", "up", NM_CONN],
                       capture_output=True)
    time.sleep(5)
    return r.returncode == 0 and is_healthy()


def send_alert_to_conoha():
    if not os.path.exists(ALERT):
        return
    subprocess.run([
        "scp", "-i", config.SSH_KEY,
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=10",
        ALERT,
        f"{config.CONOHA_USER}@{config.CONOHA_HOST}:{config.CONOHA_NETWORK_ALERT}"
    ], capture_output=True)


if confirmed_down():
    log(f"{IFACE}切断検出 → 再接続開始")
    ok = restart_iface()
    log(f"{IFACE}再接続" + ("完了" if ok else "失敗"))
    send_alert_to_conoha()
