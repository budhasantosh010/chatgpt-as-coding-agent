@echo off
REM ============================================================================
REM  CLOSE THE TAILSCALE DOOR.  Double-click. That is the whole thing.
REM
REM  Closes the Tailscale Funnel. The engine is stopped ONLY if the ngrok door
REM  is also closed -- one engine serves both doors, so closing one door must
REM  never knock out the other. The LAST door to close stops the engine.
REM
REM  Tunnel down BEFORE the engine, so there is never a moment where the public
REM  route is live with nothing listening behind it (that answers 502, which
REM  reads like a broken tunnel and sends you debugging the wrong thing).
REM
REM  Your URL does not change. start-tailscale.bat brings it all back.
REM ============================================================================
setlocal
cd /d "%~dp0"
title Harness - stopping Tailscale

echo.
echo  ================================================
echo   HARNESS - closing the TAILSCALE door
echo  ================================================
echo.

echo  [1/2] Closing the Tailscale Funnel...
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\stop-funnel.ps1"
echo.

echo  [2/2] Engine...
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\engine-stop-if-idle.ps1" -Closing "the Tailscale door"

echo.
echo  ================================================
echo   Tailscale door is CLOSED
echo.
echo   The URL never changes - start-tailscale.bat
echo   brings it straight back.
echo  ================================================
echo.
pause
