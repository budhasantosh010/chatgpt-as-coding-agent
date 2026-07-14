"""Composition root: assemble config -> context -> MCP server -> secured ASGI app.

This is the only place wiring happens. Everything above it (tools, security,
policy) is independent and unit-testable; everything below (uvicorn, Tailscale)
is deployment.
"""

from __future__ import annotations

from .config import Config
from .context import HarnessServer
from .middleware import SecurityMiddleware
from .server import build_mcp


def build_asgi_app(config: Config):
    """Return (asgi_app, harness_server). The app is the FastMCP Streamable-HTTP
    app wrapped in the security middleware."""
    server = HarnessServer(config)
    mcp = build_mcp(config, server)
    app = mcp.streamable_http_app()
    app.add_middleware(SecurityMiddleware, config=config)
    return app, server
