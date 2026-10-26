"""docker-compose.prod.yml carries the RAG stack (design-rag.md §4.3.1, §4.3.3).

Structural checks only: the VM run is the real test. They keep prod's pinned
images and health checks in step with docker-compose.yml, and hold the
memory budget for the 16 GB e2-standard-4.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[2]
RAG = ("ollama", "ollama-pull", "infinity", "chroma")
MODEL_SERVERS = ("ollama", "infinity", "chroma")
GIB = 1024**3


def load(name: str) -> dict:
    return yaml.safe_load((ROOT / name).read_text())["services"]


PROD = load("docker-compose.prod.yml")
DEV = load("docker-compose.yml")


def gib(limit) -> float:
    """Compose's byte forms: an int, or a number with b/k/m/g, optionally +b."""
    if isinstance(limit, int):
        return limit / GIB
    m = re.fullmatch(r"(\d+)([bkmg])b?", str(limit).lower())
    assert m, limit
    units = {"b": 1, "k": 1024, "m": 1024**2, "g": GIB}
    return int(m[1]) * units[m[2]] / GIB


@pytest.mark.parametrize("name", RAG)
def test_rag_service_matches_dev(name):
    prod, dev = PROD[name], DEV[name]
    assert prod["image"] == dev["image"]
    keys = (
        "command",
        "entrypoint",
        "platform",
        "environment",
        "volumes",
        "healthcheck",
        "depends_on",
    )
    for key in keys:
        assert prod.get(key) == dev.get(key), key


@pytest.mark.parametrize("name", RAG)
def test_model_containers_get_no_secrets(name):
    assert "env_file" not in PROD[name]


def test_only_nginx_publishes_ports():
    assert [n for n, s in PROD.items() if "ports" in s] == ["nginx"]


def test_memory_limits_fit_the_vm():
    limits = {n: gib(s["mem_limit"]) for n, s in PROD.items() if "mem_limit" in s}
    assert limits["infinity"] == 9
    assert limits["ollama"] == 4
    # A limit added anywhere else must still leave about 2 GB of the 16 for
    # the unlimited services and the host
    assert sum(limits.values()) <= 14


def test_gib_parses_compose_forms():
    assert gib("9g") == gib("9gb") == gib(9 * GIB) == 9
    assert gib("512m") == 0.5


def test_restart_policies():
    for name in MODEL_SERVERS:
        assert PROD[name]["restart"] == "unless-stopped"
    assert PROD["ollama-pull"]["restart"] == "no"


def test_backend_waits_for_rag_and_keeps_uploads():
    backend = PROD["backend"]
    for name in MODEL_SERVERS:
        assert backend["depends_on"][name] == {"condition": "service_started"}
    assert "uploads_data:/data/uploads" in backend["volumes"]


def test_volumes_are_declared():
    declared = yaml.safe_load((ROOT / "docker-compose.prod.yml").read_text())["volumes"]
    for name in ("ollama_models", "infinity_cache", "chroma_data", "uploads_data"):
        assert name in declared
