#!/usr/bin/env python3
"""インターネット疎通を監視し、断のときだけ段階的に復旧・記録する。

構成の前提 (NetworkManager の route metric、小さいほど優先):
  - 優先: eth0 (eth0-auto, metric LAN_METRIC=600)
          自宅ではルーター経由でインターネットに出られる → SIMを節約
          現場はカメラ用LANでゲートウェイが無い → 自動的にSIMが使われる
  - 予備: SIMドングル (gsm 接続, metric 700)

LANフェイルオーバー:
  LANのゲートウェイはあるのにインターネットに出られない (ルーター/回線障害)
  ときは、eth0 の metric を LAN_FALLBACK_METRIC(900) に下げて SIM に切替。
  切替中も毎回 LAN 経由の疎通を試し、戻ったら LAN_METRIC に戻す。

予備回線(SIM)の健康診断:
  LAN で通信中も毎回 SIM 経由の疎通を試し、だめなら SIM だけ復旧
  (SIM再接続 → ModemManager再起動) を試みて、異常と復旧を通知する。

復旧の段階 (どの経路でも出られないとき):
  1. SIM接続の張り直し (nmcli down/up)
  2. ModemManager の再起動 (QMIポートの取りこぼし対策)
  3. モデムのリセット (mmcli --reset)
  4. LAN接続の張り直し (現場用の固定IP eth0-site で動作中は行わない)
  5. それでも断が続けば NET_REBOOT_AFTER_RUNS 回ごとに再起動

通知: 異常 (断の検出/復旧、SIM切替、再起動など) だけを network_alert.txt に
      記録し、まだ送っていない行 (network_alert_pending.txt) を、インターネットに
      出られるときに ConoHa の network_alert.txt へ追記する。
      ConoHa 側の daily_report.py が毎日メールで送り、送信後にファイルを消す。
      経路変更 (ケーブル抜き差し等) は異常ではないので標準出力 (network.log) のみ。

cron 例: */5 * * * * /usr/bin/python3 /home/pi/solar/check_network.py
"""
import fcntl, json, os, subprocess, sys, time
from datetime import datetime
import config

BASE = os.path.dirname(os.path.abspath(__file__))
ALERT = getattr(config, "NETWORK_ALERT_LOCAL", os.path.join(BASE, "network_alert.txt"))
PENDING = os.path.join(BASE, "network_alert_pending.txt")  # ConoHa未送信分
STATE = getattr(config, "NETWORK_STATE", os.path.join(BASE, "network_state.json"))
LOCK = os.path.join(BASE, ".check_network.lock")

GSM_CONN = getattr(config, "GSM_CONNECTION", "nihontsushin")
LAN_CONN = getattr(config, "NM_CONNECTION", "eth0-auto")
SITE_CONN = getattr(config, "SITE_CONNECTION", "eth0-site")  # 現場用の固定IP
TARGETS = getattr(config, "PING_TARGETS", ["1.1.1.1", "8.8.8.8"])
REBOOT_AFTER = getattr(config, "NET_REBOOT_AFTER_RUNS", 6)  # 0 で再起動しない
LAN_DEV = getattr(config, "LAN_IFACE", "eth0")
SIM_DEV = getattr(config, "SIM_IFACE", "wwan0")
LAN_METRIC = getattr(config, "LAN_METRIC", 600)
LAN_FALLBACK_METRIC = getattr(config, "LAN_FALLBACK_METRIC", 900)

SIM_RETRY_MINUTES = 30  # 予備SIMが直らないときの復旧試行の間隔(分)
GRACE_CHECKS = 4        # 断と判定するまでの確認回数
GRACE_INTERVAL = 5      # 確認間隔(秒)
MAX_ALERT_LINES = 200


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg, alert=True):
    """標準出力 (cron で network.log へ) に記録。alert=True なら通知対象にもする。"""
    line = f"{now()} {msg}\n"
    print(line, end="", flush=True)
    if not alert:
        return
    lines = []
    if os.path.exists(ALERT):
        with open(ALERT) as f:
            lines = f.readlines()
    lines.append(line)
    with open(ALERT, "w") as f:  # 手元の履歴 (直近 MAX_ALERT_LINES 行)
        f.writelines(lines[-MAX_ALERT_LINES:])
    with open(PENDING, "a") as f:
        f.write(line)


def run(cmd, timeout=60):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None


def online():
    for t in TARGETS:
        r = run(["ping", "-c", "1", "-W", "3", t], timeout=10)
        if r and r.returncode == 0:
            return True
    return False


def online_via(dev):
    """指定インターフェース経由でインターネットに出られるか。"""
    for t in TARGETS:
        r = run(["ping", "-I", dev, "-c", "1", "-W", "3", t], timeout=10)
        if r and r.returncode == 0:
            return True
    return False


def confirmed_offline():
    """猶予時間内に一度でも疎通すれば False (一瞬の瞬断は無視)。"""
    for i in range(GRACE_CHECKS):
        if online():
            return False
        if i < GRACE_CHECKS - 1:
            time.sleep(GRACE_INTERVAL)
    return True


def route_dev():
    """インターネット向けに実際に使われているインターフェース名。"""
    r = run(["ip", "route", "get", TARGETS[0]])
    if not r or r.returncode != 0:
        return None
    parts = r.stdout.split()
    return parts[parts.index("dev") + 1] if "dev" in parts else None


def nmcli(*args, timeout=90):
    return run(["sudo", "nmcli", *args], timeout=timeout)


def set_lan_metric(metric):
    # eth0 は reapply で metric が反映される (モデムには効かないので使わない)
    nmcli("connection", "modify", LAN_CONN, "ipv4.route-metric", str(metric))
    nmcli("device", "reapply", LAN_DEV)
    time.sleep(3)


def step_sim_reconnect():
    nmcli("connection", "down", GSM_CONN)
    time.sleep(3)
    nmcli("connection", "up", GSM_CONN)


def step_mm_restart():
    # 起動時に ModemManager が QMI ポート(cdc-wdm0)を取りこぼし、AT ポート(ttyUSB2)
    # だけで認識してデータ接続できなくなることがある (EC25)。再起動で認識し直させる。
    run(["sudo", "systemctl", "restart", "ModemManager"], timeout=60)
    time.sleep(40)  # モデム再認識待ち
    nmcli("connection", "up", GSM_CONN)


def step_modem_reset():
    run(["sudo", "mmcli", "-m", "any", "--reset"], timeout=30)
    time.sleep(60)  # モデム再認識待ち
    nmcli("connection", "up", GSM_CONN)


def active_lan_conn():
    r = run(["nmcli", "-g", "GENERAL.CONNECTION", "device", "show", LAN_DEV])
    return r.stdout.strip() if r and r.returncode == 0 else ""


def step_lan_reconnect():
    # 現場用の固定IP (eth0-site) で動いているときは触らない。
    # DHCP (eth0-auto) を張り直すと固定IPが外れてカメラに届かなくなるため。
    if active_lan_conn() == SITE_CONN:
        return
    nmcli("connection", "up", LAN_CONN)


RECOVERY_STEPS = [
    ("SIM再接続", step_sim_reconnect),
    ("ModemManager再起動", step_mm_restart),
    ("モデムリセット", step_modem_reset),
    ("LAN再接続", step_lan_reconnect),
]


def recover(state):
    for name, fn in RECOVERY_STEPS:
        fn()
        time.sleep(10)
        if online():
            return name
        if try_lan_failover(state):  # SIMだけ戻った場合は SIM優先に切替
            return f"{name} + SIM優先に切替"
    return None


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(s):
    with open(STATE, "w") as f:
        json.dump(s, f)


def send_pending_alerts():
    """未送信の異常記録だけを ConoHa の通知ファイルへ追記する。成功したら消す。"""
    if not os.path.exists(PENDING):
        return
    with open(PENDING) as f:
        data = f.read()
    if not data.strip():
        os.remove(PENDING)
        return
    try:
        r = subprocess.run([
            "ssh", "-i", config.SSH_KEY,
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ConnectTimeout=15",
            f"{config.CONOHA_USER}@{config.CONOHA_HOST}",
            f"cat >> {config.CONOHA_NETWORK_ALERT}",
        ], input=data, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return
    if r.returncode == 0:
        os.remove(PENDING)


def minutes_since(ts):
    t = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    return int((datetime.now() - t).total_seconds() // 60)


def on_online(state):
    dev = route_dev()
    if state.get("down_since"):
        log(f"インターネット復旧 (経路: {dev}, 断 {minutes_since(state['down_since'])}分)")
    elif state.get("dev") and dev and dev != state["dev"]:
        log(f"経路変更 {state['dev']} → {dev}", alert=False)  # 異常ではない
    state.pop("down_since", None)
    state.pop("fail_runs", None)
    state["dev"] = dev
    save_state(state)
    send_pending_alerts()  # 出られるうちに未送信分を送る


def try_lan_failover(state):
    """LANだけがダメでSIMは生きているなら、SIM優先に切り替える。"""
    if state.get("lan_demoted") or online_via(LAN_DEV) or not online_via(SIM_DEV):
        return False
    set_lan_metric(LAN_FALLBACK_METRIC)
    state["lan_demoted"] = True
    log(f"LAN経由でインターネットに出られないため SIM優先に切替 (eth0 metric {LAN_FALLBACK_METRIC})")
    return online()


def try_lan_restore(state):
    """SIMへ切替中に LAN の疎通が戻っていれば LAN優先に戻す。"""
    if state.get("lan_demoted") and online_via(LAN_DEV):
        set_lan_metric(LAN_METRIC)
        state.pop("lan_demoted")
        log(f"LANの疎通が復帰したため LAN優先に戻しました (eth0 metric {LAN_METRIC})")


def on_offline(state):
    if try_lan_failover(state):
        on_online(state)
        return

    if not state.get("down_since"):
        state["down_since"] = now()
        log(f"インターネット断を検出 (経路: {route_dev()})")
    state["fail_runs"] = state.get("fail_runs", 0) + 1

    how = recover(state)
    if how:
        log(f"復旧処理成功: {how} (経路: {route_dev()})")
        on_online(state)
        return

    reboot = REBOOT_AFTER and state["fail_runs"] % REBOOT_AFTER == 0
    if state["fail_runs"] == 1 or reboot:  # ログの連発を避ける
        log(f"復旧処理失敗 ({state['fail_runs']}回目)")
    save_state(state)
    if reboot:
        log("断が続いているため再起動します")
        run(["sudo", "reboot"])


SIM_RECOVERY_STEPS = [
    ("SIM再接続", step_sim_reconnect),
    ("ModemManager再起動", step_mm_restart),
]


def check_backup_sim(state):
    """LAN で通信中も、予備の SIM が使えるかを確かめる。

    自宅では LAN で出られるため SIM の故障に気づけない (再起動後に SIM が
    つながらず、そのまま現場に設置すると遠隔操作できなくなる)。
    SIM 経由で出られなければ SIM だけ復旧を試み、異常・復旧を通知する。
    """
    if route_dev() == SIM_DEV:
        return  # SIM で通信中 (= SIM は生きている)
    if online_via(SIM_DEV):
        state.pop("sim_retry_at", None)
        if state.pop("sim_down_since", None):
            log("予備回線(SIM)が復旧しました")
        return
    if not state.get("sim_down_since"):
        state["sim_down_since"] = now()
        log("予備回線(SIM)で通信できません → SIMの復旧を試みます")
    elif minutes_since(state.get("sim_retry_at", state["sim_down_since"])) < SIM_RETRY_MINUTES:
        return  # 復旧の試行は SIM_RETRY_MINUTES 分に1回まで
    state["sim_retry_at"] = now()
    for name, fn in SIM_RECOVERY_STEPS:
        fn()
        time.sleep(5)
        if online_via(SIM_DEV):
            log(f"予備回線(SIM)が復旧しました ({name})")
            state.pop("sim_down_since", None)
            state.pop("sim_retry_at", None)
            return


def main():
    lock = open(LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(0)  # 前回の実行(復旧処理中)がまだ動いている

    state = load_state()
    try_lan_restore(state)
    if online() or not confirmed_offline():
        check_backup_sim(state)
        on_online(state)
    else:
        on_offline(state)


if __name__ == "__main__":
    main()
