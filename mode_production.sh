#!/bin/bash
# 本番モード: Wi-Fiを無効化し、SIM(wwan0)主回線 + eth0予備で動作させる
echo "本番モードに切替中..."
sudo nmcli radio wifi off
echo "WiFi無効化完了"
ip route | grep default
