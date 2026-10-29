"""Tokenizer and chunkers on synthetic text and on eval/sample_data
(design-rag.md §4.5.4, §10). Embeddings are stubbed."""

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest

from app.services.rag.chunking import (
    Chunk,
    _split_unit,
    chunk_html,
    chunk_markdown,
    chunk_pdf,
    chunk_qa,
    heading_prefix,
    html_sections,
    pdf_pages,
    qa_answer,
    semantic,
    window,
)
from app.services.rag.citations import assign_ids
from app.services.rag.presets import (
    MAX_INPUT_TOKENS,
    PRESETS,
    fallback_for,
)
from app.services.rag.tokens import count_tokens, tokenize

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / "eval" / "sample_data"
BASELINE = PRESETS["sliding-window"]["chunking"]
TAILORED = PRESETS["type-tailored"]["chunking"]


def _norm(text: str) -> str:
    return " ".join(text.split())


def _window_cfg(size, overlap, reset="none"):
    return {
        "method": "sliding_window",
        "chunk_size": size,
        "chunk_overlap": overlap,
        "reset_at": reset,
    }


def _chunking(per_type=None, size=200, overlap=40):
    return {
        "token_unit": "minilm-wordpiece",
        "heading_prefix_max_tokens": 30,
        "default": {
            "method": "sliding_window",
            "chunk_size": size,
            "chunk_overlap": overlap,
        },
        "per_type": per_type or {},
    }


def _words(n, stem="word"):
    return " ".join(f"{stem}{i}" for i in range(n))


# Tokenizer


def test_tokenizer_is_not_truncated_to_128():
    assert count_tokens(" ".join(["policy"] * 1000)) == 1000


def test_offsets_slice_the_original_text():
    text = "Late Policy — Café naïve P1–P4 😀"
    pieces = [text[t.start : t.end] for t in tokenize(text)]
    assert pieces[:5] == ["Late", "Policy", "—", "Café", "naïve"]
    assert "😀" in pieces


def test_special_tokens_are_not_counted():
    assert count_tokens("hello") == 1
    assert count_tokens("") == 0


# window and whole-word expansion


def test_window_fits_in_one():
    assert window(5, 5, 1) == [(0, 5)]
    assert window(0, 5, 1) == [(0, 0)]


def test_window_starts_and_last_reaches_end():
    assert window(10, 4, 1) == [(0, 4), (3, 7), (6, 10)]
    assert window(11, 4, 1) == [(0, 4), (3, 7), (6, 10), (9, 11)]
    assert window(10, 4, 0) == [(0, 4), (4, 8), (8, 10)]


def test_windows_never_split_a_spaced_word():
    text = " ".join(["internationalization", "parallax", "deterministic"] * 40)
    words = set(text.split())
    for a, b in _split_unit(text, _window_cfg(25, 5)):
        assert set(text[a:b].split()) <= words
        assert count_tokens(text[a:b]) <= 25 + 2


def test_unspaced_run_falls_back_to_token_boundaries():
    text = "start " + "x1y2z3" * 60 + " end"
    for a, b in _split_unit(text, _window_cfg(20, 4)):
        assert count_tokens(text[a:b]) <= 20 + 2


def test_zero_overlap_windows_cover_every_character():
    text = _words(300)
    spans = _split_unit(text, _window_cfg(37, 0))
    covered = set()
    for a, b in spans:
        covered.update(range(a, b))
    assert all(i in covered for i, c in enumerate(text) if not c.isspace())


def test_heading_prefix_drops_leading_components():
    prefix = heading_prefix(["instructions.md", "Project 2", _words(20, "t")], 30)
    assert count_tokens(prefix) <= 30
    assert not prefix.startswith("instructions.md")
    assert heading_prefix(["a.md", "Intro"]) == "a.md > Intro"
    assert heading_prefix(["", "  ", "Only"]) == "Only"


def test_heading_prefix_cuts_one_long_component_at_a_word():
    long = _words(40, "heading")
    prefix = heading_prefix([long], 30)
    assert 0 < count_tokens(prefix) <= 30
    assert long.startswith(prefix)
    assert long[len(prefix)] == " "


# Markdown (synthetic)


def _md(text, chunking=None):
    return chunk_markdown(text, "f.md", chunking or _chunking())


def _check_lines(source, chunk):
    lines = source.splitlines()
    span = "\n".join(lines[chunk.line_start - 1 : chunk.line_end])
    assert chunk.text in span
    # The range is tight: the text starts on its first line and ends on its last
    text_lines = chunk.text.split("\n")
    first, last = lines[chunk.line_start - 1], lines[chunk.line_end - 1]
    if len(text_lines) == 1:
        assert chunk.line_start == chunk.line_end
        at = first.index(chunk.text)
        before, after = first[:at], first[at + len(chunk.text) :]
    else:
        assert first.rstrip().endswith(text_lines[0])
        assert last.lstrip().startswith(text_lines[-1])
        before = first.rstrip()[: -len(text_lines[0])]
        after = last.lstrip()[len(text_lines[-1]) :]
    # Whole words: the chunk never starts or ends inside a word
    assert before == "" or before[-1].isspace()
    assert after == "" or after[0].isspace()


def test_fenced_hash_lines_are_content():
    text = "# Top\nintro\n```bash\n# not a heading\nrun\n```\nafter\n"
    chunks = _md(text)
    assert len(chunks) == 1
    assert chunks[0].prefix == "f.md > Top"
    assert "# not a heading" in chunks[0].text and "```" in chunks[0].text
    assert (chunks[0].line_start, chunks[0].line_end) == (2, 7)


def test_tilde_fence_and_unclosed_fence():
    text = (
        "# A\n~~~\n# inside\n~~~\n## B\nb text\n```\n# never closed\n## still fenced\n"
    )
    chunks = _md(text)
    assert [c.prefix for c in chunks] == ["f.md > A", "f.md > A > B"]
    assert "## still fenced" in chunks[1].text


def test_heading_levels_reset_deeper_ones():
    text = "# A\n## B\n### C\nc\n## D\nd\n# E\ne\n"
    assert [c.prefix for c in _md(text)] == [
        "f.md > A > B > C",
        "f.md > A > D",
        "f.md > E",
    ]


def test_text_before_first_heading_is_a_section():
    chunks = _md("preamble line\n\n# A\nbody\n")
    assert chunks[0].prefix == "f.md"
    assert (chunks[0].line_start, chunks[0].line_end) == (1, 1)
    assert (chunks[1].line_start, chunks[1].line_end) == (4, 4)


def test_heading_only_section_is_dropped():
    assert [c.prefix for c in _md("# A\n\n## B\nbody\n")] == ["f.md > A > B"]


def test_windowed_line_ranges_are_exact():
    body = "\n".join(f"line {i} " + _words(7, f"w{i}x") for i in range(60))
    text = f"# Big\n{body}\n"
    chunks = _md(text, _chunking(size=40, overlap=10))
    assert len(chunks) > 3
    for chunk in chunks:
        _check_lines(text, chunk)
    assert chunks[0].line_start == 2
    assert chunks[-1].line_end == 61


def _subheading_doc():
    parts = ["# Tasks"]
    for i in range(4):
        parts.append(f"#### Sub {i}")
        parts.extend(f"sub{i} " + _words(8, f"s{i}y") for _ in range(3))
    return "\n".join(parts) + "\n"


def test_subheading_reset_starts_segments_at_h4():
    text = _subheading_doc()
    cfg = _chunking({"repo_markdown": _window_cfg(150, 10, "subheading")})
    chunks = _md(text, cfg)
    assert [c.text.splitlines()[0] for c in chunks] == [
        f"#### Sub {i}" for i in range(4)
    ]
    for chunk in chunks:
        _check_lines(text, chunk)


def test_subheading_reset_only_when_section_is_oversized():
    cfg = _chunking({"repo_markdown": _window_cfg(1000, 10, "subheading")})
    assert len(_md(_subheading_doc(), cfg)) == 1


# Markdown (real)


def _md_files():
    return sorted((SAMPLE / "repo").rglob("*.md"))


def test_realtime_fenced_comments_stay_in_seeing_it_live():
    text = (SAMPLE / "repo/p2-buzzer/docs/realtime.md").read_text()
    chunks = chunk_markdown(text, "realtime.md", BASELINE)
    live = [c for c in chunks if c.prefix.endswith("Seeing it live")]
    assert any("# Scripted end-to-end game" in c.text for c in live)
    assert not any("Scripted" in c.prefix for c in chunks)


@pytest.mark.parametrize("chunking", [BASELINE, TAILORED], ids=["baseline", "tailored"])
def test_every_sample_markdown_line_range_is_exact(chunking):
    for path in _md_files():
        text = path.read_text()
        for chunk in chunk_markdown(text, path.name, chunking):
            _check_lines(text, chunk)


# HTML


def _html(name):
    return (SAMPLE / "web" / f"{name}.html").read_text()


@pytest.mark.parametrize("name", ["syllabus", "schedule"])
def test_html_chrome_is_removed(name):
    text = "\n".join("\n".join(lines) for _, lines in html_sections(_html(name)))
    assert "opens in new tab" not in text
    assert "Toggle navigation" not in text
    assert "\xa0" not in text
    assert not re.search(r"\s{2,}", text.replace("\n", " "))


@pytest.mark.parametrize("name", ["syllabus", "schedule"])
def test_one_section_per_h1_to_h3(name):
    html = _html(name)
    sections = html_sections(html)
    headings = re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>", html, re.S)
    # Every section ends with its own heading; heading-only ones are dropped
    assert len(sections) <= len(headings)
    assert len({tuple(path) for path, _ in sections}) == len(sections)
    if name == "syllabus":
        # "Syllabus" (h1) and "Official Statements…" (h2) have no text of their own
        assert len(sections) == len(headings) - 2 == 20


def test_heading_inline_markup_joins_without_spaces():
    paths = [path for path, _ in html_sections(_html("schedule"))]
    assert [
        "Course Schedule",
        "Week 7",
        "Thu: Lecture 13 — Orchestrating Local RAG with Ollama (Oct 15)",
    ] in paths


def test_syllabus_late_policy_is_one_display_line():
    lines = [line for _, ls in html_sections(_html("syllabus")) for line in ls]
    assert "Late Policy — Slip Days:" in lines
    assert any(
        line.startswith("Each student has a bank of 5 slip days") for line in lines
    )


def test_schedule_prefix_is_truncated_and_keeps_the_day():
    chunks = asyncio.run(chunk_html(_html("schedule"), "schedule", BASELINE))
    for chunk in chunks:
        assert count_tokens(chunk.prefix) <= 30
    long_day = [c for c in chunks if "Lecture 27" in c.prefix]
    assert long_day and long_day[0].prefix.endswith("(Dec 08)")


def test_semantic_without_embedder_raises():
    with pytest.raises(ValueError, match="embedder"):
        asyncio.run(chunk_html(_html("syllabus"), "syllabus", TAILORED))


# Semantic


def _topic_stub(topics):
    async def embed(sentences):
        assert len(sentences) == len(topics)
        return [[1.0, 0.0] if t == 0 else [0.0, 1.0] for t in topics]

    return embed


def _semantic_cfg(max_tokens, size=20, overlap=5):
    return {
        "method": "semantic",
        "similarity_threshold": 0.6,
        "max_tokens": max_tokens,
        "oversize_window": {"chunk_size": size, "chunk_overlap": overlap},
    }


def test_semantic_splits_at_similarity_drops():
    sentences = [f"Sentence {i} talks about {_words(3, 'topic')}." for i in range(6)]
    text = " ".join(sentences[:3]) + "\n" + " ".join(sentences[3:])
    spans = asyncio.run(
        semantic(text, _semantic_cfg(60), _topic_stub([0, 0, 1, 1, 1, 0]))
    )
    assert [text[a:b] for a, b in spans] == [
        " ".join(sentences[:2]),
        sentences[2] + "\n" + " ".join(sentences[3:5]),
        sentences[5],
    ]


def test_oversized_semantic_span_is_windowed_not_truncated():
    sentences = [f"Fact {i} {_words(6, 'detail')}." for i in range(12)]
    text = " ".join(sentences)
    spans = asyncio.run(semantic(text, _semantic_cfg(40), _topic_stub([0] * 12)))
    assert len(spans) > 1
    covered = set()
    for a, b in spans:
        assert count_tokens(text[a:b]) <= 20 + 2
        covered.update(range(a, b))
    assert all(i in covered for i, c in enumerate(text) if not c.isspace())


def test_semantic_unit_within_cap_skips_embedding():
    async def never(_):
        raise AssertionError("should not embed")

    assert asyncio.run(semantic("Short. Text.", _semantic_cfg(30), never)) == [(0, 12)]


# PDF


@pytest.fixture(scope="module")
def slides():
    return pdf_pages((SAMPLE / "repo/lecture-10/slides.pdf").read_bytes())


def test_pdf_has_19_pages(slides):
    assert len(slides) == 19


def test_page_reset_never_crosses_pages(slides):
    chunks = chunk_pdf(slides, "slides.pdf", TAILORED)
    assert {c.page_start for c in chunks} == set(range(1, 20))
    assert all(c.page_start == c.page_end for c in chunks)
    # Only slides longer than the 120-token window are split, within the page
    per_page = {n: sum(c.page_start == n for c in chunks) for n in range(1, 20)}
    assert {n for n, k in per_page.items() if k > 1} == {7, 17, 18}
    temperature = [c for c in chunks if c.page_start == 14]
    assert temperature[0].prefix == "slides.pdf p.14 > Temperature and Sampling"
    assert temperature[0].title == "slides.pdf p.14"


def test_streamed_pages_are_monotonic(slides):
    chunks = chunk_pdf(slides, "slides.pdf", BASELINE)
    starts = [c.page_start for c in chunks]
    assert starts == sorted(starts) and starts[0] == 1
    assert any(c.page_end > c.page_start for c in chunks)
    assert chunks[-1].page_end == 19


def test_pdf_page_tracking_on_synthetic_pages():
    pages = [_words(30, "alpha"), "", _words(30, "gamma")]
    chunks = chunk_pdf(
        pages, "x.pdf", _chunking({"repo_pdf": _window_cfg(20, 5, "page")})
    )
    assert {c.page_start for c in chunks} == {1, 3}
    assert all(("alpha" in c.text) != ("gamma" in c.text) for c in chunks)


# Historical Q&A


@dataclass
class _Post:
    id: int
    kind: str
    author_role: str
    is_accepted: bool = False
    created_at: datetime = datetime(2026, 10, 1)


@dataclass
class _Question:
    status: str


def test_qa_answer_selection():
    student = _Post(1, "ANSWER", "STUDENT", is_accepted=True)
    ai = _Post(2, "ANSWER", "AI", is_accepted=True)
    staff_old = _Post(3, "ANSWER", "STAFF", created_at=datetime(2026, 10, 1))
    staff_new = _Post(4, "ANSWER", "STAFF", created_at=datetime(2026, 10, 2))
    followup = _Post(5, "FOLLOWUP", "STAFF", created_at=datetime(2026, 10, 3))
    unaccepted = _Post(6, "ANSWER", "STUDENT")

    assert qa_answer(_Question("OPEN"), [ai, student]) is student
    assert qa_answer(_Question("OPEN"), [ai]) is None
    assert (
        qa_answer(_Question("CLOSED"), [ai, staff_old, staff_new, followup])
        is staff_new
    )
    assert qa_answer(_Question("CLOSED"), [unaccepted, followup]) is None
    assert qa_answer(_Question("OPEN"), [staff_new, unaccepted]) is None


def _pair_of(n_tokens):
    """A body that makes the whole pair exactly n_tokens long."""
    body_tokens = n_tokens - count_tokens("Question: T\n\n\nAnswer: done")
    return " ".join(["policy"] * body_tokens)


def test_qa_pair_is_one_chunk():
    body = _pair_of(200)
    chunks = chunk_qa(7, "T", body, "done")
    assert len(chunks) == 1
    assert chunks[0].prefix == "" and chunks[0].text.startswith("Question: T\n")
    assert chunks[0].question_id == 7


def test_long_qa_pair_is_never_split():
    # T4: historical Q&A pairs are atomic, however long
    body = _pair_of(5000)
    chunks = chunk_qa(7, "T", body, "done")
    assert len(chunks) == 1
    assert chunks[0].prefix == ""
    assert chunks[0].text == f"Question: T\n{body}\n\nAnswer: done"
    assert count_tokens(chunks[0].text) == 5000


# Every sample file under every preset


async def _stub_embed(sentences):
    # A topic shift every fourth sentence
    return [
        [1.0, 0.0] if (i // 4) % 2 == 0 else [0.0, 1.0] for i in range(len(sentences))
    ]


def _all_chunks(chunking):
    files = {}
    for path in _md_files():
        files[str(path.relative_to(REPO))] = chunk_markdown(
            path.read_text(), path.name, chunking
        )
    for name in ("syllabus", "schedule"):
        files[f"eval/sample_data/web/{name}.html"] = asyncio.run(
            chunk_html(_html(name), name, chunking, _stub_embed)
        )
    pdf = SAMPLE / "repo/lecture-10/slides.pdf"
    files["eval/sample_data/repo/lecture-10/slides.pdf"] = chunk_pdf(
        pdf_pages(pdf.read_bytes()), pdf.name, chunking
    )
    return files


@pytest.fixture(scope="module", params=sorted(PRESETS))
def preset_chunks(request):
    preset = PRESETS[request.param]
    return preset, _all_chunks(preset["chunking"])


def _text_budget(chunking, chunk_type):
    cfg = fallback_for(chunking, chunk_type)
    if cfg["method"] == "semantic":
        return max(cfg["max_tokens"], cfg["oversize_window"]["chunk_size"] + 2)
    return cfg["chunk_size"] + 2


def test_sample_chunks_fit_the_model(preset_chunks):
    preset, files = preset_chunks
    chunking = preset["chunking"]
    limit = MAX_INPUT_TOKENS[preset["embedding_model"]] - 2
    max_prefix = chunking["heading_prefix_max_tokens"]
    for chunks in files.values():
        assert chunks
        for chunk in chunks:
            assert chunk.text.strip() == chunk.text != ""
            prefix = count_tokens(chunk.prefix)
            assert prefix <= max_prefix
            # Expansion may also spend the prefix budget the chunk leaves unused
            budget = _text_budget(chunking, chunk.chunk_type) + max_prefix - prefix
            assert count_tokens(chunk.text) <= budget
            assert count_tokens(chunk.embedded_text) <= limit


def test_sample_chunk_ids_are_unique(preset_chunks):
    _, files = preset_chunks
    ids = [i for path, chunks in files.items() for i, _ in assign_ids(chunks, 1, path)]
    assert len(ids) == len(set(ids))


def test_every_ground_truth_section_lands_in_a_chunk(preset_chunks):
    _, files = preset_chunks
    truth = json.loads((REPO / "eval" / "ground_truth.json").read_text())
    checked = 0
    for q in truth["questions"]:
        source = q["expected_source"]
        if q["resource_type"] in ("historical_qa", "no_match"):
            continue  # in-app threads and the off-topic question
        chunks = files[source]
        # Heading sections must be a chunk's heading; labels and slides its text
        if q["resource_type"] in ("repo_markdown", "schedule"):
            texts = [c.prefix for c in chunks]
        else:
            texts = [_norm(c.embedded_text) for c in chunks]
        for section in q["expected_source_section"].split(" / "):
            assert any(_norm(section) in t for t in texts), (q["id"], section)
            checked += 1
    assert checked == 12


def test_sliding_window_profiles_produce_identical_chunks():
    baseline = _all_chunks(PRESETS["sliding-window"]["chunking"])
    for name in ("embedding-alt", "bge-small"):
        assert _all_chunks(PRESETS[name]["chunking"]) == baseline


def test_chunk_is_a_plain_dataclass():
    chunk = Chunk("syllabus", "S", "S", "body")
    assert chunk.embedded_text == "S\nbody"
    assert Chunk("historical_qa", "T", "", "q").embedded_text == "q"


# Regressions from the diff review


def test_small_pdf_with_page_reset_never_crosses_pages():
    pages = ["Slide one title\nalpha beta", "Slide two\ngamma delta"]
    chunks = chunk_pdf(pages, "s.pdf", TAILORED)
    assert [(c.page_start, c.page_end) for c in chunks] == [(1, 1), (2, 2)]
    # Without a page reset the small deck stays one unit
    assert len(chunk_pdf(pages, "s.pdf", BASELINE)) == 1


def test_pdf_prefix_keeps_the_page_label():
    pages = [_words(40, "verylongtitle") + "\nbody text"]
    chunk = chunk_pdf(pages, "slides.pdf", BASELINE)[0]
    assert chunk.prefix.startswith("slides.pdf p.1 > verylongtitle0")
    assert count_tokens(chunk.prefix) <= 30


def test_markdown_lines_count_newlines_only():
    text = "# Title\nline2\n## Sub\ntext more\x0cstill\nlast\n"
    sub = [c for c in _md(text) if c.prefix.endswith("Sub")][0]
    assert (sub.line_start, sub.line_end) == (4, 5)
    assert " " in sub.text


def test_markdown_crlf_bom_and_indented_headings():
    text = "﻿# Title\r\nintro\r\n   ## Indented\r\nbody\r\n"
    chunks = _md(text)
    assert [c.prefix for c in chunks] == ["f.md > Title", "f.md > Title > Indented"]
    assert [(c.line_start, c.line_end) for c in chunks] == [(2, 2), (4, 4)]
    assert all("\r" not in c.text and "﻿" not in c.text for c in chunks)


def test_long_words_are_never_lost():
    link = "[guide](https://git.doit.wisc.edu/cdis/cs/courses/aicoding/realtime-guide.md#L22-34)"
    for position in range(0, 400, 7):
        words = ["word"] * 400
        words.insert(position, link)
        text = " ".join(words)
        spans = _split_unit(text, _window_cfg(150, 30))
        covered = set()
        for a, b in spans:
            covered.update(range(a, b))
        assert all(i in covered for i, c in enumerate(text) if not c.isspace()), (
            position
        )


def test_deeply_nested_html_is_a_value_error():
    html = "<div>" * 3000 + "deep" + "</div>" * 3000
    with pytest.raises(ValueError, match="nested"):
        html_sections(html)
