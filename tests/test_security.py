"""Request guards (api/security.py) and SSRF-safe fetching (sources/safe_fetch.py)."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from trendradar.core.errors import SourceError
from trendradar.core.settings import Settings
from trendradar.sources import safe_fetch


@pytest.fixture()
def make_client(tmp_path, monkeypatch):
    from trendradar.core.settings import reset_settings

    def build(base_url: str = "http://127.0.0.1:8787", **env: str) -> TestClient:
        monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("ALLOWED_HOSTS", env.pop("ALLOWED_HOSTS", ""))
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        reset_settings()
        from trendradar.api import create_app

        return TestClient(create_app(static_dir=tmp_path / "nope"), base_url=base_url)

    yield build
    reset_settings()


NOTE = {"title": "安全测试", "content": "fact"}


def test_untrusted_host_is_rejected(make_client):
    with make_client() as c:
        assert c.get("/api/health").status_code == 200
        assert c.get("/api/health", headers={"host": "evil.example"}).status_code == 400


def test_cross_site_write_is_blocked_but_cli_and_own_ui_pass(make_client):
    with make_client() as c:
        blocked = c.post("/api/materials", json=NOTE, headers={"origin": "https://evil.example"})
        assert blocked.status_code == 403 and blocked.json()["error"] == "forbidden_origin"
        # "simple" form POST that skips preflight is blocked too
        form = c.post("/api/materials", data={"x": "1"}, headers={"origin": "https://evil.example"})
        assert form.status_code == 403
        assert (
            c.post("/api/materials", json=NOTE, headers={"sec-fetch-site": "cross-site"}).status_code == 403
        )
        assert c.post("/api/materials", json=NOTE).status_code == 201  # CLI / scripts: no Origin
        own = c.post("/api/materials", json=NOTE, headers={"origin": "http://127.0.0.1:8787"})
        assert own.status_code == 201
        dev = c.post("/api/materials", json=NOTE, headers={"origin": "http://localhost:5173"})
        assert dev.status_code == 201


def test_cors_only_reflects_known_origins(make_client):
    preflight = {"access-control-request-method": "POST", "access-control-request-headers": "content-type"}
    with make_client() as c:
        ok = c.options("/api/materials", headers={"origin": "http://localhost:5173", **preflight})
        assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
        bad = c.options("/api/materials", headers={"origin": "https://evil.example", **preflight})
        assert "access-control-allow-origin" not in bad.headers


def test_lan_access_needs_allowed_hosts_and_is_same_origin(make_client):
    with make_client("http://192.168.1.5:8787", ALLOWED_HOSTS="192.168.1.5") as c:
        r = c.post("/api/materials", json=NOTE, headers={"origin": "http://192.168.1.5:8787"})
        assert r.status_code == 201
    with make_client("http://192.168.1.5:8787") as c:
        assert c.get("/api/health").status_code == 400


def test_extra_cors_origin(make_client):
    with make_client(CORS_ORIGINS="https://radar.example.com/") as c:
        r = c.post("/api/materials", json=NOTE, headers={"origin": "https://radar.example.com"})
        assert r.status_code == 201


def test_resolve_allowed_hosts():
    from trendradar.api.security import resolve_allowed_hosts

    assert "192.168.1.5" in resolve_allowed_hosts(Settings(host="192.168.1.5", allowed_hosts=""))
    assert "0.0.0.0" not in resolve_allowed_hosts(Settings(host="0.0.0.0", allowed_hosts=""))
    assert resolve_allowed_hosts(Settings(allowed_hosts="*")) == ["*"]


# ── SSRF ──


@pytest.fixture()
def fake_dns(monkeypatch):
    table = {
        "public.example": "93.184.216.34",
        "other.example": "93.184.216.35",
        "internal.example": "10.0.0.8",
        "meta.example": "169.254.169.254",
    }

    def resolve(host: str, port: int) -> list[str]:
        try:
            return [str(__import__("ipaddress").ip_address(host))]
        except ValueError:
            return [table[host]]

    monkeypatch.setattr(safe_fetch, "_resolve", resolve)
    return table


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8787/api/health",
        "http://localhost.invalid/",
        "http://internal.example/admin",
        "http://meta.example/latest/meta-data/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://user:pw@public.example/",
        "file:///etc/passwd",
    ],
)
def test_private_and_odd_urls_are_rejected(fake_dns, url):
    fake_dns["localhost.invalid"] = "127.0.0.1"
    with pytest.raises(safe_fetch.UnsafeURL):
        safe_fetch.assert_public_url(url)


def _transport(routes: dict[str, httpx.Response]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return routes[str(request.url)]

    return httpx.MockTransport(handler)


def test_redirect_to_private_address_is_rejected(fake_dns):
    transport = _transport(
        {"http://public.example/a": httpx.Response(302, headers={"location": "http://internal.example/x"})}
    )
    with pytest.raises(safe_fetch.UnsafeURL):
        safe_fetch.fetch_public_page("http://public.example/a", transport=transport)


def test_public_page_with_redirect_charset_and_size_cap(fake_dns):
    html = '<html><head><meta charset="gbk"><title>标题</title></head><body>正文内容</body></html>'
    transport = _transport(
        {
            "http://public.example/a": httpx.Response(301, headers={"location": "/b"}),
            "http://public.example/b": httpx.Response(302, headers={"location": "http://other.example/c"}),
            "http://other.example/c": httpx.Response(
                200, headers={"content-type": "text/html"}, content=html.encode("gbk")
            ),
        }
    )
    page = safe_fetch.fetch_public_page("http://public.example/a", transport=transport)
    assert page.url == "http://other.example/c" and "正文内容" in page.text and not page.truncated
    capped = safe_fetch.fetch_public_page("http://public.example/a", transport=transport, max_bytes=20)
    assert capped.truncated and len(capped.text.encode("gbk", errors="ignore")) <= 20


def test_non_html_and_errors_become_source_errors(fake_dns):
    transport = _transport(
        {
            "http://public.example/zip": httpx.Response(200, headers={"content-type": "application/zip"}),
            "http://public.example/404": httpx.Response(404),
            "http://public.example/loop": httpx.Response(302, headers={"location": "/loop"}),
        }
    )
    for path in ("zip", "404", "loop"):
        with pytest.raises(SourceError):
            safe_fetch.fetch_public_page(f"http://public.example/{path}", transport=transport)


def test_material_from_url_uses_safe_fetch(conn, monkeypatch):
    from trendradar.studio import materials

    with pytest.raises(safe_fetch.UnsafeURL):
        materials.material_from_url(conn, "http://127.0.0.1:8787/api/settings")
    monkeypatch.setattr(
        materials,
        "fetch_public_page",
        lambda url: safe_fetch.FetchedPage(url=url, text="<title>T</title><p>Body text here.</p>"),
    )
    material = materials.get_material(conn, materials.material_from_url(conn, "https://public.example/p"))
    assert material["kind"] == "url" and material["url"] == "https://public.example/p"
