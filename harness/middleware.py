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

        if self.config.connector_log and scope.get("method") == "POST":
            receive = await self._logging_receive(receive, headers, ip)

        await self.app(scope, receive, send)

    async def _logging_receive(self, receive, headers: dict, ip: str):
        """Record which JSON-RPC method the client asked for, then replay the
        body untouched.

        This exists to answer one question no amount of local testing can:
        does the connector ever RE-READ our tool list? A client that never
        sends `tools/list` again is serving a cached menu, and no change to the
        tools on this machine can reach it. Without this log that distinction
        is pure guesswork.

        Only the first body chunk is parsed — enough for JSON-RPC, whose method
        is at the top of the object — and a chunked or unparseable body is
        skipped rather than risking the request.
        """
        first = await receive()
        try:
            payload = json.loads(first.get("body", b"") or b"{}")
            method = payload.get("method")
        except (ValueError, AttributeError):
            method = None
        if method:
            self._log_connector(method, headers, ip)
        replayed = False

        async def wrapped():
            nonlocal replayed
            if not replayed:
                replayed = True
                return first
            return await receive()

        return wrapped

    def _log_connector(self, method: str, headers: dict, ip: str) -> None:
        record = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "method": method,
            "ip": ip,
            # The user agent is how we tell OpenAI's fetch apart from our own
            # probes and the Workbench.
            "agent": headers.get("user-agent", "")[:120],
        }
        try:
            path = self.config.state_dir / "connector.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass  # observability must never break a request

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
