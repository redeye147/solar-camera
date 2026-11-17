#!/usr/bin/env python3
"""当月の毎日12:00画像をグリッド合成し、月次サマリー画像として転送する。

毎日実行すると、その月の途中経過が更新されていく（cron 例: 5 21 * * *）。
"""
import subprocess, os, calendar, math
from datetime import datetime
from PIL import Image, ImageDraw
import config

TMP_DIR = "/tmp/solar_monthly"
COLS    = 6
CELL_W  = 213
CELL_H  = 160
LABEL_H = 20
SSH_OPTS = ["-i", config.SSH_KEY,
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ConnectTimeout=15"]
REMOTE = f"{config.CONOHA_USER}@{config.CONOHA_HOST}"

os.makedirs(TMP_DIR, exist_ok=True)

today = datetime.now()
year, month = today.year, today.month
days = calendar.monthrange(year, month)[1]
ym = f"{year}{month:02d}"

print(f"{year}年{month}月の合成開始（{days}日分）")

# ConoHa上の画像一覧を取得し、存在するものだけ取りに行く
r = subprocess.run(["ssh", *SSH_OPTS, REMOTE, f"ls {config.CONOHA_IMG_DIR}/"],
                   capture_output=True, text=True, timeout=60)
available = set(r.stdout.split())

images = []
for day in range(1, days + 1):
    fname = f"{ym}{day:02d}_1200.jpg"
    local = f"{TMP_DIR}/{fname}"
    if fname in available:
        r = subprocess.run(["scp", *SSH_OPTS,
                            f"{REMOTE}:{config.CONOHA_IMG_DIR}/{fname}", local],
                           capture_output=True, timeout=120)
        if r.returncode == 0:
            images.append((day, local))
            print(f"  {day}日: OK")
            continue
    images.append((day, None))
    print(f"  {day}日: 画像なし")

rows = math.ceil(days / COLS)
canvas = Image.new("RGB", (COLS * CELL_W, rows * (CELL_H + LABEL_H)), (30, 30, 30))
draw = ImageDraw.Draw(canvas)

for idx, (day, path) in enumerate(images):
    x = (idx % COLS) * CELL_W
    y = (idx // COLS) * (CELL_H + LABEL_H)
    draw.rectangle([x, y, x+CELL_W-1, y+LABEL_H-1], fill=(50, 50, 50))
    draw.text((x+CELL_W//2, y+LABEL_H//2), f"{month}/{day}",
              fill=(200, 200, 200), anchor="mm")
    img_y = y + LABEL_H
    if path:
        try:
            img = Image.open(path).resize((CELL_W, CELL_H))
            canvas.paste(img, (x, img_y))
        except Exception:
            draw.rectangle([x, img_y, x+CELL_W-1, img_y+CELL_H-1], fill=(60, 40, 40))
    else:
        draw.rectangle([x, img_y, x+CELL_W-1, img_y+CELL_H-1], fill=(40, 40, 40))
        draw.text((x+CELL_W//2, img_y+CELL_H//2), "no image",
                  fill=(100, 100, 100), anchor="mm")
    draw.rectangle([x, y, x+CELL_W-1, y+CELL_H+LABEL_H-1],
                   outline=(80, 80, 80), width=1)

out_path = f"{TMP_DIR}/{ym}.jpg"
canvas.save(out_path, "JPEG", quality=85)
print(f"合成完了: {out_path} ({os.path.getsize(out_path)/1024:.0f}KB)")

r = subprocess.run(["scp", *SSH_OPTS, out_path, f"{REMOTE}:{config.CONOHA_MONTHLY_DIR}/"],
                   capture_output=True, timeout=120)
print("✅ 転送成功" if r.returncode == 0 else f"❌ 転送失敗: {r.stderr.decode()}")

for _, path in images:
    if path and os.path.exists(path):
        os.remove(path)
if os.path.exists(out_path):
    os.remove(out_path)
