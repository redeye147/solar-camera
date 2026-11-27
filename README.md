# solar-camera

太陽光発電所の遠隔監視カメラシステム。Raspberry Pi に接続したRTSPカメラで定期的に撮影し、ConoHa VPS上のWebサーバーへ画像を転送・公開します。

## 構成

```
                    ┌──────────── 現場（ルーター無し） / 自宅 ────────────┐
[Reolinkカメラ] ─LAN─ [USBハブ(LAN)] ─ [Raspberry Pi Zero "solarcam"] ─ [SIMドングル EC25]
 192.168.1.101(固定)                    eth0: 自宅=DHCP / 現場=192.168.1.50(固定)    │
                                        Tailscale: 100.93.198.46                    │ LTE（日本通信SIM）
                                                                                    ▼
          ┌──────────────── ConoHa VPS（solar.redeye-lab.com）────────────────┐
          │ nginx: 閲覧サイト /images /monthly、/capture → solar-trigger(:5001) │
          │ cron: check_rpi.py（毎時・撮影停止監視）/ daily_report.py（20:30）   │
          └──────────────────────────────┬──────────────────────────────────────┘
                                         ▼ Gmail（→ LINE 転送）
```

| 流れ | 仕組み |
| --- | --- |
| 定時撮影 | Pi `capture.py`（4〜20時の毎時0分）→ カメラ RTSP → ConoHa `images/` へ scp |
| 今すぐ撮影 | ブラウザ → ConoHa `/capture` → `trigger` 作成 → Pi `poll.py`（2分ごと）が撮影し、結果を `capture_result.json` に書いて `trigger` を削除 → 画面が成功・失敗を表示 |
| 転送失敗 | Pi `retry/` に退避 → `poll.py` が再送 |
| ネットワーク監視 | Pi `check_network.py`（5分ごと）→ 異常だけ ConoHa `network_alert.txt` に追記 → `daily_report.py`（20:30）がメール |
| 撮影停止監視 | ConoHa `check_rpi.py`（毎時）→ 予定の撮影が2回続けて届かなければ [緊急]、再開で [復旧] |
| 月次合成 | Pi `monthly_composite.py`（毎日21:05）→ ConoHa `monthly/` |
| 通信量 | Pi `monthly_traffic.py`（毎月7日）→ ConoHa `traffic_report.txt` → 20:30 のメール |
| 遠隔保守 | Tailscale（`ssh pi@solarcam`）。状態の一覧は `~/solar/status.sh` |
| 定期再起動 | Pi crontab `45 2 * * *` で `power_cut_prepare.sh`: SD カードを読み取り専用にしてタイマーコンセントの電源断（2:50〜2:55）を待つ。電源が切れなければ 3:05 に自分で再起動（切り替えは `setup_power_timer.sh`、旧方式は `0 3 * * *` の reboot） |

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
| `setup_modem_delay.sh` | ModemManager の起動を遅らせ、起動直後に SIM がつながらない問題を防ぐ |
| `power_cut_prepare.sh` | 毎日 2:45 に SD カードを読み取り専用にし、タイマーコンセントの電源断を待つ（来なければ自分で再起動） |
| `auto_update.sh` | 毎日 21:30 に GitHub の main を自動適用。更新前の健康診断・文法チェック、更新後の健康診断とログのエラー確認を行い、だめなら自動で元の版に戻す（`--install` で cron 登録、`.no_auto_update` で一時停止） |
| `setup_power_timer.sh` | crontab の毎日の再起動を `power_cut_prepare.sh` 方式に切り替える（`--revert` で元に戻す） |
| `index.html` | カメラ画像閲覧UI（日次・サムネイル・手動撮影） |
| `monthly.html` | 月次サマリー閲覧UI |
| `config.py.example` | 設定テンプレート（カメラIP/パスワード等） |
| `status.sh` | solarcam と ConoHa の状態を一覧表示 |
| `server/` | ConoHa 側のスクリプト・設定（`deploy.sh` で配置。`capture_trigger.py`・nginx・systemd は現物の写し） |
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

# 毎日2:45に SD を読み取り専用にしてタイマーコンセントの電源断を待つ（setup_power_timer.sh で設定）
45 2 * * * sudo /home/pi/solar/power_cut_prepare.sh

# 毎日21:05に当月の月次合成を更新
5 21 * * * /usr/bin/python3 /home/pi/solar/monthly_composite.py >> /home/pi/solar/monthly.log 2>&1

# 毎月7日 01:30 に前の課金期間（7日〜翌6日）のSIM通信量レポート（要 vnstat）
30 1 7 * * /usr/bin/python3 /home/pi/solar/monthly_traffic.py >> /home/pi/solar/traffic.log 2>&1
```

### 6. 運用モード切替

- `mode_test.sh` — Wi-Fi を有効化（自宅での保守用）
- `mode_production.sh` — Wi-Fi を無効化（現場運用）

### 7. ConoHa 側スクリプト（`server/`）

| ファイル | 役割 | ConoHa の cron |
| --- | --- | --- |
| `server/check_rpi.py` | 撮影予定（4〜20時の毎時）に対し画像が2回続けて届かなければ停止アラート、再開で復旧通知 | `0 * * * *` |
| `server/daily_report.py` | Pi から追記された異常ログ・通信量レポートを毎日メール（異常ログは直近60日・最新20件まで）。送信後は全件を `~/archive/` に追記保存して元ファイルを削除 | `30 20 * * *` |
| `server/line_daily_report.py` | LINE 用の日報メール（発電量・金額・日射量・気温・今月累計・PCS/回線の状態・12時の写真）。件名「[日報]」を Gmail の GAS が LINE に転送。PCS の発電量の差・発電効率の低下（晴れの日が3回続けて直近30日の平常値の85%未満）・みえるーぷの警報・撮影の欠けを ⚠️ で知らせる。`--dry-run` で送らずに表示 | `0 22 * * *` |
| `server/mieloop.py` | みえるーぷ（発電所の監視サービス）にログインし、日別 CSV（発電量・金額・日射量・気温）と警報一覧を取得。ログイン情報は `~/.solar_mieloop.conf`（chmod 600、リポジトリ外） | — |
| `server/mailer.py` | 共通のメール送信。認証情報は `~/.solar_mail.conf`（chmod 600、リポジトリ外） | — |

Raspberry Pi から配置する（既存スクリプトは `~/backup_日時/` に退避。初回は既存の `daily_report.py` から `~/.solar_mail.conf` を作成）:

```bash
cd ~/solar && server/deploy.sh
```

通知の設定確認（テストメール送信）は ConoHa で `python3 ~/check_rpi.py --test`。

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

### 自動更新（`auto_update.sh`）

現場の Pi は毎日 21:30 に GitHub の `main` を自動で取り込む。止まって現地に行くことにならないよう、次の順で安全を確かめる。

1. 一時停止ファイル `~/solar/.no_auto_update` があれば何もしない（大きな変更の前に `touch`、終わったら `rm`）
2. 更新前の健康診断（インターネット・ConoHa・カメラ・Tailscale）。異常があれば更新しない
3. 新しい版の文法チェック（Python・sh）。誤りがあれば更新しない
4. 適用後、約6分待って（check_network・poll が新しいコードで動く）健康診断とログの Traceback を確認。だめなら元の版に戻す
5. `server/`・画面のファイルが変わっていれば ConoHa へ配置
6. 結果（更新・見送り・巻き戻し）は異常通知として 20:30 のメールに載る

自動で更新するのはリポジトリのファイルだけ。crontab・NetworkManager・systemd などのシステム設定は手動で行う。

```bash
cd ~/solar && ./auto_update.sh --install   # cron に登録（30 21 * * *）
tail ~/solar/update.log                    # 実行の記録
```

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
- `setup_modem_delay.sh`: ModemManager の起動を30秒遅らせ（systemd drop-in）、起動直後の QMI ポート取りこぼし自体を防ぐ（一度実行すればよい）
- 起動から10分以内に検出して自動で直った断・SIM不調は記録（`network.log`）だけで通知しない（毎日3時の再起動直後は SIM がつながらないことが多く、ModemManager 再起動で直るため）。10分を過ぎても直らなければ通知
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
