"""Security middleware: rate limiting and response headers."""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


def _int_env(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple sliding-window rate limiter per client IP.

    - MATH_COACH_RATE_LIMIT_PER_MINUTE: general API limit (0 disables)
    - MATH_COACH_AUTH_RATE_LIMIT_PER_MINUTE: stricter limit for auth endpoints
    """

    AUTH_PATHS = {
        "/api/auth/login",
        "/api/auth/register",
    }

    def __init__(self, app, general_limit: int | None = None, auth_limit: int | None = None):
        super().__init__(app)
        self.general_limit = (
            general_limit
            if general_limit is not None
            else _int_env("MATH_COACH_RATE_LIMIT_PER_MINUTE", 120)
        )
        self.auth_limit = (
            auth_limit
            if auth_limit is not None
            else _int_env("MATH_COACH_AUTH_RATE_LIMIT_PER_MINUTE", 20)
        )
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._window = 60.0
        self._trust_proxy_headers = str(
            os.getenv("MATH_COACH_TRUST_PROXY_HEADERS", "false")
        ).strip().lower() in {"1", "true", "yes", "on"}
        self._max_client_keys = 10_000
        self._last_cleanup = 0.0

    def _client_key(self, request: Request) -> str:
        if self._trust_proxy_headers:
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                # A trusted reverse proxy appends the client address at the end.
                # Taking the last value avoids accepting a client-supplied prefix.
                return forwarded.split(",")[-1].strip() or "unknown"
        if request.client and request.client.host:
            return request.client.host
        return "unknown"

    def _allow(self, key: str, limit: int) -> bool:
        if limit <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            self._cleanup(now)
            bucket = self._hits[key]
            while bucket and now - bucket[0] > self._window:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            return True

    def _cleanup(self, now: float) -> None:
        # Avoid unbounded memory growth when exposed to many client addresses.
        if now - self._last_cleanup < self._window:
            return
        self._last_cleanup = now
        for key, bucket in list(self._hits.items()):
            while bucket and now - bucket[0] > self._window:
                bucket.popleft()
            if not bucket:
                self._hits.pop(key, None)
        while len(self._hits) >= self._max_client_keys:
            _, oldest_key = min(
                ((bucket[0], key) for key, bucket in self._hits.items() if bucket),
                default=(0.0, ""),
            )
            if not oldest_key:
                break
            self._hits.pop(oldest_key, None)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        if path.startswith("/api/"):
            key = self._client_key(request)
            limit = self.auth_limit if path in self.AUTH_PATHS else self.general_limit
            # Auth endpoints also count against the general bucket when both enabled.
            if path in self.AUTH_PATHS:
                if not self._allow(f"auth:{key}", self.auth_limit):
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "登录/注册过于频繁，请稍后再试"},
                    )
            if not self._allow(f"api:{key}", self.general_limit if path not in self.AUTH_PATHS else max(self.general_limit, self.auth_limit)):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "请求过于频繁，请稍后再试"},
                )
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach baseline security headers (CSP, HSTS optional, nosniff, etc.)."""

    def __init__(self, app, enable_hsts: bool | None = None):
        super().__init__(app)
        if enable_hsts is None:
            raw = (os.getenv("MATH_COACH_ENABLE_HSTS") or "").strip().lower()
            if raw in {"1", "true", "yes", "on"}:
                enable_hsts = True
            elif raw in {"0", "false", "no", "off"}:
                enable_hsts = False
            else:
                # Default on when cookie secure is forced (TLS expected).
                enable_hsts = (os.getenv("MATH_COACH_COOKIE_SECURE") or "").lower() in {
                    "1",
                    "true",
                    "yes",
                    "on",
                }
        self.enable_hsts = bool(enable_hsts)
        self.csp = os.getenv(
            "MATH_COACH_CSP",
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "font-src 'self' data:; "
            "connect-src 'self'; "
            "media-src 'self' blob: data:; "
            "object-src 'none'; "
            "frame-src 'self' blob:; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'",
        )

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(self), microphone=(self), geolocation=()",
        )
        if self.csp:
            response.headers.setdefault("Content-Security-Policy", self.csp)
        if self.enable_hsts:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response
