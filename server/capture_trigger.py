#!/usr/bin/env python3
"""「今すぐ撮影」ボタンの受け口（ConoHa: systemd の solar-trigger.service で常駐）。

nginx の /capture → 127.0.0.1:5001/capture。トリガーファイルを作ると、
Raspberry Pi の poll.py（2分ごと）が見つけて撮影し、ファイルを消す。

※ ConoHa 上の /home/solar/capture_trigger.py（root 所有）の写し。
  変更して反映するには sudo でファイルを置き換え、
  sudo systemctl restart solar-trigger が必要。
"""
from flask import Flask, jsonify
import os

app = Flask(__name__)
TRIGGER = "/var/www/html/solar/trigger"


@app.route('/capture', methods=['POST'])
def capture():
    open(TRIGGER, 'w').close()
    return jsonify({"status": "ok"})


@app.route('/capture_status', methods=['GET'])
def status():
    exists = os.path.exists(TRIGGER)
    return jsonify({"triggered": exists})


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5001)
