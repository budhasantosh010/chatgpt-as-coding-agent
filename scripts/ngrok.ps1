# Open the SECOND public door to the harness, using ngrok instead of the
# Tailscale Funnel. Use it on networks that block Tailscale.
#
# Usage:  .\scripts\ngrok.ps1 [-Port 8848]
#
# This does not replace the funnel and does not touch it. Both tunnels can be
# open at once: they are two roads to the same localhost:8848, so the same
# tasks, workspaces, evidence and files are behind either one.
#
# KNOWN BLOCKER on this machine (2026-08-25) -- read before debugging:
#
#   ngrok 3.3.1  (winget; validly signed by "ngrok, Inc." via DigiCert)
#       -> REJECTED BY NGROK: ERR_NGROK_121, "agent version 3.3.1 is too old,
#          the minimum supported agent version for your account is 3.20.0".
#          Paid accounts are exempt from that minimum; free ones are not.
#
#   ngrok 3.20+  (ngrok update, or the official bin.equinox.io zip)
#       -> QUARANTINED BY WINDOWS DEFENDER as Trojan:Win32/Kepavll!rfn,
#          severity 5, with current definitions (1.457.327.0). The zip
#          downloads but will not extract; an in-place `ngrok update` leaves
#          the PATH shim pointing at a file Windows refuses to open, so even
#          `ngrok version` fails.
#
# No version satisfies both. It cannot be fixed from inside this repo. The
# detection is probably heuristic -- Defender routinely flags tunnelling tools,
# and !rfn is an ML/reputation hit rather than a signature match -- but that
# stays UNVERIFIED, because Defender blocks reading the binary to check whether
# it is properly signed. Do not treat "probably a false positive" as a finding.
#
# Resolving it is an operator decision, not a code change: a Defender exclusion,
# a paid ngrok plan (3.3.1 then works), a different tunnel, or the funnel.
#
# One-time prerequisites:
#   - ngrok installed            (winget install --id Ngrok.Ngrok --exact)
#   - ngrok authtoken configured (ngrok config add-authtoken <token>)
#   - a RESERVED domain claimed in the ngrok dashboard, and that hostname set
#     as HARNESS_PUBLIC_HOST in .env
#
# The reserved domain is the whole point. Without it ngrok hands out a new
# random hostname on every start, and because a ChatGPT connector is bound to
# one URL and caches its tool menu per URL, a new hostname means building a new
# connector every single day.
param([int]$Port = 8848)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

# One source of truth: ask the harness what hostname it will accept, rather
# than keeping a second copy of it in this script that can drift.
$publicHost = (python -c "from harness.config import Config; print(Config.from_env().public_host)").Trim()
if (-not $publicHost) {
    Write-Host "X  HARNESS_PUBLIC_HOST is not set." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "   Claim a domain at dashboard.ngrok.com -> Domains, then put it in .env:"
    Write-Host "     HARNESS_PUBLIC_HOST=your-name.ngrok-free.dev"
    Write-Host ""
    Write-Host "   Restart the engine afterwards, or it will 403 the tunnel."
    exit 1
}

if (-not (Get-Command ngrok -ErrorAction SilentlyContinue)) {
    Write-Host "X  ngrok is not installed (or not on PATH)." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "   Install it:      winget install --id Ngrok.Ngrok --exact"
    Write-Host "   Then sign in:    ngrok config add-authtoken <token from dashboard>"
    Write-Host ""
    Write-Host "   Open a NEW terminal after installing so PATH refreshes."
    exit 1
}

# Already running against the right domain? Then this is a no-op, not an error.
# ngrok's local agent API is the only honest source for what is actually up —
# unlike `tailscale funnel status`, it reports the live tunnel, not intent.
function Get-NgrokTunnels {
    try {
        return (Invoke-RestMethod -Uri "http://127.0.0.1:4040/api/tunnels" -TimeoutSec 3).tunnels
    } catch {
        return $null
    }
}

$existing = Get-NgrokTunnels
if ($existing | Where-Object { $_.public_url -eq "https://$publicHost" }) {
    Write-Host "ngrok is already serving https://$publicHost - leaving it alone."
    Write-Host ""
    python -m harness url
    exit 0
}
if ($existing) {
    Write-Host "X  An ngrok agent is already running, but on a different URL:" -ForegroundColor Yellow
    $existing | ForEach-Object { Write-Host "     $($_.public_url) -> $($_.config.addr)" }
    Write-Host ""
    Write-Host "   Free ngrok accounts allow one agent at a time. Stop it first:"
    Write-Host "     .\scripts\stop-ngrok.ps1"
    exit 1
}

# ngrok v3 renamed --domain to --url and now wants the full https:// form.
# Older builds only understand --domain. Ask the binary rather than guessing,
# because guessing wrong fails with an argument error that reads like a network
# fault.
$supportsUrl = (ngrok http --help 2>&1 | Out-String) -match "--url"
$ngrokArgs = if ($supportsUrl) {
    @("http", "--url=https://$publicHost", "$Port")
} else {
    @("http", "--domain=$publicHost", "$Port")
}

Write-Host "Starting ngrok -> https://$publicHost -> 127.0.0.1:$Port ..."
Start-Process ngrok -ArgumentList $ngrokArgs -WindowStyle Minimized

# Poll the agent API instead of sleeping a fixed amount: the tunnel is usually
# up in about a second, but a cold start on poor wifi can take ten.
$up = $false
foreach ($attempt in 1..20) {
    Start-Sleep -Milliseconds 750
    $tunnels = Get-NgrokTunnels
    if ($tunnels | Where-Object { $_.public_url -eq "https://$publicHost" }) { $up = $true; break }
}

if (-not $up) {
    Write-Host ""
    Write-Host "X  ngrok did not come up on https://$publicHost." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "   Look at the minimised ngrok window for the real error. Common ones:"
    Write-Host "     ERR_NGROK_4018  no authtoken   -> ngrok config add-authtoken <token>"
    Write-Host "     ERR_NGROK_313   domain not yours / typo in HARNESS_PUBLIC_HOST"
    Write-Host "     ERR_NGROK_108   another agent is already running"
    exit 1
}

Write-Host "        ok - tunnel is live"
Write-Host ""
python -m harness url
