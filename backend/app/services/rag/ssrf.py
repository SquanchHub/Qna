"""SSRF guard for every URL the backend fetches (design-rag.md §4.5.2, §4.6).

Staff can register any URL, so without this they could make the backend reach
``ollama:11434``, ``mysql:3306`` or cloud metadata at ``169.254.169.254``.
``guarded_get`` resolves each host once, refuses any internal address, and then
connects to that validated IP, sending the original name as ``Host`` and as the
TLS SNI. A second DNS answer (rebinding) is therefore never used. Redirects are
followed by hand, and each hop is checked again.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass, field
from email.message import Message
from urllib.parse import urljoin

import httpx

MAX_REDIRECTS = 5
FETCH_TIMEOUT_S = 30.0
_REDIRECTS = {301, 302, 303, 307, 308}
_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
# Deprecated or translation forms that can carry an internal IPv4 address
_REFUSED_V6 = (
    ipaddress.ip_network("::/96"),  # IPv4-compatible
    ipaddress.ip_network("::ffff:0:0:0/96"),  # SIIT
    ipaddress.ip_network("fec0::/10"),  # site-local
)


class FetchError(Exception):
    """A source could not be fetched. The message is safe to store and show."""


class UrlNotAllowed(FetchError):
    """The URL's scheme or host is not allowed (an SSRF target)."""


def _embedded_ipv4(addr: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    if addr.ipv4_mapped:
        return addr.ipv4_mapped
    if addr in _NAT64:
        return ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF)
    if addr.sixtofour:
        return addr.sixtofour
    if addr.teredo:
        return addr.teredo[1]
    return None


def is_public(ip: str) -> bool:
    """True only for a globally routable unicast address. IPv4 embedded in IPv6
    (mapped, NAT64, 6to4, Teredo) is judged by the IPv4 address."""
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address):
        if any(addr in net for net in _REFUSED_V6):
            return False
        addr = _embedded_ipv4(addr) or addr
    if addr.is_multicast or addr.is_unspecified:
        return False
    if isinstance(addr, ipaddress.IPv4Address) and addr in _CGNAT:
        return False
    return addr.is_global


def _normalise(host: str) -> str:
    return host.strip().rstrip(".").lower()


def _literal(host: str) -> str | None:
    try:
        return str(ipaddress.ip_address(host.strip("[]")))
    except ValueError:
        return None


def _is_localhost(host: str) -> bool:
    return host == "localhost" or host.endswith(".localhost")


async def resolve_public(host: str, port: int) -> str:
    """The address to connect to. Every DNS answer must be public."""
    host = _normalise(host)
    if not host or _is_localhost(host):
        raise UrlNotAllowed(f"host {host or '(empty)'} is not allowed")
    literal = _literal(host)
    if literal is not None:
        if not is_public(literal):
            raise UrlNotAllowed(f"address {literal} is not allowed")
        return literal
    try:
        infos = await asyncio.to_thread(
            socket.getaddrinfo, host, port, 0, socket.SOCK_STREAM
        )
    except (socket.gaierror, UnicodeError) as exc:
        raise FetchError(f"host {host} does not resolve") from exc
    addresses = [info[4][0] for info in infos]
    if not addresses:
        raise FetchError(f"host {host} does not resolve")
    for address in addresses:
        if not is_public(address):
            raise UrlNotAllowed(f"host {host} resolves to an internal address")
    return addresses[0]


async def check_registration_host(host: str) -> None:
    """The early check at registration. A host that doesn't resolve is accepted;
    the guard in guarded_get stays the authority."""
    try:
        await resolve_public(host, 443)
    except UrlNotAllowed:
        raise
    except FetchError:
        return


@dataclass
class FetchResult:
    final_url: str
    status: int
    headers: httpx.Headers
    body: bytes
    charset: str | None = field(default=None)


def _charset(content_type: str | None) -> str | None:
    if not content_type:
        return None
    msg = Message()
    msg["content-type"] = content_type
    return msg.get_param("charset") or None


def _transport() -> httpx.AsyncBaseTransport:
    # No keep-alive: httpcore pools by (scheme, IP, port) and ignores SNI, so a
    # pooled TLS connection could serve another host on the same IP
    return httpx.AsyncHTTPTransport(
        limits=httpx.Limits(max_keepalive_connections=0), retries=0
    )


def _parse(url: str) -> httpx.URL:
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL as exc:
        raise UrlNotAllowed("invalid URL") from exc
    if parsed.scheme not in ("http", "https"):
        raise UrlNotAllowed("only http and https URLs are allowed")
    if not parsed.host:
        raise UrlNotAllowed("URL has no host")
    return parsed


async def _hop(
    url: httpx.URL, headers: dict, max_bytes: int, timeout: float
) -> tuple[int, httpx.Headers, bytes]:
    port = url.port or (443 if url.scheme == "https" else 80)
    ip = await resolve_public(url.host, port)
    literal = _literal(url.host)
    name = f"[{url.host}]" if literal and ":" in literal else url.host
    host_header = name if url.port is None else f"{name}:{url.port}"
    target = url.copy_with(host=ip)
    # SNI carries only DNS names (RFC 6066)
    extensions = {} if literal else {"sni_hostname": url.host}
    async with httpx.AsyncClient(
        transport=_transport(),
        follow_redirects=False,
        trust_env=False,
        timeout=timeout,
    ) as client:
        async with client.stream(
            "GET",
            target,
            headers={**headers, "Host": host_header},
            extensions=extensions,
        ) as response:
            if response.status_code in _REDIRECTS:
                return response.status_code, response.headers, b""
            chunks, total = [], 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise FetchError(
                        f"response larger than {max_bytes // (1024 * 1024) or 1} MB"
                    )
                chunks.append(chunk)
            return response.status_code, response.headers, b"".join(chunks)


async def guarded_get(
    url: str,
    *,
    max_bytes: int,
    headers: dict | None = None,
    timeout: float = FETCH_TIMEOUT_S,
    max_redirects: int = MAX_REDIRECTS,
    allow_redirects: bool = True,
) -> FetchResult:
    """GET url under the guard. Non-2xx statuses, oversized bodies and network
    errors raise FetchError, and so does a 3xx when allow_redirects is False
    (token-bearing calls, so the header is never forwarded)."""
    current = _parse(url)
    for _ in range(max_redirects + 1):
        try:
            status, resp_headers, body = await asyncio.wait_for(
                _hop(current, headers or {}, max_bytes, timeout), timeout
            )
        except (httpx.HTTPError, TimeoutError) as exc:
            raise FetchError(
                f"could not fetch {current.host}: {type(exc).__name__}"
            ) from exc
        if status in _REDIRECTS:
            location = resp_headers.get("location")
            if not allow_redirects or not location:
                raise FetchError(f"HTTP {status} from {current.host}")
            current = _parse(urljoin(str(current), location))
            continue
        if not 200 <= status < 300:
            raise FetchError(f"HTTP {status} from {current.host}")
        return FetchResult(
            str(current),
            status,
            resp_headers,
            body,
            _charset(resp_headers.get("content-type")),
        )
    raise FetchError(f"more than {max_redirects} redirects")
