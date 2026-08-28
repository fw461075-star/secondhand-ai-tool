@echo off
chcp 65001 >nul
echo ==========================================
echo   启动 NapCat + QQ
echo ==========================================
echo.

:: 检查管理员权限
net session >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo 需要管理员权限，正在请求...
    powershell -Command "Start-Process '%~f0' -Verb runAs"
    exit
)

:: 设置环境变量
set "NAPCAT_PATCH_PACKAGE=C:\NapCat\qqnt.json"
set "NAPCAT_LOAD_PATH=C:\NapCat\loadNapCat.js"
set "NAPCAT_INJECT_PATH=C:\NapCat\NapCatWinBootHook.dll"
set "NAPCAT_LAUNCHER_PATH=C:\NapCat\NapCatWinBootMain.exe"
set "NAPCAT_MAIN_PATH=C:\NapCat\napcat.mjs"

:: 创建loadNapCat.js
echo (async () =^> {await import("file:///%NAPCAT_MAIN_PATH:\=/%")})() > "C:\NapCat\loadNapCat.js"

:: 检查QQ路径
if not exist "C:\Program Files\Tencent\QQNT\QQ.exe" (
    echo 错误: 找不到 QQ.exe
    pause
    exit /b
)

:: 启动 NapCat + QQ
echo 正在启动 NapCat 和 QQ...
echo 如果QQ需要扫码登录，请完成登录后 NapCat 会自动加载
echo.
"%NAPCAT_LAUNCHER_PATH%" "C:\Program Files\Tencent\QQNT\QQ.exe" "%NAPCAT_INJECT_PATH%"

echo.
echo NapCat 已启动
echo WebSocket 端口: 3001
echo Web UI: http://127.0.0.1:6099
echo.
pause
