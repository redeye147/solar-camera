#!/usr/bin/env python3
import subprocess
import config

result = subprocess.run([
    "ssh", "-i", config.SSH_KEY,
    "-o", "StrictHostKeyChecking=no",
    "-o", "ConnectTimeout=10",
    f"{config.CONOHA_USER}@{config.CONOHA_HOST}",
    f"test -f {config.CONOHA_TRIGGER} && echo yes || echo no"
], capture_output=True, text=True, timeout=20)

if result.stdout.strip() == "yes":
    print("トリガー検出 → 撮影開始")
    subprocess.run([
        "/usr/bin/python3",
        "/home/pi/solar/capture.py"
    ])
    subprocess.run([
        "ssh", "-i", config.SSH_KEY,
        "-o", "StrictHostKeyChecking=no",
        f"{config.CONOHA_USER}@{config.CONOHA_HOST}",
        f"rm -f {config.CONOHA_TRIGGER}"
    ])
    print("完了・trigger削除")
else:
    print("トリガーなし")
