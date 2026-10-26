"""In-process locks (design-rag.md §4.5.7). The backend runs as one process.

- ``INGESTION_LOCK`` is held for one whole ingestion job, so jobs queue FIFO
  and never embed or write Chroma concurrently.
- ``GENERATION_LOCK`` is held only around one Ollama call (live and compare),
  so generations never overlap; embedding and retrieval take no app lock.
- ``JOB_CREATE_LOCK`` is held from "is a job active for this profile or
  resource?" through the insert or delete and its commit, so two requests
  can't both pass the check (one QUEUED/RUNNING job per profile, §4.5.5).
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

GENERATION_LOCK = asyncio.Semaphore(1)
INGESTION_LOCK = asyncio.Semaphore(1)
JOB_CREATE_LOCK = asyncio.Lock()


@asynccontextmanager
async def acquire(lock: asyncio.Semaphore, timeout: float) -> AsyncIterator[None]:
    """Hold `lock`, waiting at most `timeout` seconds (asyncio.TimeoutError)."""
    await asyncio.wait_for(lock.acquire(), timeout)
    try:
        yield
    finally:
        lock.release()
