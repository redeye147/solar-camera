#!/bin/bash
# テストモード: Wi-Fiを有効化する（自宅での保守用）
echo "テストモードに切替中..."
sudo nmcli radio wifi on
sleep 5
echo "WiFi有効化完了"
ip addr | grep "inet "
