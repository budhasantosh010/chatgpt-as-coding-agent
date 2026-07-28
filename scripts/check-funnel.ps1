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
import json, socket, ssl, urllib.request
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
ctx, ok = ssl.create_default_context(), 0
for ip in ips:
    try:
        with socket.create_connection((ip, 443), timeout=15) as raw:
            with ctx.wrap_socket(raw, server_hostname=host) as tls:
                tls.sendall(req.encode())
                line = tls.recv(4096).decode("utf-8", "replace").splitlines()[0]
        print(f"  {ip:16s} {line}")
        ok += 1
    except Exception as exc:
        print(f"  {ip:16s} FAILED: {type(exc).__name__}")
raise SystemExit(0 if ok else 1)
"@

Write-Host "public funnel ingress  :"
$py | & C:\Python313\python.exe -
if ($LASTEXITCODE -eq 0) {
    Write-Host "`nReachable from the internet. ChatGPT can connect." -ForegroundColor Green
} else {
    Write-Host "`nNOT reachable. The funnel deregistered. Fix (URL does not change):" -ForegroundColor Yellow
    Write-Host '  tailscale funnel --https=443 off; tailscale funnel --bg 8848'
    exit 1
}
