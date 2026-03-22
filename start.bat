@echo off
chcp 65001 >nul
echo ==============================================
echo Telegram Bridge Service Windows 启动脚本
echo ==============================================
echo.

:: 检查虚拟环境是否存在
if not exist venv (
    echo ❌ 错误：未找到虚拟环境，请先运行 install.bat 安装
    pause
    exit /b 1
)

:: 激活虚拟环境
call venv\Scripts\activate.bat

:: 启动服务
echo 🚀 启动Telegram桥接服务...
python main.py

if %errorlevel% neq 0 (
    echo.
    echo ❌ 服务启动失败，请检查错误信息
    pause
)
