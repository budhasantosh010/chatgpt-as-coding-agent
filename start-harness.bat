@echo off
REM ============================================================================
REM  Double-click this to start the harness. Nothing else to remember.
REM
REM  It runs the four steps in the order they have to happen, and STOPS at the
REM  first one that fails with the actual fix on screen -- because the four
REM  failure modes all look identical from ChatGPT ("can't connect") and
REM  guessing between them wastes more time than checking does.
REM ============================================================================
setlocal
cd /d "%~dp0"
title Harness

echo.
echo  ================================================
echo   HARNESS - starting
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
    echo     the TLS handshake. Nothing on your side fixes it. Use home Wi-Fi.
    echo.
    pause
    exit /b 1
)
echo        ok - logged in
echo.

REM --- 2/4  Open the tunnel ---------------------------------------------------
echo  [2/4] Opening the Tailscale Funnel...
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\funnel.ps1"
if errorlevel 1 (
    echo.
    echo  X  The funnel did not start. Try re-registering it:
    echo        tailscale funnel --https=443 off
    echo        tailscale funnel --bg 8848
    echo.
    pause
    exit /b 1
)
echo.

REM --- 3/4  Engine + Workbench ------------------------------------------------
REM  Its own window, so closing this one does not kill the engine, and the
REM  engine's log stays readable instead of scrolling past the health check.
echo  [3/4] Starting the engine and Workbench...
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
    echo.
    pause
    exit /b 1
)
timeout /t 1 /nobreak >nul
goto waitloop
:engineup
echo        ok - engine listening
echo.

REM --- 4/4  Prove ChatGPT can actually reach it -------------------------------
REM  This is the only step that tests the REAL path. `tailscale funnel status`
REM  reads local config and will say "Funnel on" while the public ingress has
REM  no route here, and probing the *.ts.net name from this machine is answered
REM  inside the tailnet, so both of those look healthy when nothing works.
echo  [4/4] Checking the public path ChatGPT uses...
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\check-funnel.ps1"
if errorlevel 1 (
    echo.
    echo  X  Not reachable from the internet. The check above says which cause.
    echo.
    pause
    exit /b 1
)

echo.
echo  ================================================
echo   READY
echo.
echo   Workbench :  http://127.0.0.1:8849
echo   ChatGPT   :  paste the URL printed in step 2
echo  ================================================
echo.
start "" http://127.0.0.1:8849
echo  This window can be closed. The engine keeps running in its own window.
echo.
pause
