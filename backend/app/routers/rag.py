import asyncio
from collections.abc import AsyncIterator
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends

from ..common.dependencies import require_rag_viewer
from ..config import settings
from ..models.user import User
from ..services.rag import clients

router = APIRouter(tags=["rag"])


async def get_rag_http() -> AsyncIterator[httpx.AsyncClient]:
    """One client per request, so it is never bound to another event loop."""
    async with httpx.AsyncClient(timeout=clients.HEALTH_TIMEOUT_S) as http:
        yield http


@router.get("/rag/health")
async def rag_health(
    _: Annotated[User, Depends(require_rag_viewer)],
    http: Annotated[httpx.AsyncClient, Depends(get_rag_http)],
) -> dict:
    """Service status for ADMIN or staff of any course; never 5xx (design §6)."""
    ollama, infinity, chroma = await asyncio.gather(
        clients.ollama_health(http),
        clients.infinity_health(http),
        clients.chroma_health(http),
    )
    return {
        "ollama": ollama,
        "infinity": infinity,
        "chroma": chroma,
        "gitlab_token_configured": bool(settings.GITLAB_TOKEN),
        "live_enabled": settings.RAG_LIVE_ENABLED,
        "defaults": {
            "profile": settings.RAG_DEFAULT_PROFILE,
            "threshold": settings.RAG_DEFAULT_THRESHOLD,
            "model": settings.RAG_DEFAULT_MODEL,
        },
    }
