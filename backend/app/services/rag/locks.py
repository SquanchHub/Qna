"""In-process locks (design-rag.md §4.5.7). The backend runs as one process.

- ``INGESTION_LOCK`` is held for one whole ingestion job, so jobs queue FIFO
  and never embed or write Chroma concurrently.
- ``JOB_CREATE_LOCK`` is held from "is a job active for this profile or
  resource?" through the insert or delete and its commit, so two requests
  can't both pass the check (one QUEUED/RUNNING job per profile, §4.5.5).
"""

import asyncio

INGESTION_LOCK = asyncio.Semaphore(1)
JOB_CREATE_LOCK = asyncio.Lock()
