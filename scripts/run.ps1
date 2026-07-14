# Start the harness MCP server. Reads .env in the repo root automatically.
# Usage:  .\scripts\run.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
python -m harness serve
