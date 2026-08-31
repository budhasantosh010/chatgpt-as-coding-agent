# Why is nothing working? Run this and it will tell you.
#
# Read-only. It starts nothing, stops nothing and changes nothing, so it is
# always safe to run -- including while ChatGPT is mid-task.
#
# It exists because the failure modes are NOT distinguishable from ChatGPT's
# end. Every one of them shows up there as "can't connect", and the single
# most misleading case is a dead engine: both doors then fail at once, which
# reads like the network broke, when the network is usually fine.
#
#   ONE ENGINE, TWO DOORS. Kill the engine and you get two dead doors and
#   zero clues. So this checks OUTWARD FROM THE ENGINE, never inward from
#   the tunnel -- starting at the tunnel sends you off reconfiguring the
#   one part that was never broken.
#
# The rule that does most of the work here:
#
#   502 from a public URL  =  THE TUNNEL IS FINE. The engine is down.
#                             A 502 is the tunnel saying "I reached your
#                             machine and nothing answered."
#   timeout / no answer    =  the tunnel is down (or the network blocks it).
#   403                    =  everything is up; the harness refused the Host.
#
# Probes run through Python, never Invoke-WebRequest. See the IPv6 note below
# -- PowerShell 5.1 gets this wrong and reports healthy tunnels as dead.
param([switch]$Quiet)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

function Line($s) { if (-not $Quiet) { Write-Host $s } }
function Head($s) { if (-not $Quiet) { Write-Host ""; Write-Host $s -ForegroundColor Cyan } }

Line ""
Line "  ================================================"
Line "   HARNESS - diagnosis"
Line "  ================================================"

# ---------------------------------------------------------------------------
# Config. One source of truth: ask the harness, never keep a second copy here.
# ---------------------------------------------------------------------------
$cfg = python -c "from harness.config import Config; c=Config.from_env(); print(c.port); print(c.public_host)" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "  X  Could not read the harness config." -ForegroundColor Red
    Write-Host "     Is Python on PATH, and is this the repo folder?"
    Write-Host ("     " + ($cfg -join " "))
    exit 2
}
$port       = [int]$cfg[0]
$publicHost = "$($cfg[1])".Trim()

$tsHost = $null
try {
    $tsHost = (tailscale status --json 2>$null | ConvertFrom-Json).Self.DNSName
    if ($tsHost) { $tsHost = $tsHost.TrimEnd(".") }
} catch { $tsHost = $null }

# ---------------------------------------------------------------------------
# 1. The engine. Everything below is meaningless if this is down.
# ---------------------------------------------------------------------------
Head "  [1] ENGINE"
$eng = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
$wb  = Get-NetTCPConnection -State Listen -LocalPort 8849  -ErrorAction SilentlyContinue
$engineUp = [bool]$eng

if ($engineUp) { Line ("      engine    :{0}   UP    (pid {1})" -f $port, $eng[0].OwningProcess) }
else           { Line ("      engine    :{0}   DOWN" -f $port) }
if ($wb) { Line ("      workbench :8849   UP    (pid {0})" -f $wb[0].OwningProcess) }
else     { Line  "      workbench :8849   DOWN" }

# engine.pid records what LAST STARTED and is never cleared on exit, so a
# present pid file proves nothing. Say so out loud -- it has misled before.
$pidFile = Join-Path $env:USERPROFILE ".chatgpt-code-harness\engine.pid"
if (Test-Path $pidFile) {
    $recorded = (Get-Content $pidFile -Raw).Trim()
    if (-not (Get-Process -Id $recorded -ErrorAction SilentlyContinue)) {
        Line ("      engine.pid says {0}, which is NOT running - STALE." -f $recorded)
        Line  "      (engine.pid is not a liveness check; nothing clears it on exit.)"
    }
}

# ---------------------------------------------------------------------------
# 2/3/4. The actual HTTP paths.
# ---------------------------------------------------------------------------
$state = Join-Path $env:USERPROFILE ".chatgpt-code-harness"
$route = (Get-Content (Join-Path $state "secret_route.txt") -Raw).Trim()

$targets = New-Object System.Collections.ArrayList
[void]$targets.Add(@("LOCAL", "http://127.0.0.1:$port/$route/mcp"))
if ($tsHost)     { [void]$targets.Add(@("FUNNEL", "https://$tsHost/$route/mcp")) }
if ($publicHost) { [void]$targets.Add(@("NGROK",  "https://$publicHost/$route/mcp")) }
$targetsJson = ConvertTo-Json -InputObject @($targets) -Compress -Depth 4

# Probed from Python, never Invoke-WebRequest. PowerShell 5.1 prefers IPv6 and
# does not fall back quickly; where IPv6 to a tunnel edge is broken it reports
# a perfectly healthy door as a timeout. Python and curl fall back to IPv4 in
# milliseconds. Same URL, same second, opposite verdicts -- so which client
# does the asking is load-bearing, not cosmetic.
$py = @"
import json, socket, urllib.error, urllib.request

# Force IPv4. ngrok publishes AAAA records, getaddrinfo returns them first, and
# Python tries addresses IN ORDER with no Happy Eyeballs fallback -- so on a
# network where IPv6 to the tunnel edge is broken, every probe burns the full
# timeout on each v6 address before reaching a working v4 one. That turned this
# diagnostic into a two-minute wait for an answer it already had.
#
# This does not weaken the check. ChatGPT reaches the tunnel from OpenAI's
# servers, not across this machine's Wi-Fi, so the operator's local IPv6 is not
# on the path being tested. Pinning v4 makes the probe a closer match to what
# ChatGPT actually experiences, not a looser one.
_getaddrinfo = socket.getaddrinfo
def _v4_only(host, port, family=0, type=0, proto=0, flags=0):
    return _getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = _v4_only

targets = json.loads(r'''$targetsJson''')
body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                              "clientInfo": {"name": "diagnose", "version": "1"}}}).encode()
for name, url in targets:
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        # No ngrok-skip-browser-warning header, deliberately. ChatGPT does not
        # send it either, and a check that papers over the exact failure it is
        # looking for is worse than no check at all.
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            status, ctype, payload = r.status, r.headers.get("Content-Type", ""), r.read(400)
    except urllib.error.HTTPError as e:
        status, ctype, payload = e.code, e.headers.get("Content-Type", ""), e.read(400)
    except Exception as exc:
        print("{0}|0|no|{1}".format(name, type(exc).__name__))
        continue
    text = payload.decode("utf-8", "replace")
    ok = "yes" if (status == 200 and "protocolVersion" in text) else "no"
    kind = "html" if ("html" in ctype.lower() or "<!DOCTYPE" in text[:200]) else ctype
    print("{0}|{1}|{2}|{3}".format(name, status, ok, kind))
"@

$raw = $py | & python -
$res = @{}
foreach ($l in $raw) {
    if ("$l" -match "^(\w+)\|(\d+)\|(yes|no)\|(.*)$") {
        $res[$matches[1]] = @{ status = [int]$matches[2]; ok = ($matches[3] -eq "yes"); kind = $matches[4].Trim() }
    }
}

function Show($label, $key) {
    if (-not $res.ContainsKey($key)) { Line ("      {0}  not checked" -f $label); return }
    $r = $res[$key]
    if ($r.ok)              { $verdict = "handshake OK" }
    elseif ($r.status -eq 0) { $verdict = "no answer ({0})" -f $r.kind }
    else                     { $verdict = $r.kind }
    Line ("      {0}  HTTP {1,-3}  {2}" -f $label, $r.status, $verdict)
}

Head "  [2] LOCAL path (does the engine itself answer?)"
Show "local " "LOCAL"

Head "  [3] TAILSCALE door"
$funnelOn = ((tailscale funnel status 2>&1 | Out-String) -match "Funnel on")
if ($funnelOn) { Line "      funnel config    on" } else { Line "      funnel config    OFF" }
Line  "      (that line is INTENT, not proof. Only the probe below is evidence.)"
Show "public" "FUNNEL"

Head "  [4] NGROK door (the second door)"
if (-not $publicHost) {
    Line "      HARNESS_PUBLIC_HOST is not set - no second door configured."
} else {
    $ngProc = Get-Process ngrok -ErrorAction SilentlyContinue
    if ($ngProc) { Line ("      agent            running (pid {0})" -f $ngProc[0].Id) }
    else {
        Line "      agent            NOT RUNNING"
        Line "      ngrok is not a service. It does not survive a reboot, and"
        Line "      start-harness.bat does not start it. Use start-ngrok.bat."
    }
    Show "public" "NGROK"
}

# ---------------------------------------------------------------------------
# The verdict. This is the part worth reading.
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "  ================================================" -ForegroundColor Cyan
Write-Host "   VERDICT" -ForegroundColor Cyan
Write-Host "  ================================================" -ForegroundColor Cyan

$localOk  = $res.ContainsKey("LOCAL")  -and $res["LOCAL"].ok
$funnelOk = $res.ContainsKey("FUNNEL") -and $res["FUNNEL"].ok
$ngrokOk  = $res.ContainsKey("NGROK")  -and $res["NGROK"].ok

# Local dead but a public door alive cannot happen when everything agrees on
# one port -- the tunnels forward to the same engine this probe just failed to
# reach. So it means the config port and the tunnel's target port DISAGREE.
# Worth naming: the "engine is down" message below would be actively wrong
# here, and would send you restarting a healthy engine.
if ((-not $localOk) -and ($funnelOk -or $ngrokOk)) {
    Write-Host ""
    Write-Host "   PORT MISMATCH - not an outage." -ForegroundColor Yellow
    Write-Host ""
    Write-Host ("   The harness config says port {0}, and nothing is answering" -f $port)
    Write-Host "   there - but a public door IS serving a healthy engine. So the"
    Write-Host "   tunnel is forwarding to a different port than the config names."
    Write-Host ""
    Write-Host "   Check:  python -m harness doctor        (the port it reports)"
    Write-Host "           tailscale funnel status         (the port it proxies to)"
    Write-Host "           HARNESS_PORT in .env, if it is set at all"
    Write-Host ""
    exit 1
}

if ((-not $engineUp) -or (-not $localOk)) {
    $five02 = ($res.ContainsKey("FUNNEL") -and $res["FUNNEL"].status -eq 502) -or
              ($res.ContainsKey("NGROK")  -and $res["NGROK"].status  -eq 502)
    Write-Host ""
    Write-Host "   THE ENGINE IS DOWN. This is the whole problem." -ForegroundColor Red
    Write-Host ""
    if ($five02) {
        Write-Host "   Your tunnel returned 502 - which means IT IS FINE."
        Write-Host "   A 502 is the tunnel saying 'I reached your machine and"
        Write-Host "   nothing answered'. Do not touch the tunnel config."
        Write-Host ""
    }
    Write-Host "   One engine sits behind both doors, so a dead engine makes"
    Write-Host "   BOTH doors fail at once. That looks like the network broke -"
    Write-Host "   especially right after changing Wi-Fi. It usually did not."
    Write-Host ""
    Write-Host "   The engine runs in a console window with no supervisor:"
    Write-Host "   closing that window is a full stop, and nothing restarts it."
    Write-Host ""
    Write-Host "   FIX:  start-harness.bat   (Tailscale door)" -ForegroundColor Green
    Write-Host "         start-ngrok.bat     (ngrok door; starts the engine too)" -ForegroundColor Green
    Write-Host ""
    exit 1
}

if (-not ($funnelOk -or $ngrokOk)) {
    Write-Host ""
    Write-Host "   The engine is HEALTHY, but no public door is open." -ForegroundColor Yellow
    Write-Host "   ChatGPT reaches you through a tunnel, so it cannot connect yet."
    Write-Host ""
    if ($res.ContainsKey("FUNNEL") -and $res["FUNNEL"].status -eq 403) {
        Write-Host "   The funnel returned 403 - the harness refused the Host."   -ForegroundColor Yellow
        Write-Host "   Restart the engine; config is read at startup only."
    }
    if ($res.ContainsKey("NGROK") -and $res["NGROK"].status -eq 403) {
        Write-Host "   ngrok returned 403 - the engine was started BEFORE"        -ForegroundColor Yellow
        Write-Host "   HARNESS_PUBLIC_HOST was set. stop-harness.bat, then start again."
    }
    if ($res.ContainsKey("NGROK") -and $res["NGROK"].kind -eq "html") {
        Write-Host "   ngrok served its free-tier BROWSER WARNING page, not the"  -ForegroundColor Yellow
        Write-Host "   harness. ChatGPT cannot click through it. Use the funnel,"
        Write-Host "   or set ngrok-skip-browser-warning via a Traffic Policy rule."
    }
    Write-Host ""
    Write-Host "   FIX:  start-harness.bat  and/or  start-ngrok.bat" -ForegroundColor Green
    Write-Host ""
    exit 1
}

Write-Host ""
if     ($funnelOk) { Write-Host "   Tailscale door : WORKING" -ForegroundColor Green }
elseif ($tsHost)   { Write-Host "   Tailscale door : down"    -ForegroundColor Yellow }
if     ($ngrokOk)  { Write-Host "   ngrok door     : WORKING" -ForegroundColor Green }
elseif ($publicHost) { Write-Host "   ngrok door     : down"  -ForegroundColor Yellow }

Write-Host ""
Write-Host "   ChatGPT can connect. Paste the matching URL as its connector:"
Write-Host ""
python -m harness url

if ($publicHost -and (-not $ngrokOk) -and (Get-Process ngrok -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Host "   NOTE: the ngrok agent IS running but the probe failed. Check"      -ForegroundColor DarkGray
    Write-Host "   ngrok's own counter at http://127.0.0.1:4040/api/tunnels - if it"  -ForegroundColor DarkGray
    Write-Host "   does not increment, your request never reached ngrok at all and"   -ForegroundColor DarkGray
    Write-Host "   the tunnel is not at fault. Broken local IPv6 does exactly this."  -ForegroundColor DarkGray
    Write-Host "   It does NOT affect ChatGPT, whose traffic runs OpenAI -> ngrok"    -ForegroundColor DarkGray
    Write-Host "   edge and never crosses your Wi-Fi."                                -ForegroundColor DarkGray
}
Write-Host ""
exit 0
