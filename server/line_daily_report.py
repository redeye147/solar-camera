#!/usr/bin/env python3
"""LINE 用の日報メール（ConoHa の cron: 0 22 * * *）。

件名「[日報] 太陽光発電所 …」のメールを自分宛てに送ると、Gmail の GAS が
本文を LINE に送り、本文の「PHOTO: URL」行を写真として送る。

  line_daily_report.py            日報を送る
  line_daily_report.py --dry-run  送らずに本文を表示する（確認用）

知らせる異常（⚠️）:
  - PCS のどちらかの発電量が、もう一方の半分未満（一部停止の可能性）
  - 晴れの日（平均日射量 100W/m2 以上）が EFF_STREAK 回続けて、発電効率（kWh÷日射量）が
    直近60日の晴れの日の中央値の 85% 未満（汚れ・影・故障の可能性）
  - みえるーぷの警報（軽故障・重故障、毎晩の「DC入力不足電圧」以外の通知）
  - 撮影の欠け、ネットワークの異常、撮影停止アラート
"""
import glob, json, os, re, statistics, sys
from datetime import date, datetime, timedelta
import mailer

SITE = "https://solar.redeye-lab.com"
IMAGE_DIR = "/var/www/html/solar/images"
ALERT_FILE = "/var/www/html/solar/network_alert.txt"
ALERT_ARCHIVE = os.path.expanduser("~/archive/network_alert.log")
RPI_STATE = os.path.expanduser("~/check_rpi_state.json")
CAPTURE_HOURS = range(4, 21)          # 定時撮影 4〜20時
PCS_IDS = ["1", "2"]
SUNNY_IRR = 100                       # 晴れとみなす平均日射量 (W/m2)
EFF_WARN_RATIO = 0.85                 # 平常の発電効率に対してこれ未満で警告
EFF_MIN_SAMPLES = 5                   # 平常値の計算に必要な晴れの日の数
EFF_STREAK = 3                        # 晴れの日がこの回数続けて低いときだけ警告
EFF_BASE_DAYS = 30                    # 平常値に使う期間（日）。季節の変化に追従するため短め
PCS_WARN_RATIO = 0.5                  # PCS 間の発電量の比がこれ未満で警告
ROUTINE_ALERT_CODES = {"0064"}        # 毎晩の DC入力不足電圧（日没）は知らせない
WEEKDAY = "月火水木金土日"


def yen(v):
    return f"{round(v):,}円" if v is not None else "-"


def sky(irr):
    if irr is None:
        return "☀"
    return "☀" if irr >= SUNNY_IRR else ("⛅" if irr >= 50 else "☁")


def efficiency_streak(hist, today):
    """直近の晴れの日 EFF_STREAK 回（今日を含む）がすべて平常の EFF_WARN_RATIO 未満なら
    その比率のリストを、そうでなければ None を返す。

    発電効率 = 発電量 ÷ 平均日射量。曇りの日は計算上高めに出るので晴れの日だけを使う。
    日が短くなる季節には少しずつ下がるため、平常値は直近 EFF_BASE_DAYS 日の
    晴れの日の中央値（判定対象の日は除く）とする。
    """
    sunny = [(r["date"], r["kwh"] / r["irr"]) for r in hist
             if r["date"] <= today and r["kwh"] and r["irr"] and r["irr"] >= SUNNY_IRR]
    if len(sunny) < EFF_STREAK or sunny[-1][0] != today:
        return None                                   # 今日が晴れでなければ判定しない
    recent = sunny[-EFF_STREAK:]
    start = recent[0][0]
    base = [e for d, e in sunny if start - timedelta(days=EFF_BASE_DAYS) <= d < start]
    if len(base) < EFF_MIN_SAMPLES:
        return None
    med = statistics.median(base)
    ratios = [e / med for _, e in recent]
    return ratios if all(r < EFF_WARN_RATIO for r in ratios) else None


def solar_section(today, warnings):
    """発電量の行と、発電に関する警告を返す。取得できなければ説明の行を返す。"""
    step = "ログイン"
    try:
        from mieloop import Mieloop
        m = Mieloop()
        step = "CSV取得"
        hist = m.days(today - timedelta(days=60), today)
    except Exception as e:
        code = getattr(e, "code", "")
        warnings.append(f"⚠️ みえるーぷから発電量を取得できません（{step}: {type(e).__name__} {code}）".replace(" ）", "）"))
        return ["☀ 発電量 取得できませんでした"], False

    by_date = {r["date"]: r for r in hist}
    t = by_date.get(today)
    month = [r for r in hist if r["date"].month == today.month and r["date"].year == today.year]
    mk = sum(r["kwh"] or 0 for r in month)
    my = sum(r["yen"] or 0 for r in month)
    lines = []
    if t and t["kwh"] is not None:
        lines.append(f"{sky(t['irr'])} 発電量 {t['kwh']:.1f} kWh（{yen(t['yen'])}）")
        extra = []
        if t["irr"] is not None:
            extra.append(f"日射量 {t['irr']:.0f} W/m²")
        if t["temp"] is not None:
            extra.append(f"気温 {t['temp']:.0f}℃")
        if extra:
            lines.append("   " + "・".join(extra))
    else:
        lines.append("☀ 発電量 今日のデータがまだありません")
    lines.append(f"📅 今月 {mk:,.0f} kWh（{yen(my)}）")

    # 発電効率の低下（晴れの日が EFF_STREAK 回続けて平常の 85% 未満のときだけ警告）
    ratios = efficiency_streak(hist, today)
    if ratios:
        txt = "・".join(f"{r:.0%}" for r in ratios)
        warnings.append(f"⚠️ 発電効率の低下が晴れの日 {EFF_STREAK} 回続いています"
                        f"（平常の {txt}）パネルの汚れ・影・故障の可能性")

    # PCS ごとの発電量（取れる場合だけ比べる）
    try:
        per = {}
        for p in PCS_IDS:
            r = {x["date"]: x for x in m.days(today, today, pcs_id=p)}.get(today)
            per[p] = r["kwh"] if r else None
        vals = [v for v in per.values() if v is not None]
        total = t["kwh"] if t else None
        if (len(vals) == len(PCS_IDS) and total and total >= 5
                and abs(sum(vals) - total) <= total * 0.1 and max(vals) > 0):
            if min(vals) / max(vals) < PCS_WARN_RATIO:
                detail = " / ".join(f"PCS{p} {v:.1f}kWh" for p, v in per.items())
                warnings.append(f"⚠️ PCS の発電量に差（{detail}）一部停止の可能性")
    except Exception:
        pass  # PCS 個別が取れなくても日報は送る

    # みえるーぷの警報（今日発生、日没の定常通知を除く）
    try:
        for a in m.alerts():
            if a["occurred"].date() == today and a["code"] not in ROUTINE_ALERT_CODES:
                warnings.append(f"⚠️ PCS{a['pcs']} {a['level']}: {a['message']}")
    except Exception:
        pass
    return lines, True


def system_section(today, warnings, pcs_known=True):
    """カメラ・回線の状態。"""
    names = [os.path.basename(f) for f in glob.glob(f"{IMAGE_DIR}/{today:%Y%m%d}_*.jpg")]
    shot = {n[9:11] for n in names if n[11:13] == "00"}            # 定時（:00）の撮影
    expected = [h for h in CAPTURE_HOURS if h <= datetime.now().hour]
    got = sum(1 for h in expected if f"{h:02d}" in shot)
    if got < len(expected):
        warnings.append(f"⚠️ 撮影 {got}/{len(expected)} 回（欠けあり）")

    net = 0
    for path in (ALERT_FILE, ALERT_ARCHIVE):
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                net += sum(1 for l in f if l.startswith(f"{today:%Y-%m-%d}"))
    if net:
        warnings.append(f"⚠️ 回線の異常記録 {net} 件（20:30 のメール参照）")
    try:
        with open(RPI_STATE) as f:
            if json.load(f).get("alerted"):
                warnings.append("⚠️ 撮影停止アラート発信中")
    except (OSError, ValueError):
        pass

    pcs_ok = not any("PCS" in w for w in warnings)
    net_ok = not net
    pcs_txt = ("不明" if not pcs_known else "正常 ✅" if pcs_ok else "要確認 ⚠️")
    return [f"   PCS {len(PCS_IDS)}台 {pcs_txt}"
            f"　回線 {'異常なし ✅' if net_ok else '要確認 ⚠️'}"], sorted(names)


def photo_url(names):
    noon = [n for n in names if n[9:13] == "1200"]
    pick = noon[0] if noon else (names[-1] if names else None)
    return f"{SITE}/images/{pick}" if pick else None


def build(today):
    warnings = []
    lines, pcs_known = solar_section(today, warnings)
    sys_lines, names = system_section(today, warnings, pcs_known)
    body = "\n".join(lines) + "\n🔧 システム\n" + "\n".join(sys_lines)
    if warnings:
        body += "\n" + "\n".join(warnings)
    url = photo_url(names)
    if url:
        body += f"\nPHOTO: {url}"
    tag = "[日報][要確認]" if warnings else "[日報]"
    subject = f"{tag} 太陽光発電所 {today.month}/{today.day}({WEEKDAY[today.weekday()]})"
    return subject, body


def main():
    subject, body = build(date.today())
    if "--dry-run" in sys.argv:
        print(subject); print(); print(body)
        return
    print("送信成功" if mailer.send(subject, body) else "送信失敗")


if __name__ == "__main__":
    main()
