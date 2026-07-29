@echo off
REM  Double-click to shut the harness down cleanly: close the public tunnel
REM  first, then stop the engine. Tunnel first, so there is never a window
REM  where the public route is live but nothing is listening behind it.
REM
REM  There is no `harness down` subcommand, so the engine is stopped by the
REM  ports it holds -- which is also what clears the [Errno 10048] that a
REM  half-dead engine leaves behind on the next start.
setlocal
cd /d "%~dp0"
title Harness - stopping

echo.
echo  Closing the Tailscale Funnel...
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\stop-funnel.ps1"

echo.
echo  Stopping the engine (:8848) and Workbench (:8849)...
powershell -NoProfile -Command ^
  "$p = Get-NetTCPConnection -State Listen -LocalPort 8848,8849 -ErrorAction SilentlyContinue | Select-Object -Expand OwningProcess -Unique;" ^
  "if (-not $p) { 'nothing was listening'; exit 0 };" ^
  "foreach ($id in $p) { try { Stop-Process -Id $id -Force -ErrorAction Stop; \"  stopped pid $id\" } catch { \"  could not stop pid $id\" } }"

echo.
echo  Stopped. The URL does not change - start-harness.bat brings it all back.
echo.
pause
