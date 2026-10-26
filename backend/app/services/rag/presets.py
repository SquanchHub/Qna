"""Ingestion presets (design-rag.md §4.4.1). A profile copies one at creation
and never changes; sizes are chunk tokens (tokens.py)."""

from __future__ import annotations

import copy

MINILM = "sentence-transformers/all-MiniLM-L6-v2"
GTE_QWEN = "Alibaba-NLP/gte-Qwen2-1.5B-instruct"
BGE_SMALL = "BAAI/bge-small-en-v1.5"

# Model input limits in tokens, [CLS]/[SEP] included; gte's is our cap
MAX_INPUT_TOKENS = {MINILM: 256, BGE_SMALL: 512, GTE_QWEN: 8192}

CHUNK_TYPES = ("syllabus", "schedule", "repo_markdown", "repo_pdf")
SEMANTIC_TYPES = ("syllabus", "schedule")
RESET_FOR_TYPE = {"page": "repo_pdf", "subheading": "repo_markdown"}
CHUNKING_KEYS = {"token_unit", "heading_prefix_max_tokens", "default", "per_type"}
WINDOW_KEYS = {"chunk_size", "chunk_overlap"}
FALLBACK_KEYS = {
    "sliding_window": {"method", "reset_at", *WINDOW_KEYS},
    "semantic": {"method", "similarity_threshold", "max_tokens", "oversize_window"},
}

# [CLS] + [SEP] + whole-word expansion slack (chunking.EXPANSION_SLACK)
BUDGET_RESERVE = 4
# A Q&A pair longer than this is windowed; fixed for every profile
QA_MAX_TOKENS = 222

_BASE_WINDOW = {"method": "sliding_window", "chunk_size": 200, "chunk_overlap": 40}


def _chunking(per_type: dict) -> dict:
    return {
        "token_unit": "minilm-wordpiece",
        "heading_prefix_max_tokens": 30,
        "default": dict(_BASE_WINDOW),
        "per_type": per_type,
    }


def _semantic() -> dict:
    return {
        "method": "semantic",
        "similarity_threshold": 0.60,
        "max_tokens": 220,
        "oversize_window": {"chunk_size": 200, "chunk_overlap": 40},
    }


PRESETS: dict[str, dict] = {
    "sliding-window": {
        "embedding_model": MINILM,
        "query_instruction": "",
        "chunking": _chunking({}),
    },
    "type-tailored": {
        "embedding_model": MINILM,
        "query_instruction": "",
        "chunking": _chunking(
            {
                "repo_pdf": {
                    "method": "sliding_window",
                    "chunk_size": 120,
                    "chunk_overlap": 30,
                    "reset_at": "page",
                },
                "repo_markdown": {
                    "method": "sliding_window",
                    "chunk_size": 150,
                    "chunk_overlap": 30,
                    "reset_at": "subheading",
                },
                "syllabus": _semantic(),
                "schedule": _semantic(),
            }
        ),
    },
    "embedding-alt": {
        "embedding_model": GTE_QWEN,
        "query_instruction": (
            "Instruct: Given a student's question about a course, retrieve "
            "course material passages that answer it\nQuery: "
        ),
        "chunking": _chunking({}),
    },
    "bge-small": {
        "embedding_model": BGE_SMALL,
        "query_instruction": (
            "Represent this sentence for searching relevant passages: "
        ),
        "chunking": _chunking({}),
    },
}


def get_preset(name: str) -> dict:
    """A deep copy, so a caller can't change the code-defined preset."""
    return {"preset": name, **copy.deepcopy(PRESETS[name])}


def fallback_for(chunking: dict, chunk_type: str) -> dict:
    """The fallback chunker config for a chunk type, `reset_at` filled in."""
    cfg = dict(chunking["per_type"].get(chunk_type) or chunking["default"])
    if cfg["method"] == "sliding_window":
        cfg.setdefault("reset_at", "none")
    return cfg


def _check_keys(cfg: dict, allowed: set[str], where: str) -> None:
    unknown = set(cfg) - allowed
    if unknown:
        raise ValueError(f"{where}: unknown keys {sorted(unknown)}")


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_window(cfg: dict, where: str) -> list[int]:
    size, overlap = cfg.get("chunk_size"), cfg.get("chunk_overlap")
    if not _is_int(size) or not _is_int(overlap):
        raise ValueError(f"{where}: chunk_size and chunk_overlap must be ints")
    if not 0 <= overlap < size:
        raise ValueError(f"{where}: need 0 <= chunk_overlap < chunk_size")
    return [size]


def _check_fallback(cfg: dict, chunk_type: str | None) -> list[int]:
    where = chunk_type or "default"
    if not isinstance(cfg, dict):
        raise ValueError(f"{where}: must be an object")
    method = cfg.get("method")
    _check_keys(cfg, FALLBACK_KEYS.get(method, {"method"}), where)
    if method == "sliding_window":
        sizes = _check_window(cfg, where)
        reset = cfg.get("reset_at", "none")
        if reset != "none" and RESET_FOR_TYPE.get(reset) != chunk_type:
            raise ValueError(f"{where}: reset_at {reset!r} not allowed here")
        return sizes
    if method == "semantic":
        if chunk_type not in SEMANTIC_TYPES:
            raise ValueError(f"{where}: semantic is only for syllabus and schedule")
        threshold = cfg.get("similarity_threshold")
        if not isinstance(threshold, (int, float)) or not 0 < threshold < 1:
            raise ValueError(f"{where}: similarity_threshold must be in (0, 1)")
        max_tokens = cfg.get("max_tokens")
        if not _is_int(max_tokens) or max_tokens < 1:
            raise ValueError(f"{where}: max_tokens must be a positive int")
        window = cfg.get("oversize_window")
        if not isinstance(window, dict):
            raise ValueError(f"{where}: semantic needs oversize_window")
        _check_keys(window, WINDOW_KEYS, f"{where}.oversize_window")
        return [max_tokens, *_check_window(window, f"{where}.oversize_window")]
    raise ValueError(f"{where}: unknown method {method!r}")


def validate_chunking(chunking: dict, model: str) -> None:
    """Raise ValueError unless `chunking` is a valid §4.4.1 config for `model`."""
    if model not in MAX_INPUT_TOKENS:
        raise ValueError(f"unknown embedding model {model!r}")
    _check_keys(chunking, CHUNKING_KEYS, "chunking")
    if chunking.get("token_unit") != "minilm-wordpiece":
        raise ValueError("token_unit must be 'minilm-wordpiece'")
    prefix = chunking.get("heading_prefix_max_tokens")
    if not _is_int(prefix) or prefix < 1:
        raise ValueError("heading_prefix_max_tokens must be a positive int")
    per_type = chunking.get("per_type")
    if not isinstance(per_type, dict) or not isinstance(chunking.get("default"), dict):
        raise ValueError("default and per_type are required")
    unknown = set(per_type) - set(CHUNK_TYPES)
    if unknown:
        raise ValueError(f"unknown per_type keys {sorted(unknown)}")

    # `default` also covers markdown, PDF and Q&A, so it is a plain window
    default = chunking["default"]
    if (
        default.get("method") != "sliding_window"
        or default.get("reset_at", "none") != "none"
    ):
        raise ValueError("default: must be sliding_window with no reset_at")
    sizes = _check_fallback(default, None)
    for chunk_type, cfg in per_type.items():
        sizes += _check_fallback(cfg, chunk_type)
    limit = MAX_INPUT_TOKENS[model]
    # A whole Q&A pair (no prefix) fits in the smallest limit, 256
    for size in sizes:
        if size + prefix + BUDGET_RESERVE > limit:
            raise ValueError(
                f"size {size} + prefix {prefix} + {BUDGET_RESERVE} exceeds "
                f"{limit} tokens for {model}"
            )
