# Close the ngrok door. The Tailscale Funnel is untouched.
# Usage:  .\scripts\stop-ngrok.ps1
$ErrorActionPreference = "Stop"

$procs = Get-Process ngrok -ErrorAction SilentlyContinue
if (-not $procs) {
    Write-Host "No ngrok agent is running."
    exit 0
}
Write-Host "Stopping ngrok ($($procs.Count) process(es)) ..."
$procs | Stop-Process -Force
Write-Host "Done. The ngrok URL is no longer reachable; the funnel still is."
