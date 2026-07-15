"""Composition root: assemble config -> context -> MCP server -> secured ASGI app.

This is the only place wiring happens. Everything above it (tools, security,
policy) is independent and unit-testable; everything below (uvicorn, Tailscale)
is deployment.
"""

from __future__ import annotations

import contextlib

from .config import Config
from .context import HarnessServer
from .middleware import SecurityMiddleware
from .server import build_mcp


def build_asgi_app(config: Config):
    """Return (asgi_app, harness_server). The app is the FastMCP Streamable-HTTP
    app wrapped in the security middleware, with a lifespan that terminates any
    background processes on shutdown so nothing orphans."""
    server = HarnessServer(config)
    mcp = build_mcp(config, server)
    app = mcp.streamable_http_app()

    inner_lifespan = app.router.lifespan_context

    @contextlib.asynccontextmanager
    async def lifespan(app_):
        async with inner_lifespan(app_):
            try:
                yield
            finally:
                await server.processes.shutdown_all()
                server.lsp.shutdown_all()

    app.router.lifespan_context = lifespan
    app.add_middleware(SecurityMiddleware, config=config)
    return app, server
