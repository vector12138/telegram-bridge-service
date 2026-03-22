@echo off
chcp 65001 >nul
echo ==============================================
echo Telegram Bridge Service Windows 安装脚本
echo ==============================================
echo.

:: 检查Python是否安装
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ 错误：未找到Python，请先安装Python 3.8+ 并添加到PATH
    pause
    exit /b 1
)

echo ✅ 检测到Python版本：
python --version
echo.

:: 创建虚拟环境
echo 🔧 创建Python虚拟环境...
python -m venv venv
if %errorlevel% neq 0 (
    echo ❌ 虚拟环境创建失败
    pause
    exit /b 1
)
echo ✅ 虚拟环境创建完成
echo.

:: 激活虚拟环境并安装依赖
echo 📦 安装依赖包...
call venv\Scripts\activate.bat
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo ❌ 依赖安装失败
    pause
    exit /b 1
)
echo ✅ 依赖安装完成
echo.

:: 复制配置文件
if not exist config.yaml (
    echo 📄 复制配置文件...
    copy config.example.yaml config.yaml >nul
    echo ✅ 配置文件已复制为 config.yaml，请编辑后使用
) else (
    echo ℹ️  配置文件 config.yaml 已存在，跳过复制
)
echo.

echo ==============================================
echo ✅ 安装完成！
echo ==============================================
echo 下一步：
echo 1. 编辑 config.yaml 配置文件，填写你的Bot Token、Redis等信息
echo 2. 运行 start.bat 启动服务
echo 3. 访问 http://localhost:8080/api/v1/health 检查服务是否正常
echo.
pause
