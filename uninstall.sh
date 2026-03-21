#!/bin/bash
SERVICE_NAME="telegram-bridge.service"
SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"

# 停止运行中的服务
systemctl stop "$SERVICE_NAME" >/dev/null 2>&1

# 禁用开机自启
systemctl disable "$SERVICE_NAME" >/dev/null 2>&1

# 删除服务文件
rm -f "$SERVICE_PATH"

# 重载systemd配置
systemctl daemon-reload

echo "✅ Telegram Bridge 服务已完全卸载！"
