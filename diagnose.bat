@echo off
REM ============================================================================
REM  Double-click this when ChatGPT says it cannot connect and you do not know
REM  why. It tells you WHICH part is broken and what to do about it.
REM
REM  Safe to run at any time: it starts nothing, stops nothing, changes nothing.
REM  You can run it while ChatGPT is mid-task.
REM
REM  Why this file exists at all:
REM
REM    Every failure looks identical from ChatGPT's side -- "can't connect".
REM    The worst case is a dead engine, because both doors then fail at once
REM    and that reads like the network broke. It usually did not. One engine
REM    sits behind both doors; empty the room and every door looks broken.
REM
REM    So this checks OUTWARD FROM THE ENGINE. Starting at the tunnel sends
REM    you off reconfiguring the one part that was never at fault.
REM ============================================================================
setlocal
cd /d "%~dp0"
title Harness - diagnosis

powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\diagnose.ps1"

echo.
pause
