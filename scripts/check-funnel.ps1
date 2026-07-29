# Is the harness actually reachable FROM THE INTERNET?
#
# `tailscale funnel status` reads local config and will happily say "Funnel on"
# while the ingress has no route to this machine. A localhost or MagicDNS probe
# of the *.ts.net name is answered inside the tailnet, so it always looks
# healthy too. Neither can detect the failure ChatGPT actually hits.
#
# This connects to the PUBLIC Funnel ingress IPs with SNI set to the hostname —
# the same path OpenAI takes. Run it whenever ChatGPT reports a network error.

$ErrorActionPreference = "Stop"
$state = Join-Path $env:USERPROFILE ".chatgpt-code-harness"
$route = (Get-Content (Join-Path $state "secret_route.txt") -Raw).Trim()
$hostName = "desktop-fdce9ak.taila47816.ts.net"

Write-Host "engine :8848 listening : " -NoNewline
$engineUp = [bool](Get-NetTCPConnection -State Listen -LocalPort 8848 -ErrorAction SilentlyContinue)
Write-Host $engineUp
if (-not $engineUp) {
    Write-Host "`nThe engine is not running. Start it first:" -ForegroundColor Yellow
    Write-Host '  python -m harness up'
    exit 1
}

$py = @"
import json, socket, ssl, time, urllib.request
host, route = "$hostName", "$route"
with urllib.request.urlopen(urllib.request.Request(
        f"https://dns.google/resolve?name={host}&type=A",
        headers={"Accept": "application/dns-json"}), timeout=20) as r:
    ips = [a["data"] for a in json.load(r).get("Answer", []) if a.get("type") == 1]
body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                              "clientInfo": {"name": "check", "version": "1"}}})
req = (f"POST /{route}/mcp HTTP/1.1\r\nHost: {host}\r\n"
       "Content-Type: application/json\r\n"
       "Accept: application/json, text/event-stream\r\n"
       f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n") + body
ctx = ssl.create_default_context()


def probe(ip):
    with socket.create_connection((ip, 443), timeout=15) as raw:
        with ctx.wrap_socket(raw, server_hostname=host) as tls:
            tls.sendall(req.encode())
            return tls.recv(4096).decode("utf-8", "replace").splitlines()[0]


# The ingress needs a moment to pick up the route after the funnel is
# registered. Probing once right after `tailscale funnel --bg` reports a
# healthy funnel as dead, which is worse than waiting.
ok, last = 0, {}
for attempt in range(6):
    ok, last = 0, {}
    for ip in ips:
        try:
            last[ip] = probe(ip)
            ok += 1
        except Exception as exc:
            last[ip] = f"not answering yet ({type(exc).__name__})"
    if ok:
        break
    if attempt < 5:
        print(f"  ...ingress not routing yet, retrying ({attempt + 1}/5)")
        time.sleep(10)

for ip, line in last.items():
    print(f"  {ip:16s} {line}")
raise SystemExit(0 if ok else 1)
"@

Write-Host "public funnel ingress  :"
$py | & C:\Python313\python.exe -
if ($LASTEXITCODE -eq 0) {
    Write-Host "`nReachable from the internet. ChatGPT can connect." -ForegroundColor Green
} else {
    Write-Host "`nNOT reachable after a minute of retries. Two known causes:" -ForegroundColor Yellow
    Write-Host '  1. The funnel deregistered. Re-register (the URL does not change):'
    Write-Host '       tailscale funnel --https=443 off; tailscale funnel --bg 8848'
    Write-Host '  2. This network blocks VPN services, so tailscaled cannot log in.'
    Write-Host '     Check with: tailscale status'
    Write-Host '     "You are logged out" / "NoState" means the network is the problem,'
    Write-Host '     not the funnel. Public and guest Wi-Fi block Tailscale by policy.'
    exit 1
}
