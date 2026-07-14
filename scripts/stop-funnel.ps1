# Stop the Tailscale Funnel for the harness port (revokes the public URL).
# Usage:  .\scripts\stop-funnel.ps1 [-Port 8848]
param([int]$Port = 8848)
$ErrorActionPreference = "Stop"
Write-Host "Turning off Tailscale Funnel for port $Port ..."
tailscale funnel $Port off
Write-Host "Done. The public URL is no longer reachable."
