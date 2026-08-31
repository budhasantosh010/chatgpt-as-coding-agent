@echo off
REM ============================================================================
REM  START THE NGROK DOOR.  Double-click. That is the whole thing.
REM
REM  Starts the engine (or reuses it if already running), then opens the ngrok
REM  tunnel, then PROVES ChatGPT can actually get through.
REM
REM  This NEVER touches Tailscale, deliberately. It exists for the networks
REM  that block Tailscale, and start-tailscale.bat refuses to start at all on
REM  those -- so if this file called it, the one door that still works would
REM  be unopenable on exactly the networks it was built for.
REM
REM  Safe to run when the Tailscale door is already open: both doors lead to
REM  the same engine, so this just adds a second way in.
REM
REM  ngrok is NOT a service. It does not survive a reboot, so run this again
REM  after one. Your URL never changes.
REM
REM  To close it:  stop-ngrok.bat
REM  If ChatGPT stops connecting:  diagnose.bat
REM ============================================================================
setlocal
cd /d "%~dp0"
title Harness - ngrok

echo.
echo  ================================================
echo   HARNESS - starting the NGROK door
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

REM  Its own window, so closing THIS window does not kill the engine, and the
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
    echo     Run stop-ngrok.bat and stop-tailscale.bat first, then try again.
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
    echo     Run  diagnose.bat  - it checks outward from the engine and names
    echo     the broken part. A 502 there means the tunnel is FINE and the
    echo     engine is down; do not reconfigure the tunnel.
    echo.
    pause
    exit /b 1
)

echo.
echo  ================================================
echo   READY - ngrok door is open
echo.
echo   Workbench :  http://127.0.0.1:8849
echo   ChatGPT   :  paste the ngrok URL printed above
echo                as its OWN connector. A connector is
echo                bound to one URL and caches its tool
echo                menu per URL - it cannot be repointed.
echo  ================================================
echo.
start "" http://127.0.0.1:8849
echo  You can close THIS window. The engine keeps running in its own window.
echo  Do NOT close the "Harness engine" window - that stops the harness, and
echo  nothing restarts it. ngrok is not a service either: it does not survive
echo  a reboot, so run this file again after one. If ChatGPT stops connecting,
echo  run diagnose.bat.
echo.
pause
