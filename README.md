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
| `monthly_composite.py` | 当月の毎日12:00画像をグリッド合成し、月次サマリー画像を生成 |
| `monthly_traffic.py` | SIM(wwan0)の通信量を課金期間でvnstat集計しレポート転送 |
| `mode_test.sh` / `mode_production.sh` | Wi-Fiの有効/無効切替（保守用/本番用） |
| `setup_site_network.sh` | 現場（ルーター無し）用に eth0 の予備固定IPプロファイルを作成 |
| `index.html` | カメラ画像閲覧UI（日次・サムネイル・手動撮影） |
| `monthly.html` | 月次サマリー閲覧UI |
| `config.py.example` | 設定テンプレート（カメラIP/パスワード等） |
| `.gitignore` | `config.py` 等の除外設定 |

## セットアップ

### 1. リポジトリ取得

Raspberry Pi の `/home/pi/solar` は GitHub の `main` を追跡する作業フォルダーです。

```bash
git clone https://github.com/redeye147/solar-camera.git /home/pi/solar
cd /home/pi/solar
```

### 更新の反映（Mac などから）

```bash
ssh pi@solarcam 'cd ~/solar && git pull --ff-only && git log --oneline -1'
```

- Pi 上でファイルを直接編集していると `--ff-only` で止まります（上書きはしません）。その場合は `git status` で確認してください。
- `config.py`・ログ・`retry/` などは Git の管理対象外です。

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
# 4〜20時の毎時0分に自動撮影
0 4-20 * * * /usr/bin/python3 /home/pi/solar/capture.py >> /home/pi/solar/capture.log 2>&1

# 2分毎に手動撮影トリガーとリトライ転送
*/2 * * * * /usr/bin/python3 /home/pi/solar/poll.py >> /home/pi/solar/poll.log 2>&1

# 5分毎にネットワーク自己診断
*/5 * * * * /usr/bin/python3 /home/pi/solar/check_network.py >> /home/pi/solar/network.log 2>&1

# 毎日21:05に当月の月次合成を更新
5 21 * * * /usr/bin/python3 /home/pi/solar/monthly_composite.py >> /home/pi/solar/monthly.log 2>&1

# 毎月7日 01:30 に前の課金期間（7日〜翌6日）のSIM通信量レポート（要 vnstat）
30 1 7 * * /usr/bin/python3 /home/pi/solar/monthly_traffic.py >> /home/pi/solar/traffic.log 2>&1
```

### 6. 運用モード切替

- `mode_test.sh` — Wi-Fi を有効化（自宅での保守用）
- `mode_production.sh` — Wi-Fi を無効化（現場運用）

## 動作概要

### 自動撮影フロー（`capture.py`）

1. ffmpeg + RTSPでカメラから1フレームを取得（カメラが一時的に応答しないときは15秒待って最大3回まで撮り直し。ファイル名の時刻は撮影開始時刻で固定）
2. PIL でリサイズ（横1280px）、品質を段階的に下げて60KB以下に圧縮
3. `YYYYMMDD_HHMM.jpg` のファイル名でConoHaへSCP転送
4. 転送成功後、ローカル一時ファイルを削除（失敗時は `retry/` に退避し `poll.py` が再送）
5. ログ（`capture.log`）は各行に時刻付き。カメラのパスワードは伏せ字

### 手動撮影トリガー（`poll.py`）

1. ConoHa上の `trigger` ファイル存在を確認
2. あれば `capture.py` を実行し、`trigger` を削除
3. 手動分は分が `00` 以外になるため、UI上で「手動」ラベル表示

### ネットワーク構成

NetworkManager の route metric で出口を決めます（小さいほど優先）。

| 接続 | デバイス | metric | 役割 |
| --- | --- | --- | --- |
| `eth0-auto` | USB LAN (eth0) | 600 | 優先。自宅ではルーター経由で通信し SIM を節約 |
| `nihontsushin` (gsm) | SIMドングル (wwan0) | 700 | 予備。現場（eth0 はカメラ用でゲートウェイ無し）では自動的にこちら |

```bash
sudo nmcli connection modify nihontsushin ipv4.route-metric 700 && sudo nmcli connection up nihontsushin
sudo nmcli connection modify eth0-auto ipv4.never-default no ipv4.route-metric 600 && sudo nmcli device reapply eth0
```

- LAN のゲートウェイはあるのにインターネットに出られないとき（ルーター/回線障害）は、`check_network.py` が eth0 の metric を 900 に下げて SIM に切り替え、LAN が戻れば 600 に戻します。
- SIM の接続設定は特定のポート名に固定しない（`sudo nmcli connection modify nihontsushin connection.interface-name ""`）。モデムの見え方が変わってもつながるようにするため。
- モデム（SIM）側の metric 変更は `nmcli device reapply` では反映されず、SIM の経路が消えることがあるため、必ず `nmcli connection up` で張り直すこと。

### 現場（ルーター無し）での eth0 固定IP

現場には DHCP を配るルーターが無いため、Pi とカメラの両方に固定IPが必要です。

| 機器 | 自宅（ルーターあり） | 現場（ルーター無し） |
| --- | --- | --- |
| Pi の eth0 | `eth0-auto`（DHCP、優先度10） | DHCP が30秒で失敗すると `eth0-site`（固定IP・ゲートウェイ無し）に自動切替 |
| カメラ | 固定IP（カメラ側で設定） | 同じ固定IP |

```bash
./setup_site_network.sh 192.168.1.50/24   # ルーターの DHCP 割当範囲外の空きアドレス
```

- カメラ（Reolink）はアプリ／Web設定で DHCP → 静的（固定）IP に変更し、`config.py` の `CAMERA_HOST` と一致させる。
- Pi とカメラの固定IPは、自宅ルーターの DHCP 割当範囲の外にすること（重複防止）。
- `eth0-site` で動作中は、`check_network.py` の復旧処理は LAN（DHCP）を張り直さない。
- 自宅に戻してケーブルを挿し直すと、`eth0-auto`（DHCP）が優先して使われる。

> Tailscale のノードは管理画面で **Disable key expiry** にしておくこと（既定の180日で期限切れになり遠隔接続できなくなる）。

### ネットワーク自己復旧（`check_network.py`）

1. 1.1.1.1 / 8.8.8.8 への ping で「インターネットに出られるか」を判定（約15秒の猶予で瞬断は無視）
2. LAN だけ不通で SIM が生きていれば、eth0 の metric を下げて SIM に切替（LAN 復帰で自動的に戻す）
3. どの経路でも出られないときは段階的に復旧: SIM再接続 → ModemManager再起動 → モデムリセット → LAN再接続
   - 起動時に ModemManager が QMI ポート（`cdc-wdm0`）を取りこぼし、AT ポート（`ttyUSB2`）だけで認識してデータ接続できないことがある（EC25）。ModemManager の再起動で直る
- 予備回線（SIM）の健康診断: LAN で通信中も毎回 SIM 経由の疎通を確認し、だめなら SIM だけ復旧（30分に1回まで）して異常・復旧を通知
4. 復旧できない状態が `NET_REBOOT_AFTER_RUNS` 回（既定6回=30分）続くごとに再起動
5. 異常（断の検出・復旧、SIM切替、再起動）だけを `network_alert.txt` に記録し、まだ送っていない行だけを ConoHa の `network_alert.txt` に追記（ConoHa の `daily_report.py` が毎日 20:30 にメールし、送信後に消す）
6. 経路変更（ケーブル抜き差しなど）は異常ではないので `network.log` に記録するだけ

### 月次サマリー（`monthly_composite.py`）

- 当月の各日12:00画像を6列のグリッド合成し、`YYYYMM.jpg` として生成・転送（毎日実行で途中経過を更新）

### SIM通信量レポート（`monthly_traffic.py`）

- vnstat の日別データから wwan0 の通信量を b-mobile の課金期間（既定: 7日〜翌月6日、`BILLING_START_DAY`）で集計し、上限（既定1000MB）に対する使用率を `traffic_report.txt` として転送
- `monthly_traffic.py --current` で今期の途中経過と期間末の見込みを表示（転送はしない）

## ライセンス

個人利用前提のため未指定。
