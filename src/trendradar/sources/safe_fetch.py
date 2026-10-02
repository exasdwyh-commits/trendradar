"""Fetching user-supplied URLs without turning the server into an SSRF proxy.

``material_from_url`` downloads whatever link the user pastes. Without checks a link (or a
redirect from a harmless-looking link) could reach ``127.0.0.1``, the LAN, or cloud metadata
endpoints such as ``169.254.169.254`` and store the response as a material.

Rules: http(s) only, no credentials in the URL, every hop's host must resolve exclusively to
public (globally routable) addresses, redirects are followed manually and re-validated, and the
body is capped. A DNS answer can still change between the check and the connect (rebinding);
for a single-user local tool this residual risk is accepted.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from ..core.errors import SourceError, ValidationFailed
from .http import DEFAULT_HEADERS

MAX_REDIRECTS = 5
MAX_BYTES = 3_000_000
TEXT_TYPES = ("text/html", "application/xhtml+xml", "text/plain", "application/xml", "text/xml")
_META_CHARSET = re.compile(rb"""<meta[^>]+charset=["']?\s*([A-Za-z0-9_\-]+)""", re.I)


class UnsafeURL(ValidationFailed):
    code = "unsafe_url"


@dataclass(frozen=True)
class FetchedPage:
    url: str
    text: str
    truncated: bool = False


def _resolve(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SourceError(f"无法解析域名：{host}", details={"host": host}) from exc
    return [str(info[4][0]) for info in infos]


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def assert_public_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UnsafeURL("请输入 http(s) 链接", details={"url": url})
    if parts.username or parts.password:
        raise UnsafeURL("链接不能包含账号密码", details={"url": url})
    host = parts.hostname
    if not host:
        raise UnsafeURL("链接缺少域名", details={"url": url})
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise UnsafeURL("链接端口无效", details={"url": url}) from exc
    addresses = _resolve(host, port)
    blocked = [a for a in addresses if not _is_public(a)]
    if not addresses or blocked:
        raise UnsafeURL(
            "不允许抓取本机、局域网或保留地址", details={"url": url, "host": host, "addresses": blocked}
        )


def _decode(body: bytes, header_charset: str | None) -> str:
    for candidate in (header_charset, _sniff_charset(body), "utf-8"):
        if not candidate:
            continue
        try:
            return body.decode(candidate)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", errors="replace")


def _sniff_charset(body: bytes) -> str | None:
    match = _META_CHARSET.search(body[:4096])
    if not match:
        return None
    name = match.group(1).decode("ascii", errors="ignore").lower()
    return "gb18030" if name in ("gb2312", "gbk") else name


def fetch_public_page(
    url: str,
    *,
    timeout: float = 15,
    max_bytes: int = MAX_BYTES,
    max_redirects: int = MAX_REDIRECTS,
    transport: httpx.BaseTransport | None = None,
) -> FetchedPage:
    current = url
    with httpx.Client(
        timeout=timeout, headers=DEFAULT_HEADERS, follow_redirects=False, transport=transport
    ) as client:
        for _ in range(max_redirects + 1):
            assert_public_url(current)
            try:
                with client.stream("GET", current) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise SourceError("重定向缺少目标地址", details={"url": current})
                        current = urljoin(current, location)
                        continue
                    if response.status_code >= 400:
                        raise SourceError(
                            f"抓取失败：HTTP {response.status_code}",
                            details={"url": current, "status": response.status_code},
                        )
                    ctype = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    if ctype and not ctype.startswith(TEXT_TYPES):
                        raise SourceError(f"不是网页内容（{ctype}）", details={"url": current})
                    body = bytearray()
                    truncated = False
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) >= max_bytes:
                            truncated = True
                            del body[max_bytes:]
                            break
                    return FetchedPage(
                        url=current, text=_decode(bytes(body), response.charset_encoding), truncated=truncated
                    )
            except httpx.HTTPError as exc:
                raise SourceError(f"抓取失败：{exc.__class__.__name__}", details={"url": current}) from exc
    raise SourceError("重定向次数过多", details={"url": url})
