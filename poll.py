#!/usr/bin/env python3
"""2分ごとに実行（cron）: 転送待ち画像の再送と、手動撮影トリガーの確認。

閲覧サイトの「今すぐ撮影」→ ConoHa に trigger ファイル → ここで撮影し、
結果を ConoHa の capture_result.json に書いてから trigger を消す。
画面（index.html）は capture_result.json を見て成功・失敗を表示する。
"""
import fcntl, glob, json, os, subprocess, sys, time
import config
import conoha_ssh

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
RETRY_DIR = getattr(config, "RETRY_DIR", os.path.join(BASE_DIR, "retry"))
RESULT    = getattr(config, "CONOHA_CAPTURE_RESULT",
                    f"{os.path.dirname(config.CONOHA_TRIGGER)}/capture_result.json")
MESSAGES  = {
    "ok": "撮影しました",
    "upload_pending": "撮影しましたが転送に失敗しました（自動で再送します）",
    "failed": "撮影に失敗しました（カメラが応答しません）",
}
os.makedirs(RETRY_DIR, exist_ok=True)

# 撮影や再送が長引いて次の poll（2分後）と重なったら、後のほうは何もしない
_lock = open(os.path.join(BASE_DIR, ".poll.lock"), "w")
try:
    fcntl.flock(_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    print("前回の poll がまだ動いているため終了")
    sys.exit(0)


ssh = conoha_ssh.ssh  # 接続を使い回す（通信量を減らすため）


# 転送待ち画像の再送
for f in sorted(glob.glob(f"{RETRY_DIR}/*.jpg")):
    if conoha_ssh.ok(conoha_ssh.scp_to(f, f"{config.CONOHA_IMG_DIR}/")):
        print(f"✅ リトライ転送成功: {os.path.basename(f)}")
        os.remove(f)
    else:
        print(f"❌ リトライ失敗: {os.path.basename(f)}")
        break

# 手動撮影トリガーの確認
r = ssh(f"test -f {config.CONOHA_TRIGGER} && echo yes || echo no", timeout=20)
if not r or r.stdout.strip() != "yes":
    print("トリガーなし" if r else "ConoHa に接続できません")
    sys.exit(0)

print("トリガー検出 → 撮影開始")
rc = subprocess.run([sys.executable, os.path.join(BASE_DIR, "capture.py")]).returncode
status = {0: "ok", 2: "upload_pending"}.get(rc, "failed")
result = {"status": status, "message": MESSAGES[status], "finished_ts": int(time.time())}
ssh(f"cat > {RESULT}", data=json.dumps(result, ensure_ascii=False))  # trigger を消す前に結果を書く
ssh(f"rm -f {config.CONOHA_TRIGGER}")
print(f"完了・trigger削除（結果: {status}）")
