@echo off
REM ============================================================================
REM  CLOSE THE NGROK DOOR.  Double-click. That is the whole thing.
REM
REM  Stops the ngrok agent. The engine is stopped ONLY if the Tailscale door is
REM  also closed -- one engine serves both doors, so closing one door must
REM  never knock out the other. The LAST door to close stops the engine.
REM
REM  Tailscale is never touched here.
REM
REM  Your reserved ngrok URL does not change. start-ngrok.bat brings it back.
REM ============================================================================
setlocal
cd /d "%~dp0"
title Harness - stopping ngrok

echo.
echo  ================================================
echo   HARNESS - closing the NGROK door
echo  ================================================
echo.

echo  [1/2] Stopping the ngrok agent...
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\stop-ngrok.ps1"
echo.

echo  [2/2] Engine...
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\engine-stop-if-idle.ps1" -Closing "the ngrok door"

echo.
echo  ================================================
echo   ngrok door is CLOSED
echo.
echo   Your reserved URL never changes -
echo   start-ngrok.bat brings it straight back.
echo  ================================================
echo.
pause
