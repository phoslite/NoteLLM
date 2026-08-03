@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================
echo   读书阅读助手 一键启动
echo   - 后端 API  http://127.0.0.1:8321
echo   - 前端页面  http://127.0.0.1:5173
echo   - 停止服务：start.bat stop
echo     （或本窗口启动完成后按任意键停止）
echo ================================================
echo.

rem --- 子命令：stop / restart ---
if /i "%~1"=="stop" goto :do_stop
if /i "%~1"=="restart" goto :do_restart

:main
where node >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Node.js，请先安装 https://nodejs.org
    pause
    exit /b 1
)
if not exist "backend\.venv\Scripts\python.exe" (
    echo [错误] 后端依赖未安装，请先执行：
    echo   cd backend
    echo   python -m venv .venv
    echo   .venv\Scripts\python -m pip install -e ".[dev]"
    echo   copy .env.example .env    ^(并填写 AI_API_KEY^)
    pause
    exit /b 1
)
if not exist "frontend\node_modules" (
    echo [错误] 前端依赖未安装，请先执行：
    echo   cd frontend
    echo   pnpm install
    pause
    exit /b 1
)

rem --- 端口占用检测：已在运行则跳过启动，避免重复启动报 10048 ---
netstat -ano | findstr ":8321 " | findstr "LISTENING" >nul 2>nul
if not errorlevel 1 (
    echo [提示] 后端已在运行 http://127.0.0.1:8321 ，跳过启动
) else (
    echo [1/3] 启动后端 ^(8321^)...
    start "LLMnotebook 后端" cmd /k "cd /d %~dp0backend && .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8321"
)

netstat -ano | findstr ":5173 " | findstr "LISTENING" >nul 2>nul
if not errorlevel 1 (
    echo [提示] 前端已在运行 http://127.0.0.1:5173 ，跳过启动
    goto :front_done
)

echo [2/3] 启动前端 ^(5173^)...
where pnpm >nul 2>nul
if not errorlevel 1 goto :front_pnpm
if exist "frontend\node_modules\vite\bin\vite.js" goto :front_vite
if exist "%LOCALAPPDATA%\pnpm\pnpm.cmd" goto :front_localpnpm
if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback\pnpm.cmd" goto :front_runtime_pnpm
echo [错误] 未找到 pnpm 或 vite，请先安装 pnpm：npm install -g pnpm
pause
exit /b 1

:front_pnpm
start "LLMnotebook 前端" cmd /k "cd /d %~dp0frontend && pnpm dev --host 127.0.0.1"
goto :front_done

:front_vite
start "LLMnotebook 前端" cmd /k "cd /d %~dp0frontend && node node_modules\vite\bin\vite.js --host 127.0.0.1"
goto :front_done

:front_localpnpm
start "LLMnotebook 前端" cmd /k "cd /d %~dp0frontend && "%LOCALAPPDATA%\pnpm\pnpm.cmd" dev --host 127.0.0.1"
goto :front_done

:front_runtime_pnpm
start "LLMnotebook 前端" cmd /k "cd /d %~dp0frontend && "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback\pnpm.cmd" dev --host 127.0.0.1"
goto :front_done

:front_done
echo [3/3] 等待服务就绪，自动打开浏览器...
ping -n 9 127.0.0.1 >nul
start "" http://127.0.0.1:5173
echo.
echo 启动完成。两个服务窗口保持运行。
echo 本窗口保持等待：按任意键停止前后端服务并退出；
echo 或随时另开窗口运行：start.bat stop
echo.
pause >nul
call :stop_services
exit /b 0

rem --- 停止前后端服务（按端口找 PID，结束进程树） ---
:do_stop
call :stop_services
exit /b %errorlevel%

:do_restart
call :stop_services
echo.
echo 正在重新启动...
goto :main

:stop_services
echo [停止] 正在关闭前后端服务...
set "FOUND="
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8321 " ^| findstr "LISTENING"') do (
    taskkill /F /T /PID %%a >nul 2>nul && (echo   已停止后端进程 PID=%%a & set "FOUND=1")
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173 " ^| findstr "LISTENING"') do (
    taskkill /F /T /PID %%a >nul 2>nul && (echo   已停止前端进程 PID=%%a & set "FOUND=1")
)
if not defined FOUND echo   [提示] 未检测到运行中的前后端服务（8321/5173 均未监听）
echo [停止] 完成
exit /b 0