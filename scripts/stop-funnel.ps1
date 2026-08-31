# Close the Tailscale Funnel (revokes the public URL).
# Usage:  .\scripts\stop-funnel.ps1 [-Port 8848]
#
# WHY THIS IS NOT `tailscale funnel <port> off` ANY MORE:
#
#   That spelling was removed from the Tailscale CLI. It now fails with
#   "Error: the CLI for serve and funnel has changed" and a non-zero exit --
#   and the previous version of this script printed "Done. The public URL is
#   no longer reachable." immediately afterwards regardless. So the funnel
#   stayed OPEN while the script reported success.
#
#   That is the worst kind of bug in a stop script: it hands you a false
#   belief about the state of a PUBLIC entrance to your machine. It also fed
#   a wrong answer to engine-stop-if-idle.ps1, which then correctly saw a
#   still-open door and left the engine running -- a correct decision from a
#   lie, which is the hardest kind of fault to trace.
#
#   `tailscale funnel reset` is the current spelling. It clears the funnel
#   config; `scripts/funnel.ps1` recreates exactly the same one with
#   `tailscale funnel --bg <port>`, and the hostname is a property of the
#   tailnet, so the public URL is identical afterwards. Nothing is lost.
#
# And it VERIFIES. A stop script that cannot prove it stopped anything is
# just a hopeful message.
param([int]$Port = 8848)
$ErrorActionPreference = "Continue"

Write-Host "Closing the Tailscale Funnel (port $Port) ..."
tailscale funnel reset 2>&1 | ForEach-Object { Write-Host "  $_" }

Start-Sleep -Milliseconds 500
$stillOn = ((tailscale funnel status 2>&1 | Out-String) -match "Funnel on")

if ($stillOn) {
    Write-Host ""
    Write-Host "X  The funnel is STILL ON. It was not closed." -ForegroundColor Yellow
    Write-Host "   Check by hand:  tailscale funnel status"
    Write-Host "   Then try:       tailscale funnel reset"
    exit 1
}

Write-Host "Done - verified off. The public URL is no longer reachable."
Write-Host "(It does not change. start-tailscale.bat brings the same URL back.)"
exit 0
