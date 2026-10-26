"""HTTP probes for the three RAG services (design-rag.md §4.3, §6 health row).

Each probe takes the caller's httpx.AsyncClient, so tests can pass one built
on httpx.MockTransport, and never raises: a down, slow or misbehaving service
is reported as ``ok: False``. Callers must not share one client across event
loops, so the health route opens a client per request.
"""

from __future__ import annotations

import asyncio
from importlib.metadata import PackageNotFoundError, version

import httpx
import structlog

from ...config import settings

logger = structlog.get_logger()

# Per probe, covering both of its requests; the integration tests time out at 10 s
HEALTH_TIMEOUT_S = 3.0


def chroma_client_version() -> str:
    try:
        return version("chromadb-client")
    except PackageNotFoundError:
        return "unknown"


async def _probe(service: str, coro, down: dict) -> dict:
    try:
        return await asyncio.wait_for(coro, HEALTH_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 - health must report, never raise
        logger.warning(
            "rag_health_probe_failed", service=service, error=type(exc).__name__
        )
        return down


async def ollama_health(http: httpx.AsyncClient) -> dict:
    async def check() -> dict:
        r = await http.get(f"{settings.OLLAMA_URL}/api/tags")
        r.raise_for_status()
        return {"ok": True, "models": [m["name"] for m in r.json()["models"]]}

    return await _probe("ollama", check(), {"ok": False, "models": []})


async def infinity_health(http: httpx.AsyncClient) -> dict:
    async def check() -> dict:
        (await http.get(f"{settings.INFINITY_URL}/health")).raise_for_status()
        r = await http.get(f"{settings.INFINITY_URL}/models")
        r.raise_for_status()
        return {"ok": True, "models": [m["id"] for m in r.json()["data"]]}

    return await _probe("infinity", check(), {"ok": False, "models": []})


async def chroma_health(http: httpx.AsyncClient) -> dict:
    # /api/v2/version is the API version ("1.0.0" on server 1.5.9), not the
    # release, so the two are reported side by side but never compared; the
    # skew guard is the matching pins in docker-compose.yml and requirements.txt.
    client_version = chroma_client_version()

    async def check() -> dict:
        (await http.get(f"{settings.chroma_url}/api/v2/heartbeat")).raise_for_status()
        r = await http.get(f"{settings.chroma_url}/api/v2/version")
        r.raise_for_status()
        return {
            "ok": True,
            "server_version": str(r.json()),
            "client_version": client_version,
        }

    return await _probe(
        "chroma",
        check(),
        {"ok": False, "server_version": None, "client_version": client_version},
    )
