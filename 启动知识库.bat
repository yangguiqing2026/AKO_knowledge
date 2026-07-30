@echo off
chcp 65001 >nul
title AKO 知识库服务

echo ========================================
echo   AKO 知识库服务
echo ========================================
echo.

cd /d "%~dp0"

:: 检查 Python
python --version >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python
    pause
    exit /b 1
)

echo === 配置信息 ===
python -c "from config_loader import get_config; c=get_config(); print(c.get_profile_info())"
echo ==================
echo.

echo 启动模式:
echo   1. API 服务 (Uvicorn)
echo   2. 交互查询 (query.py)
echo   3. 入库 PDF
echo   4. 入库多格式 (PDF+Word+PPT)
echo   5. 切换配置
echo.

set /p mode="请选择 (1-5): "

if "%mode%"=="1" (
    echo [启动] API 服务 http://localhost:8000
    python -m uvicorn knowledge_service:app --host 0.0.0.0 --port 8000 --reload
)
if "%mode%"=="2" (
    echo [启动] 交互查询模式
    python query.py
)
if "%mode%"=="3" (
    echo [启动] PDF 入库
    python ingest_pdf.py
)
if "%mode%"=="4" (
    echo [启动] 多格式入库
    python ingest_all_v2.py
)
if "%mode%"=="5" (
    echo [启动] 配置切换
    python switch_config.py
)

echo.
pause