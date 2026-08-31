@echo off
REM ============================================================================
REM  START THE TAILSCALE DOOR.  Double-click. That is the whole thing.
REM
REM  Starts the engine (or reuses it if already running), then opens the
REM  Tailscale Funnel, then PROVES ChatGPT can actually get through.
REM
REM  Safe to run when the ngrok door is already open: both doors lead to the
REM  same engine, so this just adds a second way in and touches nothing else.
REM
REM  Engine BEFORE funnel, deliberately. A funnel opened over a dead engine
REM  answers 502, which looks exactly like a broken tunnel and sends you
REM  debugging the one part that was fine.
REM
REM  To close it:  stop-tailscale.bat
REM  If ChatGPT stops connecting:  diagnose.bat
REM ============================================================================
setlocal
cd /d "%~dp0"
title Harness - Tailscale

echo.
echo  ================================================
echo   HARNESS - starting the TAILSCALE door
echo  ================================================
echo.

REM --- 1/4  Tailscale must be logged in ---------------------------------------
echo  [1/4] Checking Tailscale...
tailscale status >nul 2>&1
if errorlevel 1 (
    echo.
    echo  X  Tailscale is not logged in.
    echo.
    echo     Run:  tailscale up
    echo.
    echo     If that fails, THIS NETWORK IS BLOCKING TAILSCALE. Public, guest
    echo     and some hotspot networks filter VPN control servers by name in
    echo     the TLS handshake. Nothing on your side fixes it.
    echo.
    echo     USE THE OTHER DOOR:  start-ngrok.bat
    echo     That is exactly what it is for. It never touches Tailscale.
    echo.
    pause
    exit /b 1
)
echo        ok - logged in
echo.

REM --- 2/4  Engine + Workbench ------------------------------------------------
REM  Its own window, so closing THIS window does not kill the engine, and the
REM  engine's log stays readable instead of scrolling past the health check.
echo  [2/4] Engine on :8848...
powershell -NoProfile -Command "if (Get-NetTCPConnection -State Listen -LocalPort 8848 -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
if not errorlevel 1 (
    echo        ok - already running, reusing it
    goto engineup
)
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
    echo     Run stop-tailscale.bat and stop-ngrok.bat first, then try again.
    echo.
    pause
    exit /b 1
)
REM  ping, not `timeout`: timeout reads the console directly and dies with
REM  "Input redirection is not supported" whenever stdin is not a real console
REM  (scripted runs, CI, piped invocations). The wait still worked, but it
REM  printed four lines of red ERROR text that look like a real failure.
ping -n 2 127.0.0.1 >nul
goto waitloop
:engineup
echo.

REM --- 3/4  Open the tunnel ---------------------------------------------------
echo  [3/4] Opening the Tailscale Funnel...
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\funnel.ps1"
if errorlevel 1 (
    echo.
    echo  X  The funnel did not start. Try re-registering it:
    echo        tailscale funnel reset
    echo        tailscale funnel --bg 8848
    echo.
    echo     Note: `tailscale funnel ^<port^> off` no longer exists. Tailscale's
    echo     own output still suggests an "off" form - ignore it, use reset.
    echo.
    pause
    exit /b 1
)
echo.

REM --- 4/4  Prove ChatGPT can actually reach it -------------------------------
REM  The only step that tests the REAL path. `tailscale funnel status` reads
REM  local config and will say "Funnel on" while the public ingress has no
REM  route here, and probing the *.ts.net name from this machine is answered
REM  inside the tailnet -- so both of those look healthy when nothing works.
echo  [4/4] Checking the path ChatGPT actually uses...
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\check-funnel.ps1"
if errorlevel 1 (
    echo.
    echo  X  Not reachable from the internet. The check above says which cause.
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
echo   READY - Tailscale door is open
echo.
echo   Workbench :  http://127.0.0.1:8849
echo   ChatGPT   :  paste the ts.net URL printed above
echo  ================================================
echo.
start "" http://127.0.0.1:8849
echo  You can close THIS window. The engine keeps running in its own window.
echo  Do NOT close the "Harness engine" window - that stops the harness, and
echo  nothing restarts it. If ChatGPT stops connecting, run diagnose.bat.
echo.
pause
