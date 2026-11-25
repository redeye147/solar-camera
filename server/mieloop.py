#!/usr/bin/env python3
"""みえるーぷ（https://mielooop.com）から発電データと警報を取得する。

ログイン情報は ~/.solar_mieloop.conf（JSON, chmod 600）から読む:
  {"user": "ログインID", "password": "パスワード"}
"""
import csv, html, http.cookiejar, io, json, os, re, urllib.parse, urllib.request
from datetime import date, datetime

BASE = "https://mielooop.com"
PLANT_ID = 1138
CONF = os.environ.get("SOLAR_MIELOOP_CONF", os.path.expanduser("~/.solar_mieloop.conf"))


def _num(s):
    s = (s or "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


class Mieloop:
    def __init__(self, conf_path=CONF):
        with open(conf_path) as f:
            self.conf = json.load(f)
        self.op = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.op.addheaders = [("User-Agent", "Mozilla/5.0 (solar-camera daily report)")]
        self._login()

    def _open(self, url, data=None):
        if isinstance(data, dict):
            data = urllib.parse.urlencode(data, doseq=True).encode()
        return self.op.open(url, data, timeout=60)

    def _get(self, url):
        return self._open(url).read().decode("utf-8", "replace")

    def _login(self):
        h = self._get(f"{BASE}/user/login")
        tok = re.search(r'name="_token" value="([^"]+)"', h).group(1)
        r = self._open(f"{BASE}/login", {"_token": tok, "login_id": self.conf["user"],
                                         "password": self.conf["password"]})
        body = r.read().decode("utf-8", "replace")
        if "logout" not in body.lower():
            raise RuntimeError("みえるーぷにログインできません（ID・パスワードを確認）")

    def _csv_form(self):
        """発電量画面の CSV ダウンロードフォームの初期値（_token 含む）。"""
        h = self._get(f"{BASE}/plant/index/{PLANT_ID}?type=day")
        form = re.search(r'<form[^>]*id="PlantIndexForm".*?</form>', h, re.S).group(0)
        fields = {}
        for tag in re.findall(r"<input[^>]*>", form):
            n = re.search(r'name="([^"]+)"', tag)
            v = re.search(r'value="([^"]*)"', tag)
            if n:
                fields[n.group(1)] = html.unescape(v.group(1)) if v else ""
        # 日付などの選択式の欄（<select>）も、選ばれている値（無ければ先頭）を送る
        for name, body in re.findall(r'<select[^>]*name="([^"]+)"[^>]*>(.*?)</select>', form, re.S):
            sel = re.search(r'<option[^>]*value="([^"]*)"[^>]*selected', body)
            first = re.search(r'<option[^>]*value="([^"]*)"', body)
            fields[name] = sel.group(1) if sel else (first.group(1) if first else "")
        return fields

    def days(self, start, end, pcs_id=""):
        """日別データ [{date, kwh, yen, irr, temp}]（irr=平均日射量 W/m2, temp=平均気温）。"""
        f = self._csv_form()
        f.update({"type": "day", "pcs_id": pcs_id,
                  "date[year]": end.year, "date[month]": f"{end.month:02d}",
                  "date[day]": f"{end.day:02d}",
                  "start_date[year]": start.year, "start_date[month]": f"{start.month:02d}",
                  "start_date[day]": f"{start.day:02d}",
                  "end_date[year]": end.year, "end_date[month]": f"{end.month:02d}",
                  "end_date[day]": f"{end.day:02d}"})
        raw = self._open(f"{BASE}/plant/csv_download", f).read()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp932")
        rows = []
        for r in list(csv.reader(io.StringIO(text)))[1:]:
            m = re.match(r"(\d+)年(\d+)月(\d+)日", r[0] if r else "")
            if not m:
                continue
            rows.append({"date": date(*map(int, m.groups())),
                         "kwh": _num(r[1]) if len(r) > 1 else None,
                         "yen": _num(r[2]) if len(r) > 2 else None,
                         "irr": _num(r[3]) if len(r) > 3 else None,
                         "temp": _num(r[4]) if len(r) > 4 else None})
        return rows

    def alerts(self):
        """警報一覧（新しい順）[{pcs, level, code, occurred, resolved, message}]。"""
        h = self._get(f"{BASE}/alert/index?plant_id={PLANT_ID}")
        out = []
        for row in re.findall(r"<tr.*?</tr>", h, re.S):
            cells = [_text(c) for c in re.findall(r"<td.*?</td>", row, re.S)]
            if len(cells) < 7 or not re.match(r"\d{4}-\d{2}-\d{2}", cells[4]):
                continue
            out.append({"pcs": cells[1], "level": cells[2], "code": cells[3],
                        "occurred": datetime.strptime(cells[4][:19], "%Y-%m-%d %H:%M:%S"),
                        "resolved": cells[5] or None, "message": cells[6]})
        return out
