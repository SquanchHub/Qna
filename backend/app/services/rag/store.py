"""ChromaDB access for ingestion: one collection per profile (design-rag.md §4.1.2).

Collections are created with ``embedding_function=None``: we always pass our
own vectors, and the client's default would try to download an ONNX model.
"""

from __future__ import annotations

import chromadb
from chromadb.config import Settings as ChromaSettings
from chromadb.errors import NotFoundError

from ...config import settings


async def open_client():
    return await chromadb.AsyncHttpClient(
        host=settings.CHROMA_HOST,
        port=settings.CHROMA_PORT,
        settings=ChromaSettings(anonymized_telemetry=False),
    )


async def collection(client, profile):
    return await client.get_or_create_collection(
        name=profile.collection_name,
        configuration={"hnsw": {"space": "cosine"}},
        metadata={"embedding_model": profile.embedding_model, "profile_id": profile.id},
        embedding_function=None,
    )


async def existing_collection(client, name: str):
    try:
        return await client.get_collection(name=name, embedding_function=None)
    except (NotFoundError, ValueError):
        return None


async def drop_collection(client, name: str) -> None:
    try:
        await client.delete_collection(name=name)
    except (NotFoundError, ValueError):
        pass


async def delete_resource_chunks(client, profiles, resource_id: int) -> dict[int, int]:
    """Delete one resource's chunks from every profile's collection; returns
    each profile's new count (0 when it has no collection yet)."""
    counts = {}
    for profile in profiles:
        coll = await existing_collection(client, profile.collection_name)
        if coll is None:
            counts[profile.id] = 0
            continue
        await coll.delete(where={"resource_id": resource_id})
        counts[profile.id] = await coll.count()
    return counts
