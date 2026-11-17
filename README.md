# solar-camera

太陽光発電所の遠隔監視カメラシステム。Raspberry Pi に接続したRTSPカメラで定期的に撮影し、ConoHa VPS上のWebサーバーへ画像を転送・公開します。

## 構成

```
[RTSPカメラ] ──RTSP──> [Raspberry Pi Zero] ══SIM(LTE)══> [ConoHa VPS (Web)]
      │                    │  (USBハブ: LAN+SIMドングル)    │
      └──── LAN(eth0) ─────┘                              └─ Webブラウザから閲覧
                           └─ ネットワーク自己復旧 / Tailscaleで遠隔保守
```

- **Raspberry Pi**: 撮影、ネットワーク監視、月次サマリー生成
- **ConoHa VPS**: 画像配信、トリガーファイル経由の手動撮影リクエスト受付
- **ブラウザUI** (`index.html` / `monthly.html`): 日付選択、サムネイル、手動撮影ボタン、月次合成画像

## ファイル一覧

| ファイル | 役割 |
| --- | --- |
| `capture.py` | RTSPカメラから1枚撮影し、リサイズ・JPEG圧縮してConoHaへSCP転送 |
| `poll.py` | ConoHa上の `trigger` ファイルの有無を確認し、存在すれば手動撮影を実行 |
| `check_network.py` | eth0の疎通を監視し、切断時にNetworkManagerで自動復旧 |
| `monthly_composite.py` | 前月の毎日12:00画像をグリッド合成し、月次サマリー画像を生成 |
| `index.html` | カメラ画像閲覧UI（日次・サムネイル・手動撮影） |
| `monthly.html` | 月次サマリー閲覧UI |
| `config.py.example` | 設定テンプレート（カメラIP/パスワード等） |
| `.gitignore` | `config.py` 等の除外設定 |

## セットアップ

### 1. リポジトリ取得

```bash
git clone https://github.com/redeye147/solar-camera.git
cd solar-camera
```

### 2. 設定ファイル作成

`config.py.example` をコピーして `config.py` を作成し、各値を環境に合わせて書き換えます。

```bash
cp config.py.example config.py
nano config.py
```

設定項目：

- `CAMERA_USER` / `CAMERA_PASS` / `CAMERA_HOST` — RTSPカメラの認証情報とIP
- `CAMERA_PATH` — カメラ機種により異なるストリームパス（例: `h264Preview_01_sub`）
- `CONOHA_HOST` / `CONOHA_USER` — ConoHa VPSのIPとSSHユーザー名
- `CONOHA_REMOTE_BASE` — VPS上の画像配信ディレクトリ（例: `/var/www/html/solar`）
- `SSH_KEY` — Raspberry Pi → ConoHa への認証用SSH秘密鍵パス
- `GMAIL_ADDRESS` — 通知用Gmailアドレス（将来拡張用）

> ⚠️ `config.py` は `.gitignore` で除外されています。**絶対にコミットしないでください。**

### 3. 依存パッケージ

Raspberry Pi 側で以下が必要です：

```bash
sudo apt install ffmpeg python3-pil
```

ConoHa VPS 側に画像配信用のディレクトリを作成しておきます：

```bash
mkdir -p /var/www/html/solar/{images,monthly}
```

### 4. SSH鍵の配置

Raspberry Pi → ConoHa の鍵認証を有効にしておきます（`config.py` の `SSH_KEY` で指定したパス）。

### 5. cron設定例

Raspberry Pi の crontab：

```cron
# 毎時0分に自動撮影
0 * * * * /usr/bin/python3 /home/pi/solar/capture.py >> /home/pi/solar/capture.log 2>&1

# 1分毎に手動撮影トリガーをポーリング
* * * * * /usr/bin/python3 /home/pi/solar/poll.py >> /home/pi/solar/poll.log 2>&1

# 5分毎にネットワーク自己診断
*/5 * * * * /usr/bin/python3 /home/pi/solar/check_network.py

# 毎月1日 03:00 に前月の月次合成
0 3 1 * * /usr/bin/python3 /home/pi/solar/monthly_composite.py >> /home/pi/solar/monthly.log 2>&1
```

## 動作概要

### 自動撮影フロー（`capture.py`）

1. ffmpeg + RTSPでカメラから1フレームを取得
2. PIL でリサイズ（横1280px）、品質を段階的に下げて60KB以下に圧縮
3. `YYYYMMDD_HHMM.jpg` のファイル名でConoHaへSCP転送
4. 転送成功後、ローカル一時ファイルを削除

### 手動撮影トリガー（`poll.py`）

1. ConoHa上の `trigger` ファイル存在を確認
2. あれば `capture.py` を実行し、`trigger` を削除
3. 手動分は分が `00` 以外になるため、UI上で「手動」ラベル表示

### ネットワーク構成

NetworkManager の route metric で出口を決めます（小さいほど優先）。

| 接続 | デバイス | metric | 役割 |
| --- | --- | --- | --- |
| `nihontsushin` (gsm) | SIMドングル (wwan0) | 700 | 主回線 |
| `eth0-auto` | USB LAN (eth0) | 800 | 予備回線 / 現場ではカメラLAN |

```bash
sudo nmcli connection modify nihontsushin ipv4.route-metric 700
sudo nmcli connection modify eth0-auto ipv4.never-default no ipv4.route-metric 800
```

> Tailscale のノードは管理画面で **Disable key expiry** にしておくこと（既定の180日で期限切れになり遠隔接続できなくなる）。

### ネットワーク自己復旧（`check_network.py`）

1. 1.1.1.1 / 8.8.8.8 への ping で「インターネットに出られるか」を判定（約15秒の猶予で瞬断は無視）
2. 断のときは段階的に復旧: SIM再接続 → モデムリセット → LAN再接続
3. 復旧できない状態が `NET_REBOOT_AFTER_RUNS` 回（既定6回=30分）続くごとに再起動
4. 復旧時・経路変更（wwan0⇔eth0）時に `network_alert.txt`（直近200行）を ConoHa へ送信

### 月次サマリー（`monthly_composite.py`）

- 前月の各日12:00画像を6列のグリッド合成し、`YYYYMM.jpg` として生成・転送

## ライセンス

個人利用前提のため未指定。
