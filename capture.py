#!/usr/bin/env python3
"""RTSPカメラから1枚撮影し、リサイズ・圧縮してConoHaへ転送する。

カメラが一時的に応答しない（Connection refused など）ことがあるため、
失敗時は CAPTURE_RETRY_WAIT 秒待って最大 CAPTURE_RETRIES 回まで撮り直す。
ファイル名の時刻は撮影開始時刻で固定する（:00 撮影が撮り直しで :01 になり
「手動」と誤表示されるのを防ぐ）。
"""
import subprocess, datetime, os, io, shutil, sys, time
from PIL import Image
import config
import conoha_ssh

TMP_RAW   = "/tmp/capture_raw.jpg"
TMP_DIR   = "/tmp/solar"
RETRY_DIR = getattr(config, "RETRY_DIR",
                    os.path.join(os.path.dirname(os.path.abspath(__file__)), "retry"))
MAX_BYTES = 62500
RESIZE_W  = 1280
RETRIES   = getattr(config, "CAPTURE_RETRIES", 3)
RETRY_WAIT = getattr(config, "CAPTURE_RETRY_WAIT", 15)  # 秒
# 終了コード: 0=撮影・転送成功 / 1=撮影失敗 / 2=撮影成功・転送失敗(retryへ退避)


def log(msg):
    print(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {msg}", flush=True)


def mask(text):
    return text.replace(config.CAMERA_PASS, "****") if config.CAMERA_PASS else text


def grab_frame():
    """1フレーム取得。成功で None、失敗でエラー文字列を返す。"""
    if os.path.exists(TMP_RAW):
        os.remove(TMP_RAW)  # 前回の残骸で成功と誤判定しないように
    try:
        r = subprocess.run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-rtsp_transport", "tcp",
            "-timeout", "10000000",          # RTSP接続のタイムアウト(マイクロ秒)
            "-i", config.RTSP_URL,
            "-frames:v", "1",
            "-q:v", "2",
            "-update", "1",
            TMP_RAW,
        ], capture_output=True, timeout=40)
    except subprocess.TimeoutExpired:
        return "ffmpeg タイムアウト(40秒)"
    if os.path.exists(TMP_RAW) and os.path.getsize(TMP_RAW) > 0:
        return None
    return mask(r.stderr.decode(errors="replace").strip()) or f"ffmpeg 終了コード {r.returncode}"


os.makedirs(TMP_DIR, exist_ok=True)
os.makedirs(RETRY_DIR, exist_ok=True)

timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")  # 撮影開始時刻で固定
log(f"撮影開始 ({timestamp})")

for attempt in range(1, RETRIES + 1):
    err = grab_frame()
    if err is None:
        break
    log(f"撮影失敗 ({attempt}/{RETRIES}回目): {err}")
    if attempt < RETRIES:
        time.sleep(RETRY_WAIT)
else:
    log("撮影失敗: リトライ上限に達しました")
    sys.exit(1)

img = Image.open(TMP_RAW)
img = img.resize((RESIZE_W, int(img.height * RESIZE_W / img.width)))

quality = 70
while quality >= 10:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    if buf.tell() <= MAX_BYTES:
        break
    quality -= 5

out_path = f"{TMP_DIR}/{timestamp}.jpg"
with open(out_path, "wb") as f:
    f.write(buf.getvalue())
os.remove(TMP_RAW)
log(f"✅ 撮影完了: {out_path} ({buf.tell() / 1024:.1f}KB / quality={quality})")

# ConoHaへSCP転送
result = conoha_ssh.scp_to(out_path, f"{config.CONOHA_IMG_DIR}/")  # 接続を使い回す

if conoha_ssh.ok(result):
    log("✅ ConoHa転送成功")
    os.remove(out_path)
else:
    log(f"❌ 転送失敗 → retryへ退避: {conoha_ssh.err(result)}")
    shutil.move(out_path, os.path.join(RETRY_DIR, os.path.basename(out_path)))
    sys.exit(2)  # 撮影は成功・転送待ち（poll.py が再送する）
