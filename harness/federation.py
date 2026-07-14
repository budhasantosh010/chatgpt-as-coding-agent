"""MCP client federation: consume tools from OTHER MCP servers.

This is the "scale without breaking" axis — new capabilities come from plugging
in an existing MCP server (Playwright, a database server, etc.) instead of
hand-coding a tool. Servers are declared in config (stdio command or http url);
we connect on demand, list and proxy their tools.

Connections are per-call (open → initialize → call → close): simple and robust;
a slow external server can't wedge the harness.
"""

from __future__ import annotations

from typing import Any, Callable


class FederationError(Exception):
    pass


class FederationManager:
    def __init__(self, servers: dict | None = None):
        self.servers = dict(servers or {})

    def names(self) -> list[str]:
        return list(self.servers)

    def _config(self, name: str) -> dict:
        cfg = self.servers.get(name)
        if cfg is None:
            raise FederationError(
                f"Unknown MCP server {name!r}. Configured: {', '.join(self.names()) or '(none)'}"
            )
        return cfg

    async def _with_session(self, name: str, fn: Callable[[Any], Any]):
        from mcp import ClientSession

        cfg = self._config(name)
        if cfg.get("url"):
            from mcp.client.streamable_http import streamablehttp_client

            async with streamablehttp_client(cfg["url"]) as (read, write, _meta):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return await fn(session)
        else:
            from mcp.client.stdio import StdioServerParameters, stdio_client

            params = StdioServerParameters(
                command=cfg["command"], args=cfg.get("args", []), env=cfg.get("env"),
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return await fn(session)

    async def list_tools(self, name: str) -> list[tuple[str, str]]:
        async def _fn(session):
            resp = await session.list_tools()
            return [(t.name, (t.description or "").split("\n")[0]) for t in resp.tools]

        return await self._with_session(name, _fn)

    async def call_tool(self, name: str, tool: str, arguments: dict) -> str:
        async def _fn(session):
            result = await session.call_tool(tool, arguments or {})
            parts: list[str] = []
            for block in result.content:
                text = getattr(block, "text", None)
                parts.append(text if text is not None else f"[{getattr(block, 'type', 'content')}]")
            return "\n".join(parts) if parts else "(no content)"

        return await self._with_session(name, _fn)
