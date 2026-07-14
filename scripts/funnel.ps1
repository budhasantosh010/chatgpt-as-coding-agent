# Expose the local harness server to ChatGPT over the public internet via
# Tailscale Funnel, then print the exact MCP URL to paste into the connector.
#
# Usage:  .\scripts\funnel.ps1 [-Port 8848]
#
# One-time prerequisites (only needed once per machine/tailnet):
#   - Tailscale installed and logged in (tailscale up)
#   - Funnel enabled for your tailnet in the admin console (HTTPS + Funnel node attr)
param([int]$Port = 8848)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

Write-Host "Starting Tailscale Funnel for local port $Port ..."
tailscale funnel --bg $Port
Write-Host ""
tailscale funnel status
Write-Host ""
Write-Host "Paste this MCP URL into the ChatGPT connector:"
python -m harness url
