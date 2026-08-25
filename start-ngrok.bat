@echo off
REM ============================================================================
REM  Double-click this to open the SECOND door to the harness, through ngrok.
REM
REM  Use it when the network blocks Tailscale. It does NOT replace or disturb
REM  the funnel -- both can be open at once. They are two roads to the same
REM  localhost:8848, so the same tasks, files and evidence sit behind either.
REM
REM  Run start-harness.bat first. This only adds the door; it does not start
REM  the engine.
REM ============================================================================
setlocal
cd /d "%~dp0"
title Harness - ngrok door

echo.
echo  ================================================
echo   HARNESS - opening the ngrok door
echo  ================================================
echo.

REM --- 1/3  The engine has to be up first --------------------------------------
REM  ngrok forwards to a port. If nothing is listening it still reports itself
REM  "online" and ChatGPT gets a 502 that looks like a harness fault.
echo  [1/3] Checking the engine is listening on :8848...
powershell -NoProfile -Command "if (Get-NetTCPConnection -State Listen -LocalPort 8848 -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
if errorlevel 1 (
    echo.
    echo  X  The engine is not running.
    echo.
    echo     Run start-harness.bat first, then this file.
    echo.
    pause
    exit /b 1
)
echo        ok - engine listening
echo.

REM --- 2/3  Open the tunnel ----------------------------------------------------
echo  [2/3] Starting ngrok on your reserved domain...
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\ngrok.ps1"
if errorlevel 1 (
    echo.
    echo  X  ngrok did not start. The message above says why.
    echo.
    pause
    exit /b 1
)
echo.

REM --- 3/3  Prove ChatGPT can actually get through -----------------------------
REM  "ngrok online" only means the agent reached ngrok's edge. It says nothing
REM  about whether the harness accepts what arrives -- a 403 from an engine
REM  started before HARNESS_PUBLIC_HOST was set looks identical from there.
echo  [3/3] Checking the path ChatGPT actually uses...
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\check-ngrok.ps1"
if errorlevel 1 (
    echo.
    echo  X  Not usable yet. The check above names the cause.
    echo.
    pause
    exit /b 1
)

echo.
echo  ================================================
echo   NGROK DOOR OPEN
echo.
echo   Add the URL above as its OWN ChatGPT connector.
echo   A connector is bound to one URL and caches its
echo   tool menu per URL, so it cannot be re-pointed.
echo  ================================================
echo.
pause
