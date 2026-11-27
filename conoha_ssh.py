"""Pi → ConoHa の SSH/SCP を、1本の接続を使い回して行う（SIM の通信量を減らすため）。

毎回新しく SSH 接続すると、そのたびに鍵交換・認証で数 KB を使う。2分ごとの poll.py
だけで月 100MB 近くになるため、最初の接続（マスター）を数分間残しておき、
次からはその中を通す（OpenSSH の ControlMaster）。

  - マスターは使われなくなって CONTROL_PERSIST 経つと自動で閉じる
  - 回線の切り替え（LAN⇔SIM）などで古い接続が使えなくなっていたら、
    マスターを閉じて、その場で新しい接続でやり直す（失敗が後に残らない）
  - 生存確認のパケット（ServerAlive）は通信量が増えるので使わない
"""
import fcntl, os, subprocess
import config

REMOTE = f"{config.CONOHA_USER}@{config.CONOHA_HOST}"
CONTROL_PATH = os.path.expanduser("~/.ssh/solar-conoha.sock")
CONTROL_PERSIST = "5m"
LOCK = os.path.expanduser("~/.ssh/solar-conoha.lock")
BASE = ["-i", config.SSH_KEY,
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=15",
        "-o", "BatchMode=yes"]
MUX = ["-o", "ControlMaster=no", "-o", f"ControlPath={CONTROL_PATH}"]
DIRECT = ["-o", "ControlPath=none"]


def _ssh_quiet(args, timeout):
    try:
        return subprocess.run(["ssh", *BASE, *args], stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=timeout).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def _master_alive():
    return _ssh_quiet([*MUX, "-O", "check", REMOTE], 10)


def ensure_master():
    """マスター接続が無ければ作る。作れなければ False（そのときは直接接続する）。"""
    os.makedirs(os.path.dirname(CONTROL_PATH), mode=0o700, exist_ok=True)
    with open(LOCK, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)   # poll と check_network が同時に作らないように
        if _master_alive():
            return True
        try:
            os.remove(CONTROL_PATH)      # 停電・再起動で残った古いソケット
        except FileNotFoundError:
            pass
        # 出力をすべて /dev/null にしておく（裏に残るマスターが呼び出し元を待たせないため）
        return _ssh_quiet(["-o", "ControlMaster=yes", "-o", f"ControlPath={CONTROL_PATH}",
                           "-o", f"ControlPersist={CONTROL_PERSIST}", REMOTE, "true"], 40)


def close_master():
    """マスター接続を閉じる（回線が切り替わったとき用）。無ければ何もしない。"""
    _ssh_quiet([*MUX, "-O", "exit", REMOTE], 10)
    try:
        os.remove(CONTROL_PATH)
    except FileNotFoundError:
        pass


def _run(cmd, data, timeout):
    try:
        return subprocess.run(cmd, input=data, capture_output=True, text=True,
                              errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return None


def _call(tool, args, data, timeout):
    if ensure_master():
        r = _run([tool, *BASE, *MUX, *args], data, timeout)
        # ssh は 255、scp は 0 以外が接続の失敗。古い接続を捨てて、新しい接続でやり直す
        if r is not None and (r.returncode == 0 or (tool == "ssh" and r.returncode != 255)):
            return r
        close_master()
    return _run([tool, *BASE, *DIRECT, *args], data, timeout)


def ssh(cmd, data=None, timeout=60):
    """ConoHa でコマンドを実行。CompletedProcess（タイムアウト時は None）を返す。"""
    return _call("ssh", [REMOTE, cmd], data, timeout)


def scp_to(local, remote_path, timeout=120):
    """ConoHa へファイルを送る。CompletedProcess（タイムアウト時は None）を返す。"""
    return _call("scp", [local, f"{REMOTE}:{remote_path}"], None, timeout)


def scp_from(remote_path, local, timeout=120):
    """ConoHa からファイルを取ってくる。CompletedProcess（タイムアウト時は None）を返す。"""
    return _call("scp", [f"{REMOTE}:{remote_path}", local], None, timeout)


def ok(r):
    return r is not None and r.returncode == 0


def err(r):
    return "タイムアウト" if r is None else r.stderr.strip()
