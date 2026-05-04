#!/usr/bin/env python3
import subprocess, os, calendar, math
from datetime import datetime, timedelta
from PIL import Image, ImageDraw
import config

TMP_DIR = "/tmp/solar_monthly"
COLS    = 6
CELL_W  = 213
CELL_H  = 160
LABEL_H = 20

os.makedirs(TMP_DIR, exist_ok=True)

today = datetime.now()
first_of_this_month = today.replace(day=1)
last_month = first_of_this_month - timedelta(days=1)
year  = last_month.year
month = last_month.month
days  = calendar.monthrange(year, month)[1]
ym    = f"{year}{month:02d}"

print(f"{year}年{month}月の合成開始（{days}日分）")

images = []
for day in range(1, days + 1):
    fname = f"{year}{month:02d}{day:02d}_1200.jpg"
    local = f"{TMP_DIR}/{fname}"
    result = subprocess.run([
        "scp", "-i", config.SSH_KEY,
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        f"{config.CONOHA_USER}@{config.CONOHA_HOST}:{config.CONOHA_IMG_DIR}/{fname}",
        local
    ], capture_output=True)
    if result.returncode == 0 and os.path.exists(local):
        images.append((day, local))
        print(f"  {day}日: OK")
    else:
        images.append((day, None))
        print(f"  {day}日: 画像なし")

rows = math.ceil(days / COLS)
total_w = COLS * CELL_W
total_h = rows * (CELL_H + LABEL_H)

canvas = Image.new("RGB", (total_w, total_h), (30, 30, 30))
draw = ImageDraw.Draw(canvas)

for idx, (day, path) in enumerate(images):
    col = idx % COLS
    row = idx // COLS
    x = col * CELL_W
    y = row * (CELL_H + LABEL_H)

    draw.rectangle([x, y, x+CELL_W-1, y+LABEL_H-1], fill=(50, 50, 50))
    draw.text((x+CELL_W//2, y+LABEL_H//2),
              f"{month}/{day}", fill=(200, 200, 200), anchor="mm")

    img_y = y + LABEL_H
    if path:
        try:
            img = Image.open(path).resize((CELL_W, CELL_H))
            canvas.paste(img, (x, img_y))
        except:
            draw.rectangle([x, img_y, x+CELL_W-1, img_y+CELL_H-1], fill=(60, 40, 40))
    else:
        draw.rectangle([x, img_y, x+CELL_W-1, img_y+CELL_H-1], fill=(40, 40, 40))
        draw.text((x+CELL_W//2, img_y+CELL_H//2),
                  "no image", fill=(100, 100, 100), anchor="mm")

    draw.rectangle([x, y, x+CELL_W-1, y+CELL_H+LABEL_H-1],
                   outline=(80, 80, 80), width=1)

out_path = f"{TMP_DIR}/{ym}.jpg"
canvas.save(out_path, "JPEG", quality=85)
size_kb = os.path.getsize(out_path) / 1024
print(f"合成完了: {out_path} ({size_kb:.0f}KB)")

result = subprocess.run([
    "scp", "-i", config.SSH_KEY,
    "-o", "StrictHostKeyChecking=no",
    out_path,
    f"{config.CONOHA_USER}@{config.CONOHA_HOST}:{config.CONOHA_MONTHLY_DIR}/"
], capture_output=True)

if result.returncode == 0:
    print("✅ 転送成功")
else:
    print("❌ 転送失敗:", result.stderr.decode())

for _, path in images:
    if path and os.path.exists(path):
        os.remove(path)
if os.path.exists(out_path):
    os.remove(out_path)
