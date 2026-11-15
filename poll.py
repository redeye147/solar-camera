#!/usr/bin/env python3
import subprocess, os, glob, sys
import config

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
RETRY_DIR = getattr(config, "RETRY_DIR", os.path.join(BASE_DIR, "retry"))
os.makedirs(RETRY_DIR, exist_ok=True)

# リトライ転送
for f in sorted(glob.glob(f"{RETRY_DIR}/*.jpg")):
    r = subprocess.run([
        "scp", "-i", config.SSH_KEY,
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=15",
        f, f"{config.CONOHA_USER}@{config.CONOHA_HOST}:{config.CONOHA_IMG_DIR}/"
    ], capture_output=True)
    if r.returncode == 0:
        print(f"✅ リトライ転送成功: {os.path.basename(f)}")
        os.remove(f)
    else:
        print(f"❌ リトライ失敗: {os.path.basename(f)}")
        break

# トリガー確認
result = subprocess.run([
    "ssh", "-i", config.SSH_KEY,
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "ConnectTimeout=10",
    f"{config.CONOHA_USER}@{config.CONOHA_HOST}",
    f"test -f {config.CONOHA_TRIGGER} && echo yes || echo no"
], capture_output=True, text=True, timeout=20)

if result.stdout.strip() == "yes":
    print("トリガー検出 → 撮影開始")
    subprocess.run([
        sys.executable,
        os.path.join(BASE_DIR, "capture.py")
    ])
    subprocess.run([
        "ssh", "-i", config.SSH_KEY,
        "-o", "StrictHostKeyChecking=accept-new",
        f"{config.CONOHA_USER}@{config.CONOHA_HOST}",
        f"rm -f {config.CONOHA_TRIGGER}"
    ])
    print("完了・trigger削除")
else:
    print("トリガーなし")
