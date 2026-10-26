"""Citation URLs, text fragments, chunk IDs and metadata (design-rag.md §4.1, §10)."""

import json
from pathlib import Path

import pytest

from app.services.rag.chunking import Chunk
from app.services.rag.citations import (
    CitationContext,
    assign_ids,
    blob_url,
    chunk_metadata,
    content_hash,
    encode_path,
    encode_word,
    raw_pdf_url,
    source_url,
    text_fragment,
    thread_url,
    upload_url,
    web_page_url,
)

REPO = Path(__file__).resolve().parents[2]
WEB = "https://git.doit.wisc.edu/cdis/cs/courses/demo"
SHA = "0123456789abcdef0123456789abcdef01234567"


# Fragments


def test_hyphen_is_percent_encoded():
    assert encode_word("e2e-test") == "e2e%2Dtest"


def test_em_dash_and_reserved_characters():
    assert encode_word("—") == "%E2%80%94"
    assert encode_word("a,b&c") == "a%2Cb%26c"
    # encodeURIComponent leaves these alone
    assert encode_word("it's(ok)!*~") == "it's(ok)!*~"


def test_short_single_line_is_one_term():
    assert text_fragment("Late Policy — Slip Days:") == (
        "text=Late%20Policy%20%E2%80%94%20Slip%20Days%3A"
    )


def test_twelve_words_single_term_thirteen_split():
    twelve = " ".join(f"w{i}" for i in range(12))
    assert "," not in text_fragment(twelve)
    thirteen = " ".join(f"w{i}" for i in range(13))
    assert text_fragment(thirteen) == (
        "text=w0%20w1%20w2%20w3%20w4%20w5,w7%20w8%20w9%20w10%20w11%20w12"
    )


def test_multi_line_takes_first_and_last_six_words():
    text = "\n  a b c d e f g h\nmiddle line\n\nr s t u v w x y z  \n"
    assert text_fragment(text) == "text=a%20b%20c%20d%20e%20f,u%20v%20w%20x%20y%20z"


def test_short_multi_line_uses_whole_lines():
    assert text_fragment("Week 1\nDue: Friday") == "text=Week%201,Due%3A%20Friday"


def test_empty_fragment_is_an_error():
    with pytest.raises(ValueError):
        text_fragment(" \n ")


# URL builders


def test_blob_line_range_and_single_line():
    assert (
        blob_url(WEB, SHA, "a/b.md", 3, 9) == f"{WEB}/-/blob/{SHA}/a/b.md?plain=1#L3-9"
    )
    assert blob_url(WEB, SHA, "a/b.md", 4, 4) == f"{WEB}/-/blob/{SHA}/a/b.md?plain=1#L4"


def test_raw_pdf_page():
    assert raw_pdf_url(WEB, SHA, "lecture-10/slides.pdf", 14) == (
        f"{WEB}/-/raw/{SHA}/lecture-10/slides.pdf#page=14"
    )


def test_path_encoding_keeps_separators():
    assert encode_path("eval/sample_data/repo/p2-buzzer/docs/realtime.md") == (
        "eval/sample_data/repo/p2-buzzer/docs/realtime.md"
    )
    assert encode_path("my notes/week #1.md") == "my%20notes/week%20%231.md"


def test_web_page_replaces_an_existing_fragment():
    assert web_page_url("https://example.edu/syllabus.html#grading", "text=x") == (
        "https://example.edu/syllabus.html#:~:text=x"
    )


def test_thread_url_strips_trailing_slash():
    assert thread_url("http://localhost:8080/", 3, 42) == (
        "http://localhost:8080/student/questions/42?course=3"
    )


def test_upload_without_base_is_unlinked():
    assert upload_url(7, "notes/week 1.md", "#L2-5", None, in_zip=True) == (
        "upload://7/notes/week%201.md#L2-5"
    )


def test_upload_zip_joins_base_and_adds_plain_for_blob():
    base = f"{WEB}/-/blob/main/repo/"
    assert upload_url(7, "p1/instructions.md", "#L2-5", base, in_zip=True) == (
        f"{WEB}/-/blob/main/repo/p1/instructions.md?plain=1#L2-5"
    )


def test_upload_single_file_uses_base_as_is():
    base = "https://example.edu/slides.pdf"
    assert upload_url(7, "slides.pdf", "#page=3", base, in_zip=False) == (
        "https://example.edu/slides.pdf#page=3"
    )


def test_upload_non_blob_base_gets_no_plain():
    base = "https://example.edu/files"
    assert upload_url(7, "a.md", "#L1", base, in_zip=True) == (
        "https://example.edu/files/a.md#L1"
    )


# source_url dispatch


def _md_chunk(**kw):
    return Chunk(
        chunk_type="repo_markdown",
        title="a.md > A",
        prefix="a.md > A",
        text="x",
        line_start=3,
        line_end=9,
        **kw,
    )


def test_source_url_for_each_kind():
    gitlab = CitationContext(kind="gitlab", resource_id=1, web=WEB, sha=SHA)
    assert source_url(_md_chunk(), gitlab, "a.md").endswith("/a.md?plain=1#L3-9")

    pdf = Chunk("repo_pdf", "s.pdf p.2", "", "x", page_start=2, page_end=3)
    assert source_url(pdf, gitlab, "s.pdf").endswith("/-/raw/" + SHA + "/s.pdf#page=2")

    html = Chunk("syllabus", "S", "S", "Hello world")
    assert source_url(html, gitlab, "web/syllabus.html") == (
        f"{WEB}/-/blob/{SHA}/web/syllabus.html#:~:text=Hello%20world"
    )
    web = CitationContext(kind="web", resource_id=1, url="https://example.edu/s.html")
    assert (
        source_url(html, web, None)
        == "https://example.edu/s.html#:~:text=Hello%20world"
    )

    upload = CitationContext(kind="upload", resource_id=5, base=None, in_zip=False)
    assert source_url(_md_chunk(), upload, "a.md") == "upload://5/a.md#L3-9"

    qa = Chunk("historical_qa", "T", "", "Question: T", question_id=42)
    internal = CitationContext(
        kind="internal",
        resource_id=9,
        course_id=3,
        frontend_url="http://localhost:8080",
    )
    assert source_url(qa, internal, None) == (
        "http://localhost:8080/student/questions/42?course=3"
    )


def test_every_ground_truth_path_survives_in_its_url():
    truth = json.loads((REPO / "eval" / "ground_truth.json").read_text())
    ctx = CitationContext(kind="gitlab", resource_id=1, web=WEB, sha=SHA)
    paths = {
        q["expected_source"]
        for q in truth["questions"]
        if (q["expected_source"] or "").startswith("eval/")
    }
    assert len(paths) == 6
    for path in paths:
        if path.endswith(".md"):
            chunk = _md_chunk()
        elif path.endswith(".pdf"):
            chunk = Chunk("repo_pdf", "p", "", "x", page_start=1, page_end=1)
        else:
            chunk = Chunk("syllabus", "S", "S", "Hello world")
        assert path in source_url(chunk, ctx, path)


# IDs and metadata


def test_content_hash_covers_prefix():
    a = Chunk("repo_markdown", "f > A", "f > A", "same body")
    b = Chunk("repo_markdown", "f > B", "f > B", "same body")
    assert content_hash(a.embedded_text) != content_hash(b.embedded_text)


def test_ids_stable_and_heading_rename_changes_id():
    chunks = [_md_chunk()]
    assert assign_ids(chunks, 1, "a.md") == assign_ids([_md_chunk()], 1, "a.md")
    renamed = [
        Chunk("repo_markdown", "a.md > B", "a.md > B", "x", line_start=3, line_end=9)
    ]
    assert assign_ids(chunks, 1, "a.md")[0][0] != assign_ids(renamed, 1, "a.md")[0][0]
    # Same text in another resource or file is another chunk
    assert assign_ids(chunks, 1, "a.md") != assign_ids(chunks, 2, "a.md")
    assert assign_ids(chunks, 1, "a.md") != assign_ids(chunks, 1, "b.md")


def test_duplicate_texts_get_distinct_ids():
    ids = assign_ids([_md_chunk(), _md_chunk()], 1, "a.md")
    assert ids[0][1] == ids[1][1]
    assert ids[0][0] != ids[1][0]


def test_metadata_omits_none_and_has_type_keys():
    md = chunk_metadata(
        _md_chunk(),
        course_id=3,
        profile_id=4,
        resource_id=5,
        chunk_index=0,
        source_url="u",
        content_hash="h",
        ingest_job_id=6,
        rel_path="a.md",
        commit_sha=SHA,
    )
    assert None not in md.values()
    assert md["line_start"] == 3 and md["line_end"] == 9
    assert "page_start" not in md and "question_id" not in md
    assert md["resource_type"] == "repo_markdown"

    qa = Chunk("historical_qa", "T", "", "Question: T", question_id=42)
    meta = chunk_metadata(
        qa,
        course_id=3,
        profile_id=4,
        resource_id=5,
        chunk_index=0,
        source_url="u",
        content_hash="h",
        ingest_job_id=6,
    )
    assert set(meta) == {
        "course_id",
        "profile_id",
        "resource_id",
        "chunk_index",
        "resource_type",
        "source_url",
        "title",
        "content_hash",
        "ingest_job_id",
        "question_id",
    }
    assert all(isinstance(v, (str, int, float, bool)) for v in meta.values())


def test_upload_base_fragment_dropped_and_plain_not_doubled():
    assert upload_url(
        7, "a.md", "#L1", "https://example.edu/a.md#top", in_zip=False
    ) == ("https://example.edu/a.md#L1")
    base = f"{WEB}/-/blob/main/a.md?plain=1"
    assert upload_url(7, "a.md", "#L1", base, in_zip=False) == base + "#L1"


def test_upload_zip_base_with_query_keeps_query_after_path():
    base = f"{WEB}/-/blob/abc/sub?plain=1"
    assert upload_url(7, "dir/a b.md", "#L3-4", base, in_zip=True) == (
        f"{WEB}/-/blob/abc/sub/dir/a%20b.md?plain=1#L3-4"
    )


def test_uploaded_html_and_pdf_citations():
    html = Chunk("syllabus", "S", "S", "Hello world")
    single = CitationContext(
        kind="upload", resource_id=5, base="https://example.edu/s.html", in_zip=False
    )
    assert source_url(html, single, "s.html") == (
        "https://example.edu/s.html#:~:text=Hello%20world"
    )
    pdf = Chunk("repo_pdf", "s.pdf p.2", "", "x", page_start=2, page_end=2)
    blob = CitationContext(
        kind="upload", resource_id=5, base=f"{WEB}/-/blob/main/", in_zip=True
    )
    assert source_url(pdf, blob, "l/s.pdf") == f"{WEB}/-/raw/main/l/s.pdf#page=2"
