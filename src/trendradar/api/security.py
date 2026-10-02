"""Request guards for a local-first, unauthenticated API.

The app has no login, so any web page open in the user's browser could otherwise talk to
``http://127.0.0.1:8787`` (read drafts, trigger paid model calls, write files via the Easel
bridge). Two cheap guards close that hole without affecting the CLI, curl or tests:

* **Host allowlist** (``TrustedHostMiddleware``) — rejects DNS-rebinding requests whose ``Host``
  header is an attacker domain that resolves to 127.0.0.1.
* **Origin check** for state-changing methods — browsers always attach ``Origin`` to cross-site
  POST/PUT/PATCH/DELETE, including "simple" requests that skip CORS preflight. Requests from the
  app's own origin, a configured origin, or with no browser origin at all (CLI, scripts) pass.

``CORS`` is narrowed from ``*`` to the app's own and the Vite dev origins.

Configuration (``.env``):
    ALLOWED_HOSTS=   comma list of extra hostnames (e.g. LAN IP / proxy domain); ``*`` disables the check
    CORS_ORIGINS=    comma list of extra browser origins, e.g. ``https://radar.example.com``
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from ..core.logging import get_logger
from ..core.settings import Settings

log = get_logger("api.security")

LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
WILDCARD_BINDS = ("0.0.0.0", "::", "")
DEV_SERVER_PORT = 5173
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def split_csv(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def _is_loopback(host: str) -> bool:
    if host in LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def resolve_allowed_hosts(settings: Settings) -> list[str]:
    configured = split_csv(settings.allowed_hosts)
    if "*" in configured:
        return ["*"]
    hosts = [*LOOPBACK_HOSTS, *configured]
    bind = (settings.host or "").strip()
    if bind not in WILDCARD_BINDS and bind not in hosts:
        hosts.append(bind)
    return list(dict.fromkeys(h.lower() for h in hosts))


def resolve_allowed_origins(settings: Settings) -> list[str]:
    origins = [
        f"http://{host}:{port}"
        for host in ("127.0.0.1", "localhost")
        for port in dict.fromkeys((settings.port, DEV_SERVER_PORT))
    ]
    origins.extend(origin.rstrip("/") for origin in split_csv(settings.cors_origins))
    return list(dict.fromkeys(origins))


def _forbidden(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=403, content={"error": "forbidden_origin", "message": message, "details": {}}
    )


class OriginGuardMiddleware:
    """Reject cross-site state-changing requests (CSRF from any open web page)."""

    def __init__(self, app: ASGIApp, allowed_origins: list[str]) -> None:
        self.app = app
        self.allowed = {origin.lower() for origin in allowed_origins}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"].upper() in SAFE_METHODS:
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        origin = headers.get("origin", "").strip().lower().rstrip("/")
        if not origin:
            # No Origin: CLI / scripts / tests. Old browsers still expose Sec-Fetch-Site.
            if headers.get("sec-fetch-site", "").lower() == "cross-site":
                await _forbidden("跨站请求被拒绝")(scope, receive, send)
                return
            await self.app(scope, receive, send)
            return
        if origin in self.allowed or self._same_origin(origin, headers.get("host", "")):
            await self.app(scope, receive, send)
            return
        log.warning("blocked %s %s from origin %s", scope["method"], scope.get("path"), origin)
        await _forbidden("来源不在允许列表中（可在 .env 的 CORS_ORIGINS 中添加）")(scope, receive, send)

    @staticmethod
    def _same_origin(origin: str, host: str) -> bool:
        # Host itself is validated by TrustedHostMiddleware, so a matching Origin is our own UI.
        if origin == "null" or not host:
            return False
        return urlsplit(origin).netloc == host.strip().lower()


def install_security(app: FastAPI, settings: Settings) -> None:
    hosts = resolve_allowed_hosts(settings)
    origins = resolve_allowed_origins(settings)
    if hosts != ["*"] and not _is_loopback(settings.host) and not split_csv(settings.allowed_hosts):
        log.warning(
            "HOST=%s 对外监听，但只信任本机 Host；局域网 / 反向代理访问请在 ALLOWED_HOSTS 中加入域名或 IP",
            settings.host,
        )
    # add_middleware wraps outward: TrustedHost runs first, then CORS, then the origin guard.
    app.add_middleware(OriginGuardMiddleware, allowed_origins=origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)
