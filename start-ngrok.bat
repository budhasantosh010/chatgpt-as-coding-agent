@echo off
REM ============================================================================
REM  Double-click this to run the harness through ngrok INSTEAD OF Tailscale.
REM
REM  This is a complete standalone path. It never touches Tailscale, so it
REM  works on the exact networks that break the funnel -- which is the whole
REM  reason it exists. start-harness.bat gates on `tailscale status` and would
REM  refuse to start the engine at all on such a network.
REM
REM  If the engine is already running (from start-harness.bat), this reuses it
REM  and just adds the second door. Both tunnels can be open at once: two roads
REM  to one localhost:8848, so the same tasks, files and evidence sit behind
REM  either one and switching networks mid-task migrates nothing.
REM
REM  stop-harness.bat shuts the engine down. stop-ngrok.ps1 closes just this
REM  door and leaves the funnel alone.
REM ============================================================================
setlocal
cd /d "%~dp0"
title Harness - ngrok

echo.
echo  ================================================
echo   HARNESS - starting via ngrok
echo  ================================================
echo.

REM --- 1/3  Engine + Workbench -------------------------------------------------
REM  ngrok forwards to a port. If nothing is listening it still reports itself
REM  "online" and ChatGPT gets a 502 that looks like a harness fault.
echo  [1/3] Engine on :8848...
powershell -NoProfile -Command "if (Get-NetTCPConnection -State Listen -LocalPort 8848 -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
if not errorlevel 1 (
    echo        ok - already running, reusing it
    goto engineup
)

REM  Its own window, so closing this one does not kill the engine, and the
REM  engine's log stays readable instead of scrolling past the health check.
echo        not running - starting it
start "Harness engine" cmd /k "cd /d "%~dp0" && python -m harness up"

echo        waiting for the engine to bind :8848 ...
set /a _tries=0
:waitloop
set /a _tries+=1
REM  if/else, not a ternary: Windows PowerShell 5.1 has no `? :` operator.
powershell -NoProfile -Command "if (Get-NetTCPConnection -State Listen -LocalPort 8848 -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
if not errorlevel 1 goto engineup
if %_tries% GEQ 30 (
    echo.
    echo  X  The engine never came up. Look at the "Harness engine" window.
    echo     A [Errno 10048] there means an old engine still holds the port.
    echo     Run stop-harness.bat first, then try again.
    echo.
    pause
    exit /b 1
)
timeout /t 1 /nobreak >nul
goto waitloop
:engineup
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
    echo     Still stuck? Run  diagnose.bat  - it checks outward from the
    echo     engine and names the broken part. A 502 there means the tunnel
    echo     is FINE and the engine is down; do not reconfigure the tunnel.
    echo.
    pause
    exit /b 1
)

echo.
echo  ================================================
echo   READY - via ngrok
echo.
echo   Workbench :  http://127.0.0.1:8849
echo   ChatGPT   :  paste the ngrok URL printed above
echo                as its OWN connector. A connector is
echo                bound to one URL and caches its tool
echo                menu per URL - it cannot be repointed.
echo  ================================================
echo.
start "" http://127.0.0.1:8849
echo  This window can be closed. The engine keeps running in its own window.
echo  Do NOT close the "Harness engine" window - that stops the harness, and
echo  nothing restarts it. ngrok is not a service either: it does not survive
echo  a reboot, so run this file again after one. If ChatGPT stops connecting,
echo  run diagnose.bat.
echo.
pause
