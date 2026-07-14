"""Pure-ASGI security middleware.

Implemented at the raw ASGI level (not Starlette BaseHTTPMiddleware) so it never
buffers the MCP Streamable-HTTP / SSE response bodies. Gates every HTTP request
on: secret route prefix, Host allowlist (anti DNS-rebinding), Origin allowlist
(when present), optional bearer token, and a simple per-IP rate limit. Non-HTTP
scopes (lifespan, websocket) pass straight through.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict, deque

from .config import Config


class SecurityMiddleware:
    def __init__(self, app, config: Config):
        self.app = app
        self.config = config
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope.get("headers", [])
        }
        path = scope.get("path", "")

        if path == "/health":
            await self.app(scope, receive, send)
            return

        if not path.startswith(f"/{self.config.secret_route}"):
            await self._reject(send, 404, "not found")
            return

        host = headers.get("host", "").split(":")[0].lower()
        if not self._host_allowed(host):
            await self._reject(send, 403, "host not allowed")
            return

        origin = headers.get("origin")
        if origin and origin not in self.config.allowed_origins:
            await self._reject(send, 403, "origin not allowed")
            return

        if self.config.bearer_token:
            auth = headers.get("authorization", "")
            if not _constant_time_eq(auth, f"Bearer {self.config.bearer_token}"):
                await self._reject(send, 401, "unauthorized")
                return

        client = scope.get("client")
        ip = client[0] if client else "unknown"
        if not self._rate_ok(ip):
            await self._reject(send, 429, "rate limit exceeded")
            return

        await self.app(scope, receive, send)

    def _host_allowed(self, host: str) -> bool:
        if host in (h.lower() for h in self.config.allowed_hosts):
            return True
        if self.config.allow_ts_net and host.endswith(".ts.net"):
            return True
        return False

    def _rate_ok(self, ip: str) -> bool:
        now = time.monotonic()
        window = self._hits[ip]
        while window and now - window[0] > 60.0:
            window.popleft()
        if len(window) >= self.config.rate_limit_per_min:
            return False
        window.append(now)
        return True

    async def _reject(self, send, status: int, message: str) -> None:
        body = json.dumps({"error": message}).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("latin-1")),
            ],
        })
        await send({"type": "http.response.body", "body": body})


def _constant_time_eq(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a.encode(), b.encode()):
        result |= x ^ y
    return result == 0
