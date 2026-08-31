# Can ChatGPT actually reach the harness through the ngrok door?
#
# `ngrok` printing "online" only means the agent reached ngrok's edge. It says
# nothing about whether the harness accepts what arrives, and the two most
# likely failures here BOTH look like "online" at the ngrok end:
#
#   403  the engine is running with an older config and does not trust the
#        ngrok hostname yet (it was started before HARNESS_PUBLIC_HOST was set)
#   HTML the free-tier browser interstitial answered instead of the harness
#
# This sends a real MCP `initialize` down the real public path and names which
# one happened.

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$publicHost = (python -c "from harness.config import Config; print(Config.from_env().public_host)").Trim()
if (-not $publicHost) {
    Write-Host "HARNESS_PUBLIC_HOST is not set - nothing to check." -ForegroundColor Yellow
    Write-Host "See scripts\ngrok.ps1 for the one-time setup."
    exit 1
}

$state = Join-Path $env:USERPROFILE ".chatgpt-code-harness"
$route = (Get-Content (Join-Path $state "secret_route.txt") -Raw).Trim()

Write-Host "engine :8848 listening : " -NoNewline
$engineUp = [bool](Get-NetTCPConnection -State Listen -LocalPort 8848 -ErrorAction SilentlyContinue)
Write-Host $engineUp
if (-not $engineUp) {
    Write-Host "`nThe engine is not running. Start it first:" -ForegroundColor Yellow
    Write-Host '  python -m harness up'
    exit 1
}

$py = @"
import json, urllib.error, urllib.request
import socket

# Force IPv4. Tunnel edges publish AAAA records, getaddrinfo returns them
# first, and Python tries addresses IN ORDER with no Happy Eyeballs fallback --
# so on a network where IPv6 to the edge is broken, this check burns the full
# timeout on every v6 address before reaching a working v4 one. Measured on one
# such network: 2m03s before this pin, 3.6s after, same verdict both times.
#
# It does not weaken the check. ChatGPT reaches the tunnel from OpenAI's
# servers, never across this machine's Wi-Fi, so the operator's local IPv6 is
# not on the path being tested.
_getaddrinfo = socket.getaddrinfo
def _v4_only(host, port, family=0, type=0, proto=0, flags=0):
    return _getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = _v4_only
host, route = "$publicHost", "$route"
url = f"https://{host}/{route}/mcp"
body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                              "clientInfo": {"name": "check", "version": "1"}}}).encode()
req = urllib.request.Request(url, data=body, headers={
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    # ngrok's free-tier interstitial is aimed at browsers and is skipped when
    # this header is present. ChatGPT's MCP client does NOT send it, so we
    # deliberately do not send it either -- the point of this check is to see
    # what ChatGPT sees, not to paper over it.
})
try:
    with urllib.request.urlopen(req, timeout=25) as r:
        status, ctype, payload = r.status, r.headers.get("Content-Type", ""), r.read(600)
except urllib.error.HTTPError as e:
    status, ctype, payload = e.code, e.headers.get("Content-Type", ""), e.read(600)
except Exception as exc:
    print(f"  could not connect: {type(exc).__name__}: {exc}")
    raise SystemExit(3)

text = payload.decode("utf-8", "replace")
print(f"  HTTP {status}  {ctype}")
if status == 200 and "html" not in ctype.lower():
    print("  " + text[:200].replace("\n", " "))
    raise SystemExit(0)
if "html" in ctype.lower() or "<!DOCTYPE" in text[:200]:
    raise SystemExit(4)   # interstitial
if status == 403:
    raise SystemExit(5)   # harness rejected the Host
if status == 404:
    raise SystemExit(6)   # wrong secret route
print("  " + text[:200].replace("\n", " "))
raise SystemExit(7)
"@

Write-Host "ngrok public path      :"
# `python`, not a hardcoded C:\Python313\python.exe: that path breaks on
# the next Python upgrade and on every other machine, and the failure looks
# like a dead tunnel rather than a missing interpreter.
$py | & python -
$code = $LASTEXITCODE

switch ($code) {
    0 {
        Write-Host "`nReachable. ChatGPT can connect through ngrok." -ForegroundColor Green
        Write-Host "Connector URL:  https://$publicHost/<secret>/mcp   (see: python -m harness url)"
    }
    3 {
        Write-Host "`nThe tunnel is not answering at all." -ForegroundColor Yellow
        Write-Host "  Start it:  .\scripts\ngrok.ps1"
        Write-Host "  If it IS running, the reserved domain may not match HARNESS_PUBLIC_HOST."
    }
    4 {
        Write-Host "`nngrok answered with its BROWSER WARNING page, not the harness." -ForegroundColor Yellow
        Write-Host "  The free tier shows an interstitial to clients it thinks are browsers."
        Write-Host "  ChatGPT cannot click through it, so the connector will look broken."
        Write-Host "  Fixes, cheapest first:"
        Write-Host "    1. Add a Traffic Policy rule on the domain that sets the"
        Write-Host "       ngrok-skip-browser-warning request header."
        Write-Host "    2. Upgrade the ngrok plan (the interstitial is free-tier only)."
        Write-Host "    3. Use the Tailscale Funnel door instead - it has no interstitial."
    }
    5 {
        Write-Host "`nThe harness REJECTED the ngrok hostname (403 host not allowed)." -ForegroundColor Yellow
        Write-Host "  This is the common one. The engine is running with config from"
        Write-Host "  before HARNESS_PUBLIC_HOST was set. Config is read at startup only."
        Write-Host "  Fix:  stop-harness.bat  then  start-harness.bat"
        Write-Host "  Verify with:  python -m harness doctor    (look for 'second public door')"
    }
    6 {
        Write-Host "`n404 - the tunnel works but the secret route is wrong." -ForegroundColor Yellow
        Write-Host "  Get the current URL:  python -m harness url"
        Write-Host "  If the route was rotated, the ChatGPT connector needs rebuilding."
    }
    default {
        Write-Host "`nUnexpected response - see above." -ForegroundColor Yellow
    }
}
if ($code -eq 0) { exit 0 } else { exit 1 }
