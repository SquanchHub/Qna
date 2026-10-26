"""SSRF guard (design-rag.md §4.5.2, §4.6): address checks and the IP-pinned fetch."""

import socket

import httpx
import pytest

from app.services.rag import ssrf
from app.services.rag.ssrf import FetchError, UrlNotAllowed, guarded_get, is_public


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "224.0.0.1",
        "255.255.255.255",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
        "64:ff9b::7f00:1",
        "2002:7f00:1::",
        "::",
        "::7f00:1",
        "::a9fe:a9fe",
        "::ffff:0:7f00:1",
        "fec0::1",
    ],
)
def test_internal_addresses_are_refused(ip):
    assert not is_public(ip)


@pytest.mark.parametrize("ip", ["93.184.216.34", "8.8.8.8", "2606:4700::1"])
def test_public_addresses_are_allowed(ip):
    assert is_public(ip)


def _fake_getaddrinfo(mapping):
    def fake(host, port, *args, **kwargs):
        if host not in mapping:
            raise socket.gaierror("no such host")
        return [
            (socket.AF_INET6 if ":" in ip else socket.AF_INET, 1, 6, "", (ip, port))
            for ip in mapping[host]
        ]

    return fake


async def test_any_private_answer_refuses_the_host(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        _fake_getaddrinfo({"mixed.test": ["8.8.8.8", "10.0.0.5"]}),
    )
    with pytest.raises(UrlNotAllowed):
        await ssrf.resolve_public("mixed.test", 443)


async def test_localhost_names_are_refused_without_dns(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo({}))
    for host in ("localhost", "LOCALHOST.", "api.localhost"):
        with pytest.raises(UrlNotAllowed):
            await ssrf.check_registration_host(host)


async def test_registration_accepts_unresolvable_and_public_names(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo", _fake_getaddrinfo({"example.test": ["93.184.216.34"]})
    )
    await ssrf.check_registration_host("example.test")
    await ssrf.check_registration_host("nowhere.test")  # DNS failure: checked at fetch


async def test_registration_refuses_private_names_and_literals(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo", _fake_getaddrinfo({"ollama": ["172.18.0.4"]})
    )
    for host in ("ollama", "10.0.0.1", "169.254.169.254", "::1"):
        with pytest.raises(UrlNotAllowed):
            await ssrf.check_registration_host(host)


async def test_unresolvable_host_fails_at_fetch(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo({}))
    with pytest.raises(FetchError, match="resolve"):
        await guarded_get("https://nowhere.test/", max_bytes=100)


# guarded_get, on a MockTransport


@pytest.fixture
def transport(monkeypatch):
    """Routes requests to a handler; DNS maps names to public test addresses."""
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        _fake_getaddrinfo(
            {
                "example.test": ["93.184.216.34"],
                "other.test": ["8.8.8.8"],
                "v6.test": ["2606:4700::1"],
                "evil.test": ["127.0.0.1"],
            }
        ),
    )
    seen: list[httpx.Request] = []
    routes = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        key = (request.headers["host"], request.url.path)
        if key not in routes:
            return httpx.Response(404)
        return routes[key](request)

    monkeypatch.setattr(ssrf, "_transport", lambda: httpx.MockTransport(handler))
    return routes, seen


async def test_connects_to_the_validated_ip_with_host_and_sni(transport):
    routes, seen = transport
    routes[("example.test", "/s.html")] = lambda r: httpx.Response(
        200, content=b"<p>hi</p>", headers={"content-type": "text/html; charset=utf-8"}
    )
    result = await guarded_get("https://example.test/s.html?x=1", max_bytes=1000)
    assert result.body == b"<p>hi</p>"
    assert result.final_url == "https://example.test/s.html?x=1"
    assert result.charset == "utf-8"
    req = seen[0]
    assert req.url.host == "93.184.216.34"
    assert req.url.query == b"x=1"
    assert req.extensions["sni_hostname"] == "example.test"


async def test_ipv6_is_bracketed_and_port_kept_in_host(transport):
    routes, seen = transport
    routes[("v6.test:8443", "/")] = lambda r: httpx.Response(200, content=b"ok")
    await guarded_get("https://v6.test:8443/", max_bytes=10)
    assert seen[0].url.host == "2606:4700::1"
    assert seen[0].url.port == 8443


async def test_ipv6_literal_host_is_bracketed_without_sni(transport):
    routes, seen = transport
    routes[("[2606:4700::1]", "/")] = lambda r: httpx.Response(200, content=b"ok")
    await guarded_get("https://[2606:4700::1]/", max_bytes=10)
    assert seen[0].headers["host"] == "[2606:4700::1]"
    assert "sni_hostname" not in seen[0].extensions


async def test_redirect_to_internal_host_is_refused(transport):
    routes, _ = transport
    routes[("example.test", "/")] = lambda r: httpx.Response(
        302, headers={"location": "http://evil.test/admin"}
    )
    with pytest.raises(UrlNotAllowed):
        await guarded_get("https://example.test/", max_bytes=10)


async def test_relative_redirect_resolves_against_the_logical_url(transport):
    routes, seen = transport
    routes[("example.test", "/a/")] = lambda r: httpx.Response(
        301, headers={"location": "../b"}
    )
    routes[("example.test", "/b")] = lambda r: httpx.Response(200, content=b"b")
    result = await guarded_get("https://example.test/a/", max_bytes=10)
    assert result.final_url == "https://example.test/b"
    assert seen[1].headers["host"] == "example.test"


async def test_too_many_redirects(transport):
    routes, _ = transport
    for i in range(7):
        routes[("example.test", f"/{i}")] = lambda r, i=i: httpx.Response(
            302, headers={"location": f"/{i + 1}"}
        )
    with pytest.raises(FetchError, match="redirects"):
        await guarded_get("https://example.test/0", max_bytes=10)


async def test_redirects_off_makes_3xx_an_error(transport):
    routes, _ = transport
    routes[("example.test", "/")] = lambda r: httpx.Response(
        302, headers={"location": "https://other.test/"}
    )
    with pytest.raises(FetchError, match="302"):
        await guarded_get("https://example.test/", max_bytes=10, allow_redirects=False)


async def test_body_over_the_cap_aborts(transport):
    routes, _ = transport
    routes[("example.test", "/big")] = lambda r: httpx.Response(200, content=b"x" * 101)
    with pytest.raises(FetchError, match="larger"):
        await guarded_get("https://example.test/big", max_bytes=100)


async def test_non_2xx_is_an_error(transport):
    with pytest.raises(FetchError, match="404"):
        await guarded_get("https://example.test/missing", max_bytes=10)


@pytest.mark.parametrize(
    "url", ["ftp://example.test/x", "file:///etc/passwd", "https:///x"]
)
async def test_bad_schemes_and_hostless_urls(url):
    with pytest.raises(UrlNotAllowed):
        await guarded_get(url, max_bytes=10)


def test_url_not_allowed_is_a_fetch_error():
    assert issubclass(UrlNotAllowed, FetchError)
