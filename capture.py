#!/usr/bin/env python3
import subprocess, datetime, os, io
from PIL import Image
import config

TMP_RAW   = "/tmp/capture_raw.jpg"
TMP_DIR   = "/tmp/solar"
MAX_BYTES = 62500
RESIZE_W  = 1280

os.makedirs(TMP_DIR, exist_ok=True)

print("撮影中...")
result = subprocess.run([
    "ffmpeg", "-y",
    "-rtsp_transport", "tcp",
    "-i", config.RTSP_URL,
    "-frames:v", "1",
    "-q:v", "2",
    "-update", "1",
    TMP_RAW
], capture_output=True, timeout=30)

if not os.path.exists(TMP_RAW):
    print("撮影失敗")
    print(result.stderr.decode())
    exit(1)

img = Image.open(TMP_RAW)
img = img.resize((RESIZE_W, int(img.height * RESIZE_W / img.width)))

quality = 70
while quality >= 10:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    if buf.tell() <= MAX_BYTES:
        break
    quality -= 5

timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
out_path = f"{TMP_DIR}/{timestamp}.jpg"
with open(out_path, "wb") as f:
    f.write(buf.getvalue())

size_kb = buf.tell() / 1024
print(f"✅ 完了: {out_path}")
print(f"   サイズ: {size_kb:.1f}KB / quality={quality}")
os.remove(TMP_RAW)

# ConoHaへSCP転送
result = subprocess.run([
    "scp",
    "-i", config.SSH_KEY,
    "-o", "StrictHostKeyChecking=no",
    "-o", "ConnectTimeout=30",
    out_path,
    f"{config.CONOHA_USER}@{config.CONOHA_HOST}:{config.CONOHA_IMG_DIR}/"
], capture_output=True)

if result.returncode == 0:
    print("✅ ConoHa転送成功")
    os.remove(out_path)
else:
    print("❌ 転送失敗:", result.stderr.decode())
