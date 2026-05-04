#!/usr/bin/env python3
import subprocess, time, os
from datetime import datetime
import config

LOG   = "/home/pi/solar/network.log"
ALERT = "/home/pi/solar/network_alert.txt"

def log(msg):
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}\n"
    with open(ALERT, 'a') as f:
        f.write(line)

def check_eth0():
    result = subprocess.run(
        ['ip', 'addr', 'show', 'eth0'],
        capture_output=True, text=True)
    return 'inet ' in result.stdout

def restart_eth0():
    subprocess.run(['sudo', 'nmcli', 'connection', 'down', 'eth0-auto'])
    time.sleep(3)
    result = subprocess.run(
        ['sudo', 'nmcli', 'connection', 'up', 'eth0-auto'],
        capture_output=True)
    if result.returncode == 0:
        log("eth0再接続完了")
    else:
        log("eth0再接続失敗")

def send_alert_to_conoha():
    if not os.path.exists(ALERT):
        return
    subprocess.run([
        "scp", "-i", config.SSH_KEY,
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        ALERT,
        f"{config.CONOHA_USER}@{config.CONOHA_HOST}:{config.CONOHA_NETWORK_ALERT}"
    ], capture_output=True)

if not check_eth0():
    log("eth0切断検出 → 再接続開始")
    restart_eth0()
    send_alert_to_conoha()
