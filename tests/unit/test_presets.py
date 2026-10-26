"""Presets and chunking validation (design-rag.md §4.4.1, §10)."""

import copy

import pytest

from app.services.rag.presets import (
    MINILM,
    PRESETS,
    fallback_for,
    get_preset,
    validate_chunking,
)


@pytest.mark.parametrize("name", sorted(PRESETS))
def test_every_preset_validates_against_its_model(name):
    preset = PRESETS[name]
    validate_chunking(preset["chunking"], preset["embedding_model"])


def test_query_instruction_is_always_a_string():
    assert all(isinstance(p["query_instruction"], str) for p in PRESETS.values())


def _baseline():
    return copy.deepcopy(PRESETS["sliding-window"]["chunking"])


def test_chunk_size_240_with_minilm_fails():
    chunking = _baseline()
    chunking["default"]["chunk_size"] = 240
    with pytest.raises(ValueError, match="exceeds 256"):
        validate_chunking(chunking, MINILM)


def test_chunk_size_240_fits_bge():
    chunking = _baseline()
    chunking["default"]["chunk_size"] = 240
    validate_chunking(chunking, "BAAI/bge-small-en-v1.5")


def test_semantic_on_pdf_fails():
    chunking = copy.deepcopy(PRESETS["type-tailored"]["chunking"])
    chunking["per_type"]["repo_pdf"] = chunking["per_type"]["syllabus"]
    with pytest.raises(ValueError, match="semantic"):
        validate_chunking(chunking, MINILM)


def test_oversized_semantic_cap_fails():
    chunking = copy.deepcopy(PRESETS["type-tailored"]["chunking"])
    chunking["per_type"]["syllabus"]["max_tokens"] = 223
    with pytest.raises(ValueError, match="exceeds"):
        validate_chunking(chunking, MINILM)


@pytest.mark.parametrize("overlap", [200, 250, -1])
def test_bad_overlap_fails(overlap):
    chunking = _baseline()
    chunking["default"]["chunk_overlap"] = overlap
    with pytest.raises(ValueError, match="chunk_overlap"):
        validate_chunking(chunking, MINILM)


def test_page_reset_on_markdown_fails():
    chunking = _baseline()
    chunking["per_type"]["repo_markdown"] = {
        "method": "sliding_window",
        "chunk_size": 150,
        "chunk_overlap": 30,
        "reset_at": "page",
    }
    with pytest.raises(ValueError, match="reset_at"):
        validate_chunking(chunking, MINILM)


def test_unknown_type_and_model_fail():
    chunking = _baseline()
    chunking["per_type"]["historical_qa"] = chunking["default"]
    with pytest.raises(ValueError, match="per_type"):
        validate_chunking(chunking, MINILM)
    with pytest.raises(ValueError, match="unknown embedding model"):
        validate_chunking(_baseline(), "nonexistent/model")


def test_sliding_window_profiles_share_one_chunking():
    configs = [
        PRESETS[n]["chunking"] for n in ("sliding-window", "embedding-alt", "bge-small")
    ]
    assert configs[0] == configs[1] == configs[2]


def test_fallback_for_defaults():
    baseline = PRESETS["sliding-window"]["chunking"]
    assert fallback_for(baseline, "repo_pdf") == {
        "method": "sliding_window",
        "chunk_size": 200,
        "chunk_overlap": 40,
        "reset_at": "none",
    }
    tailored = PRESETS["type-tailored"]["chunking"]
    assert fallback_for(tailored, "repo_pdf")["reset_at"] == "page"
    assert fallback_for(tailored, "schedule")["method"] == "semantic"


def test_get_preset_is_a_copy():
    preset = get_preset("sliding-window")
    preset["chunking"]["default"]["chunk_size"] = 1
    assert PRESETS["sliding-window"]["chunking"]["default"]["chunk_size"] == 200
    assert preset["preset"] == "sliding-window"


def test_default_must_be_a_plain_window():
    chunking = _baseline()
    chunking["default"]["reset_at"] = "page"
    with pytest.raises(ValueError, match="default"):
        validate_chunking(chunking, MINILM)
    chunking = copy.deepcopy(PRESETS["type-tailored"]["chunking"])
    chunking["default"] = chunking["per_type"]["syllabus"]
    with pytest.raises(ValueError, match="default"):
        validate_chunking(chunking, MINILM)


def test_unknown_keys_and_non_int_sizes_fail():
    chunking = _baseline()
    chunking["default"]["chunk_sise"] = 100
    with pytest.raises(ValueError, match="unknown keys"):
        validate_chunking(chunking, MINILM)
    chunking = _baseline()
    chunking["extra"] = 1
    with pytest.raises(ValueError, match="unknown keys"):
        validate_chunking(chunking, MINILM)
    for bad in (200.0, True, "200"):
        chunking = _baseline()
        chunking["default"]["chunk_size"] = bad
        with pytest.raises(ValueError, match="ints"):
            validate_chunking(chunking, MINILM)


def test_non_object_per_type_entry_fails():
    chunking = _baseline()
    chunking["per_type"]["syllabus"] = None
    with pytest.raises(ValueError, match="object"):
        validate_chunking(chunking, MINILM)
