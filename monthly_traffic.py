#!/usr/bin/env python3
"""前月のSIM(wwan0)通信量を vnstat で集計し、レポートをConoHaへ転送する。

cron 例: 30 1 1 * *
注意: 集計はカレンダー月。b-mobile の課金期間（例: 7日〜翌6日）とはずれる。
"""
import subprocess, os, calendar
from datetime import datetime, timedelta
import config

REMOTE_FILE = getattr(config, "CONOHA_TRAFFIC_REPORT",
                      f"{config.CONOHA_REMOTE_BASE}/traffic_report.txt")
LIMIT_MB = getattr(config, "SIM_LIMIT_MB", 1000)
IFACE = getattr(config, "SIM_IFACE", "wwan0")

today = datetime.now()
last_month = today.replace(day=1) - timedelta(days=1)
ym = last_month.strftime("%Y-%m")
year, month = last_month.year, last_month.month
days_in_month = calendar.monthrange(year, month)[1]
period_start = f"{year}/{month:02d}/01"
period_end   = f"{year}/{month:02d}/{days_in_month:02d}"

result = subprocess.run(["vnstat", "-i", IFACE, "-m", "--oneline"],
                        capture_output=True, text=True)

rx_mb = tx_mb = total_mb = 0.0
for line in result.stdout.strip().split("\n"):
    if ym in line:
        parts = line.split(";")
        if len(parts) >= 9:
            try:
                rx_mb, tx_mb, total_mb = float(parts[3]), float(parts[5]), float(parts[7])
            except ValueError:
                pass

report = f"""
【日本通信SIM 月次通信量レポート】
対象月  ：{year}年{month}月
計測期間：{period_start} 〜 {period_end}
────────────────────
受信（RX）：{rx_mb:.1f} MB
送信（TX）：{tx_mb:.1f} MB
合計      ：{total_mb:.1f} MB / {LIMIT_MB} MB
使用率    ：{total_mb/LIMIT_MB*100:.1f}%
残り      ：{LIMIT_MB - total_mb:.1f} MB
────────────────────
"""

if total_mb > LIMIT_MB * 0.8:
    report += "警告：使用量が80%を超えています\n"
elif total_mb > LIMIT_MB * 0.5:
    report += "注意：使用量が50%を超えています\n"
else:
    report += "使用量は正常範囲内です\n"

report += f"\n報告日時：{today.strftime('%Y/%m/%d %H:%M')}\n"
print(report)

tmp = "/tmp/traffic_report.txt"
with open(tmp, "w") as f:
    f.write(report)

r = subprocess.run(["scp", "-i", config.SSH_KEY,
                    "-o", "StrictHostKeyChecking=accept-new",
                    "-o", "ConnectTimeout=15",
                    tmp, f"{config.CONOHA_USER}@{config.CONOHA_HOST}:{REMOTE_FILE}"],
                   capture_output=True, timeout=60)
os.remove(tmp)
print("ConoHa転送完了" if r.returncode == 0 else f"ConoHa転送失敗: {r.stderr.decode()}")
