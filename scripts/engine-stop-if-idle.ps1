# Stop the engine ONLY if no door still needs it.
#
# There is one engine and two doors. Closing one door must never take the
# engine down while the other door is still open -- that would silently break
# a connection the operator never asked to touch, and it would present as the
# worst failure mode this project has: both doors dead, looking like a network
# fault, when in fact a stop script was too eager.
#
# So: the engine is stopped by the LAST door to close, and by nobody else.
#
# There is no `harness down` subcommand, which is why this stops by port. That
# is also what clears the [Errno 10048] a half-dead engine leaves behind.
param([string]$Closing = "a door")
$ErrorActionPreference = "Stop"

$ngrokUp  = [bool](Get-Process ngrok -ErrorAction SilentlyContinue)
$funnelUp = ((tailscale funnel status 2>&1 | Out-String) -match "Funnel on")

if ($ngrokUp -or $funnelUp) {
    $who = if ($ngrokUp -and $funnelUp) { "the ngrok door and the Tailscale door are" }
           elseif ($ngrokUp)            { "the ngrok door is" }
           else                         { "the Tailscale door is" }
    Write-Host ""
    Write-Host "  Leaving the engine RUNNING - $who still open."
    Write-Host "  Close that one too and the engine stops with it."
    exit 0
}

$p = Get-NetTCPConnection -State Listen -LocalPort 8848,8849 -ErrorAction SilentlyContinue |
     Select-Object -Expand OwningProcess -Unique
if (-not $p) {
    Write-Host ""
    Write-Host "  Engine was not running."
    exit 0
}

Write-Host ""
Write-Host "  That was the last door - stopping the engine too."
foreach ($id in $p) {
    try { Stop-Process -Id $id -Force -ErrorAction Stop; Write-Host "    stopped pid $id" }
    catch { Write-Host "    could not stop pid $id" }
}
exit 0
