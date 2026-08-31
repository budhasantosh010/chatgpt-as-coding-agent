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

# The single most important line on the screen, and it must be the LAST one.
#
# The first version buried the answer under four sections of DOWN / HTTP 0 / 404
# and then ended on a wall of URLs. A real operator read that output, saw a
# correct diagnosis, and still could not tell whether the harness was working --
# because a screen full of red-looking detail reads as "the tool broke" and the
# terminal leaves you looking at whatever printed last.
#
# So: one unmissable box, plain words, one action, printed last on every single
# exit path. A diagnostic that is right but unreadable has not done its job.
function Banner($working, $headline, $action) {
    $colour = if ($working) { "Green" } else { "Red" }
    Write-Host ""
    Write-Host "  ##################################################" -ForegroundColor $colour
    Write-Host "  ##" -ForegroundColor $colour
    Write-Host ("  ##   " + $headline) -ForegroundColor $colour
    Write-Host "  ##" -ForegroundColor $colour
    if ($action) {
        Write-Host ("  ##   " + $action) -ForegroundColor $colour
        Write-Host "  ##" -ForegroundColor $colour
    }
    Write-Host "  ##################################################" -ForegroundColor $colour
    Write-Host ""
}

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
    Banner $false "COULD NOT CHECK - this is not a harness fault." "Run this from the repo folder, with Python on PATH."
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
import json, re, socket, urllib.error, urllib.request

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
        # Five fields, like every other line. A four-field line silently fails
        # the reader's regex and the door then reports "not checked" -- which
        # reads as "we skipped it" rather than "it refused the connection".
        print("{0}|0|no|{1}|-".format(name, type(exc).__name__))
        continue
    text = payload.decode("utf-8", "replace")
    ok = "yes" if (status == 200 and "protocolVersion" in text) else "no"
    kind = "html" if ("html" in ctype.lower() or "<!DOCTYPE" in text[:200]) else ctype
    # WHICH ngrok error, not merely "some ngrok error". The distinction decides
    # the advice, and getting it wrong sends the operator to the wrong machine:
    #
    #   ERR_NGROK_3200  the endpoint is offline -- no agent is serving this
    #                   domain. Start ngrok. The route and connector are fine.
    #   ERR_NGROK_8012  the agent IS serving, but could not reach the upstream.
    #                   The tunnel is fine; the ENGINE is down.
    #
    # Both arrive as plain 404/502 status codes that also have perfectly ordinary
    # harness meanings (wrong secret route / dead backend), so the status code
    # alone cannot tell you who answered.
    m = re.search(r"ERR_NGROK_\d+", text)
    edge = m.group(0) if m else "-"
    print("{0}|{1}|{2}|{3}|{4}".format(name, status, ok, kind, edge))
"@

$raw = $py | & python -
$res = @{}
foreach ($l in $raw) {
    if ("$l" -match "^(\w+)\|(\d+)\|(yes|no)\|(.*)\|(ERR_NGROK_\d+|-)$") {
        $res[$matches[1]] = @{ status = [int]$matches[2]; ok = ($matches[3] -eq "yes")
                               kind   = $matches[4].Trim(); edge = $matches[5] }
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
        Line "      start-tailscale.bat does not start it. Use start-ngrok.bat."
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
    Banner $false "PORT MISMATCH - config and tunnel disagree." "Make them name the same port, then run this again."
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
    Write-Host "   FIX:  start-tailscale.bat   (Tailscale door)" -ForegroundColor Green
    Write-Host "         start-ngrok.bat     (ngrok door; starts the engine too)" -ForegroundColor Green
    Banner $false "NOT WORKING - ChatGPT cannot connect right now." "DO THIS:  double-click start-ngrok.bat"
    exit 1
}


# ---------------------------------------------------------------------------
# Per-door reasons.
#
# These are worked out BEFORE the summary and printed whichever door failed,
# not only when both are down. Getting that wrong is easy and costly: the most
# common ngrok fault by far is a 403 from an engine started before
# HARNESS_PUBLIC_HOST was set, and if the funnel happens to be healthy at the
# same time, hiding the explanation leaves "ngrok door: down" with no cause and
# no fix -- the exact dead end this whole file exists to remove.
# ---------------------------------------------------------------------------
function Door-Reason($key, $label, $isConfigured) {
    if (-not $isConfigured) { return $null }
    if (-not $res.ContainsKey($key)) { return $null }
    $r = $res[$key]
    if ($r.ok) { return $null }

    $msg = New-Object System.Collections.ArrayList

    # ngrok's OWN edge answered, not the harness. Checked first, and by ERROR
    # CODE rather than status, because both of these arrive as ordinary status
    # codes that the harness itself also produces for unrelated reasons.
    if ($r.edge -eq "ERR_NGROK_3200") {
        [void]$msg.Add("$label was answered by ngrok's edge, NOT by the harness.")
        [void]$msg.Add("  ERR_NGROK_3200 - the endpoint is offline. The domain is")
        [void]$msg.Add("  reserved to you, but no agent is serving it right now.")
        [void]$msg.Add("  Your secret route and your ChatGPT connector are FINE -")
        [void]$msg.Add("  this 404 is ngrok's, not the harness's.")
        [void]$msg.Add("  Fix:  start-ngrok.bat")
        [void]$msg.Add("  (ngrok is not a service - it does not survive a reboot.)")
        return $msg
    }
    if ($r.edge -eq "ERR_NGROK_8012") {
        [void]$msg.Add("$label reached the ngrok agent, which could NOT reach the engine.")
        [void]$msg.Add("  ERR_NGROK_8012 - the tunnel is fine; nothing is listening")
        [void]$msg.Add("  behind it, or it is listening on a different port.")
        [void]$msg.Add("  Do not touch the tunnel. Check the engine.")
        return $msg
    }
    if ($r.edge -ne "-") {
        [void]$msg.Add("$label was answered by ngrok's edge: {0}." -f $r.edge)
        [void]$msg.Add("  That is ngrok reporting, not the harness. Look the code up at")
        [void]$msg.Add("  https://ngrok.com/docs/errors/ - the harness is not implicated.")
        return $msg
    }

    if ($r.status -eq 403) {
        [void]$msg.Add("$label returned 403 - the harness REFUSED the hostname.")
        if ($key -eq "NGROK") {
            [void]$msg.Add("  The engine was started BEFORE HARNESS_PUBLIC_HOST was set.")
            [void]$msg.Add("  Config is read at startup only, so it never picked it up.")
            [void]$msg.Add("  Fix:  stop-ngrok.bat AND stop-tailscale.bat, then start the door you want")
            [void]$msg.Add("  Check: python -m harness doctor  ->  'second public door'")
        } else {
            [void]$msg.Add("  Restart the engine; config is read at startup only.")
        }
    }
    elseif ($r.kind -eq "html") {
        [void]$msg.Add("$label served ngrok's free-tier BROWSER WARNING page, not the harness.")
        [void]$msg.Add("  ChatGPT cannot click through it, so the connector looks broken.")
        [void]$msg.Add("  Fixes: a Traffic Policy rule setting ngrok-skip-browser-warning,")
        [void]$msg.Add("  a paid plan, or just use the Tailscale door - it has no interstitial.")
    }
    elseif ($r.status -eq 404) {
        [void]$msg.Add("$label returned 404 - tunnel fine, but the secret route is wrong.")
        [void]$msg.Add("  Get the current URL:  python -m harness url")
        [void]$msg.Add("  If the route was rotated, the ChatGPT connector needs rebuilding.")
    }
    elseif ($r.status -eq 502) {
        [void]$msg.Add("$label returned 502 - the tunnel is FINE, nothing answered behind it.")
        [void]$msg.Add("  Check the engine before touching any tunnel config.")
    }
    elseif ($r.status -eq 0) {
        [void]$msg.Add("$label did not answer at all ({0})." -f $r.kind)
        if ($key -eq "NGROK") {
            if (Get-Process ngrok -ErrorAction SilentlyContinue) {
                [void]$msg.Add("  The agent IS running, so check ngrok's own counter at")
                [void]$msg.Add("  http://127.0.0.1:4040/api/tunnels - if it does not increment,")
                [void]$msg.Add("  your request never reached ngrok and the tunnel is not at fault.")
                [void]$msg.Add("  Broken local IPv6 does exactly this, and does NOT affect ChatGPT,")
                [void]$msg.Add("  whose traffic runs OpenAI -> ngrok edge, never across your Wi-Fi.")
            } else {
                [void]$msg.Add("  The agent is not running. Start it:  start-ngrok.bat")
            }
        } else {
            [void]$msg.Add("  The tunnel is down, or this network blocks it.")
            [void]$msg.Add("  If Tailscale is blocked here, use the second door: start-ngrok.bat")
        }
    }
    else {
        [void]$msg.Add("$label returned HTTP {0} - unexpected. See section [3]/[4] above." -f $r.status)
    }
    return $msg
}

$funnelReason = Door-Reason "FUNNEL" "The Tailscale door" ([bool]$tsHost)
$ngrokReason  = Door-Reason "NGROK"  "The ngrok door"     ([bool]$publicHost)

function Emit($reason, $colour) {
    if (-not $reason) { return }
    Write-Host ""
    foreach ($l in $reason) { Write-Host ("   " + $l) -ForegroundColor $colour }
}

if (-not ($funnelOk -or $ngrokOk)) {
    Write-Host ""
    Write-Host "   The engine is HEALTHY, but NO public door is open." -ForegroundColor Yellow
    Write-Host "   ChatGPT reaches you through a tunnel, so it cannot connect yet."
    Emit $funnelReason "Yellow"
    Emit $ngrokReason  "Yellow"
    Write-Host ""
    Write-Host "   FIX:  start-tailscale.bat  and/or  start-ngrok.bat" -ForegroundColor Green
    Banner $false "NOT WORKING - ChatGPT cannot connect right now." "DO THIS:  double-click start-ngrok.bat"
    exit 1
}

Write-Host ""
if     ($funnelOk) { Write-Host "   Tailscale door : WORKING" -ForegroundColor Green }
elseif ($tsHost)   { Write-Host "   Tailscale door : down"    -ForegroundColor Yellow }
if     ($ngrokOk)  { Write-Host "   ngrok door     : WORKING" -ForegroundColor Green }
elseif ($publicHost) { Write-Host "   ngrok door     : down"  -ForegroundColor Yellow }

# One door being healthy does not make the other door's fault invisible.
Emit $funnelReason "DarkYellow"
Emit $ngrokReason  "DarkYellow"

Write-Host ""
Write-Host "   ChatGPT can connect through the door(s) marked WORKING."
Write-Host "   Paste the matching URL as its connector:"
Write-Host ""
python -m harness url

$doors = @()
if ($funnelOk) { $doors += "Tailscale" }
if ($ngrokOk)  { $doors += "ngrok" }
Banner $true ("WORKING - ChatGPT can connect (" + ($doors -join " + ") + ").") "Nothing to do. Use ChatGPT as normal."
exit 0
