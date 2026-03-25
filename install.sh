#!/bin/bash
SERVICE_NAME="telegram-bridge.service"
SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"
# 自动获取当前脚本所在的项目目录（绝对路径）
PROJECT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

echo "ℹ️  检测到项目目录: $PROJECT_DIR"

# 检查虚拟环境是否存在
if [ ! -d "$PROJECT_DIR/venv" ]; then
    echo "⚠️  未检测到虚拟环境，正在自动创建..."
    python3 -m venv "$PROJECT_DIR/venv"
    echo "✅ 虚拟环境创建完成，正在安装依赖包..."
    source "$PROJECT_DIR/venv/bin/activate"
    pip install -r "$PROJECT_DIR/requirements.txt"
    echo "✅ 依赖安装完成"
fi

# 动态生成systemd服务配置文件
echo "🔧 正在生成服务配置文件..."
cat > "$SERVICE_PATH" << EOF
[Unit]
Description=Telegram Bridge Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$PROJECT_DIR
# 优化启动命令：使用最高优化级别的Python解释器
ExecStart=/bin/bash -c 'source $PROJECT_DIR/venv/bin/activate && python -OO $PROJECT_DIR/main.py'
Restart=always
RestartSec=5

# 环境变量优化：极致内存压缩
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONOPTIMIZE=2
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=MALLOC_TRIM_THRESHOLD_=65536
Environment=MALLOC_MMAP_THRESHOLD_=131072
Environment=PYTHONMALLOC=malloc

# 系统资源限制（256M内存限制）
Nice=10
MemoryLimit=256M
MemoryHigh=240M
CPUQuota=20%
PrivateTmp=true
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=$PROJECT_DIR/logs
ProtectHome=read-only

[Install]
WantedBy=multi-user.target
EOF

# 设置服务文件权限
chmod 644 "$SERVICE_PATH"

# 重载systemd配置
systemctl daemon-reload

# 启用服务开机自启
systemctl enable "$SERVICE_NAME"

# 启动服务
systemctl start "$SERVICE_NAME"

echo ""
echo "🎉 Telegram Bridge 服务安装成功！"
echo "----------------------------------------"
echo "📂 项目目录: $PROJECT_DIR"
echo "👉 查看状态: systemctl status $SERVICE_NAME"
echo "👉 实时日志: journalctl -u $SERVICE_NAME -f"
echo "👉 重启服务: systemctl restart $SERVICE_NAME"
echo "👉 停止服务: systemctl stop $SERVICE_NAME"
echo "👉 卸载服务: ./uninstall.sh"
echo "----------------------------------------"
