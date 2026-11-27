#!/usr/bin/env python3
"""SIM(wwan0)の通信量を b-mobile の課金期間で集計し、レポートをConoHaへ転送する。

課金期間は BILLING_START_DAY 日 〜 翌月 BILLING_START_DAY-1 日（既定: 7日〜翌6日）。
vnstat の日別データ（--json d）を期間内で合計する。

使い方:
  monthly_traffic.py            直前に終わった課金期間のレポート（締め日翌日の cron 用）
  monthly_traffic.py --current  今の課金期間の途中経過（確認用）

cron 例（毎月7日 01:30 に前期間を集計）: 30 1 7 * *
"""
import calendar, json, os, subprocess, sys
from datetime import date, datetime, timedelta
import config

REMOTE_FILE = getattr(config, "CONOHA_TRAFFIC_REPORT",
                      f"{config.CONOHA_REMOTE_BASE}/traffic_report.txt")
LIMIT_MB = getattr(config, "SIM_LIMIT_MB", 1000)
IFACE = getattr(config, "SIM_IFACE", "wwan0")
START_DAY = getattr(config, "BILLING_START_DAY", 7)
MB = 1000 * 1000  # 通信事業者の表記に合わせ 1MB = 10^6 バイト


def period_start(d, start_day=START_DAY):
    """日付 d を含む課金期間の開始日。"""
    def clamp(y, m):
        return date(y, m, min(start_day, calendar.monthrange(y, m)[1]))
    s = clamp(d.year, d.month)
    if d >= s:
        return s
    y, m = (d.year - 1, 12) if d.month == 1 else (d.year, d.month - 1)
    return clamp(y, m)


def next_period_start(s, start_day=START_DAY):
    y, m = (s.year + 1, 1) if s.month == 12 else (s.year, s.month + 1)
    return date(y, m, min(start_day, calendar.monthrange(y, m)[1]))


def daily_traffic(iface):
    """{date: (rx_bytes, tx_bytes)} を返す。vnstat 1.x / 2.x の JSON に対応。"""
    r = subprocess.run(["vnstat", "-i", iface, "--json", "d"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"vnstat 実行失敗: {r.stderr.strip()}")
    data = json.loads(r.stdout)
    unit = 1024 if str(data.get("jsonversion", "1")) == "1" else 1  # 1.x は KiB
    traffic = data["interfaces"][0]["traffic"]
    days = traffic.get("day") or traffic.get("days") or []
    out = {}
    for e in days:
        d = e["date"]
        out[date(d["year"], d["month"], d["day"])] = (e["rx"] * unit, e["tx"] * unit)
    return out


def main():
    current = "--current" in sys.argv
    today = date.today()
    if current:
        start = period_start(today)
        end = today
        title = "今期の途中経過"
    else:
        end = period_start(today) - timedelta(days=1)  # 直前の期間の最終日
        start = period_start(end)
        title = "課金期間レポート"
    days_total = (next_period_start(start) - start).days
    days_elapsed = (end - start).days + 1

    daily = daily_traffic(IFACE)
    rx = sum(v[0] for d, v in daily.items() if start <= d <= end) / MB
    tx = sum(v[1] for d, v in daily.items() if start <= d <= end) / MB
    total = rx + tx
    oldest = min(daily) if daily else None

    report = f"""
【日本通信SIM 通信量レポート（{title}）】
課金期間：{start:%Y/%m/%d} 〜 {next_period_start(start) - timedelta(days=1):%Y/%m/%d}
集計範囲：{start:%Y/%m/%d} 〜 {end:%Y/%m/%d}（{days_elapsed}/{days_total}日）
────────────────────
受信（RX）：{rx:.1f} MB
送信（TX）：{tx:.1f} MB
合計      ：{total:.1f} MB / {LIMIT_MB} MB
使用率    ：{total / LIMIT_MB * 100:.1f}%
残り      ：{LIMIT_MB - total:.1f} MB
"""
    if current and days_elapsed < days_total:
        projected = total / days_elapsed * days_total
        report += f"期間末の見込み：{projected:.0f} MB（今のペースの場合）\n"
    report += "────────────────────\n"

    if total > LIMIT_MB * 0.8:
        report += "警告：使用量が80%を超えています\n"
    elif total > LIMIT_MB * 0.5:
        report += "注意：使用量が50%を超えています\n"
    else:
        report += "使用量は正常範囲内です\n"
    if oldest and oldest > start:
        report += f"※ vnstat の記録は {oldest:%Y/%m/%d} 以降のみ（それ以前は含まない）\n"
    report += f"\n報告日時：{datetime.now():%Y/%m/%d %H:%M}\n"
    print(report)

    if current:
        return  # 途中経過は表示のみ

    tmp = "/tmp/traffic_report.txt"
    with open(tmp, "w") as f:
        f.write(report)
    import conoha_ssh
    r = conoha_ssh.scp_to(tmp, REMOTE_FILE, timeout=60)
    os.remove(tmp)
    print("ConoHa転送完了" if conoha_ssh.ok(r) else f"ConoHa転送失敗: {conoha_ssh.err(r)}")


if __name__ == "__main__":
    main()
