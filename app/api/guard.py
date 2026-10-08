"""Request guard: bounded bodies, ephemeral rate counters, security headers.

Pure ASGI (not BaseHTTPMiddleware) so Server-Sent Events are never buffered.
Rate counters hold peer addresses and timestamps only, in process memory.
"""
from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from threading import Lock

from fastapi.responses import JSONResponse

MAX_DEPTH = 32
MAX_PEERS = 2048

CSP = (
    b"default-src 'self'; script-src 'self'; style-src 'self'; "
    b"img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
)
DOCS_CSP = (
    b"default-src 'self'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    b"style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    b"img-src 'self' data: https://fastapi.tiangolo.com; frame-ancestors 'none'; base-uri 'none'"
)


def check_depth(text: str, limit: int = MAX_DEPTH) -> None:
    depth, in_string, escaped = 0, False, False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch in "{[":
            depth += 1
            if depth > limit:
                raise ValueError(f"Nesting exceeds {limit} levels")
        elif ch in "}]":
            depth -= 1


class GuardMiddleware:
    def __init__(self, app, *, rate_limit: int | None = None, global_limit: int | None = None,
                 max_body: int | None = None, body_timeout: float = 10.0):
        self.app = app
        self.rate_limit = rate_limit if rate_limit is not None else int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
        self.global_limit = global_limit if global_limit is not None else int(os.getenv("RATE_LIMIT_GLOBAL_PER_MINUTE", "180"))
        self.max_body = max_body if max_body is not None else int(os.getenv("MAX_BODY_BYTES", str(256 * 1024)))
        self.body_timeout = body_timeout
        self.clients: dict[str, deque] = {}
        self.global_times: deque = deque()
        self.lock = Lock()

    def _limited(self, key: str) -> bool:
        now = time.monotonic()
        with self.lock:
            self.clients = {k: q for k, q in self.clients.items() if q and q[-1] > now - 60}
            q = self.clients.get(key, deque())
            for queue in (q, self.global_times):
                while queue and queue[0] <= now - 60:
                    queue.popleft()
            full = key not in self.clients and len(self.clients) >= MAX_PEERS
            if len(q) >= self.rate_limit or len(self.global_times) >= self.global_limit or full:
                return True
            q.append(now)
            self.global_times.append(now)
            self.clients[key] = q
            return False

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        if scope["method"] == "POST":
            key = (scope.get("client") or ("unknown",))[0]
            if self._limited(key):
                return await JSONResponse(
                    {"detail": "Request limit reached. Try again in 60 seconds."}, 429, headers={"Retry-After": "60"}
                )(scope, receive, send)
            chunks, size = [], 0
            while True:
                try:
                    message = await asyncio.wait_for(receive(), timeout=self.body_timeout)
                except TimeoutError:
                    return await JSONResponse({"detail": "Request body timed out."}, 408)(scope, receive, send)
                if message["type"] == "http.disconnect":
                    return
                body = message.get("body", b"")
                size += len(body)
                if size > self.max_body:
                    return await JSONResponse({"detail": f"Request body exceeds {self.max_body // 1024} KiB."}, 413)(scope, receive, send)
                chunks.append(body)
                if not message.get("more_body"):
                    break
            payload = b"".join(chunks)
            try:
                check_depth(payload.decode("utf-8"))
            except (ValueError, UnicodeError):
                return await JSONResponse({"detail": "Request nesting exceeds 32 levels or encoding is invalid."}, 422)(scope, receive, send)

            original_receive, replayed = receive, False

            async def replay_body():
                nonlocal replayed
                if not replayed:
                    replayed = True
                    return {"type": "http.request", "body": payload, "more_body": False}
                return await original_receive()  # later calls wait for the real disconnect

            receive = replay_body

        async def secure_send(message):
            if message["type"] == "http.response.start":
                csp = DOCS_CSP if scope["path"].startswith(("/docs", "/redoc")) else CSP
                headers = [(k, v) for k, v in message["headers"] if k.lower() not in (b"content-security-policy",)]
                names = {k.lower() for k, _ in headers}
                extra = [(b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer"),
                         (b"content-security-policy", csp)]
                if b"cache-control" not in names:
                    extra.append((b"cache-control", b"no-store"))
                message["headers"] = headers + [h for h in extra if h[0] not in names]
            await send(message)

        await self.app(scope, receive, secure_send)
