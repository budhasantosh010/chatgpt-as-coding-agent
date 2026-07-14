"""CLI entrypoint: ``python -m harness [serve|doctor|url]``."""

from __future__ import annotations

import argparse
import shutil
import sys

from .config import Config


def _cmd_serve(config: Config) -> int:
    import uvicorn

    from .app import build_asgi_app

    app, _server = build_asgi_app(config)
    print(f"chatgpt-code-harness serving on http://{config.host}:{config.port}")
    print(f"MCP endpoint (local): http://{config.host}:{config.port}{config.mcp_path}")
    print(f"mode: {config.mode} | workspace roots: {[str(r) for r in config.workspace_roots]}")
    print("Expose to ChatGPT with: tailscale funnel " + str(config.port))
    # access_log disabled so the secret route path never lands in logs.
    uvicorn.run(app, host=config.host, port=config.port, access_log=False, log_level="info")
    return 0


def _tailnet_dnsname() -> str | None:
    import json
    import subprocess

    if shutil.which("tailscale") is None:
        return None
    try:
        out = subprocess.run(
            ["tailscale", "status", "--json"], capture_output=True, text=True, timeout=10
        )
        if out.returncode != 0:
            return None
        data = json.loads(out.stdout)
        name = (data.get("Self", {}) or {}).get("DNSName", "").rstrip(".")
        return name or None
    except (OSError, ValueError):
        return None


def _cmd_url(config: Config) -> int:
    print("Local MCP URL (keep the secret route private):")
    print(f"  {config.local_url()}")
    print()
    dns = _tailnet_dnsname()
    if dns:
        print("Public MCP URL for the ChatGPT connector (once `tailscale funnel` runs):")
        print(f"  https://{dns}{config.mcp_path}")
    else:
        print("Public URL once `tailscale funnel` is running:")
        print(f"  https://<machine>.<tailnet>.ts.net{config.mcp_path}")
        print("  (start Tailscale to auto-fill the hostname here)")
    return 0


def _cmd_doctor(config: Config) -> int:
    print("== chatgpt-code-harness doctor ==\n")
    print("Config:")
    for key, value in config.redacted().items():
        print(f"  {key}: {value}")
    print()

    ok = True
    print("Checks:")
    for root in config.workspace_roots:
        exists = root.exists()
        ok = ok and exists
        print(f"  [{'ok' if exists else 'MISSING'}] workspace root: {root}")
    for tool in ("git", "rg", "tailscale"):
        found = shutil.which(tool)
        note = found or "not found"
        if tool == "tailscale" and not found:
            note += " (needed only to expose to ChatGPT)"
        elif tool == "rg" and not found:
            note += " (grep falls back to pure Python)"
        print(f"  [{'ok' if found else 'warn'}] {tool}: {note}")
    print(f"  [ok] state dir: {config.state_dir}")
    print(f"  [{'ok' if config.bearer_token else 'warn'}] bearer token: "
          f"{'set' if config.bearer_token else 'not set (secret route is the gate)'}")
    print()
    print("Doctor finished." + ("" if ok else " Fix MISSING items above."))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harness", description="ChatGPT code harness MCP server")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="run the MCP server (default)")
    sub.add_parser("doctor", help="validate config and environment")
    sub.add_parser("url", help="print the MCP endpoint URLs")
    args = parser.parse_args(argv)

    config = Config.from_env()
    command = args.command or "serve"
    if command == "serve":
        return _cmd_serve(config)
    if command == "url":
        return _cmd_url(config)
    if command == "doctor":
        return _cmd_doctor(config)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
