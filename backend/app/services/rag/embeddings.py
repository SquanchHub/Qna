"""Document embeddings from Infinity (design-rag.md §4.3.1, §4.5.6)."""

from __future__ import annotations

import asyncio

import httpx

from ...config import settings
from . import clients


async def embed(model: str, texts: list[str]) -> list[list[float]]:
    """One vector per text, in order. Documents are embedded without the
    profile's query_instruction, which applies to queries only."""
    timeout = settings.RAG_INGEST_EMBED_TIMEOUT_S

    async def call() -> list[dict]:
        async with httpx.AsyncClient(timeout=timeout) as http:
            r = await http.post(
                f"{settings.INFINITY_URL}/embeddings",
                json={"model": model, "input": texts},
            )
            r.raise_for_status()
            return r.json()["data"]

    data = await asyncio.wait_for(call(), timeout)
    if len(data) != len(texts):
        raise ValueError(
            f"Infinity returned {len(data)} vectors for {len(texts)} texts"
        )
    return [d["embedding"] for d in sorted(data, key=lambda d: d["index"])]


async def served_models() -> set[str] | None:
    """Model ids Infinity serves now, or None when it can't be reached."""
    async with httpx.AsyncClient(timeout=clients.HEALTH_TIMEOUT_S) as http:
        health = await clients.infinity_health(http)
    return set(health["models"]) if health["ok"] else None
