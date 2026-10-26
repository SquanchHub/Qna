"""Citation URLs, chunk IDs and Chroma metadata (design-rag.md §4.1).

URLs are built once at ingestion and stored as `source_url`; query time
never rebuilds them.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from urllib.parse import quote

from .chunking import Chunk

FRAGMENT_TERM_WORDS = 6
FRAGMENT_SINGLE_TERM_WORDS = 12


def encode_word(word: str) -> str:
    """encodeURIComponent, plus `-`, which text-fragment syntax reserves."""
    return quote(word, safe="!'()*~").replace("-", "%2D")


def text_fragment(display_text: str) -> str:
    """`text=` directive: the whole line if it is one of <= 12 words, else the
    first 6 words of the first line and the last 6 of the last."""
    lines = [line.split() for line in display_text.splitlines()]
    lines = [words for words in lines if words]
    if not lines:
        raise ValueError("no display text for a fragment")

    def term(words: list[str]) -> str:
        return "%20".join(encode_word(w) for w in words)

    if len(lines) == 1 and len(lines[0]) <= FRAGMENT_SINGLE_TERM_WORDS:
        return f"text={term(lines[0])}"
    start = term(lines[0][:FRAGMENT_TERM_WORDS])
    end = term(lines[-1][-FRAGMENT_TERM_WORDS:])
    return f"text={start},{end}"


def encode_path(path: str) -> str:
    """Percent-encode each segment; `/ . - _` stay literal (§4.1.1)."""
    return quote(path, safe="/")


def _lines_suffix(line_start: int, line_end: int) -> str:
    if line_start == line_end:
        return f"#L{line_start}"
    return f"#L{line_start}-{line_end}"


def blob_url(web: str, sha: str, path: str, line_start: int, line_end: int) -> str:
    return (
        f"{web}/-/blob/{sha}/{encode_path(path)}?plain=1"
        f"{_lines_suffix(line_start, line_end)}"
    )


def raw_pdf_url(web: str, sha: str, path: str, page: int) -> str:
    return f"{web}/-/raw/{sha}/{encode_path(path)}#page={page}"


def gitlab_html_url(web: str, sha: str, path: str, fragment: str) -> str:
    return f"{web}/-/blob/{sha}/{encode_path(path)}#:~:{fragment}"


def web_page_url(url: str, fragment: str) -> str:
    return f"{url.split('#', 1)[0]}#:~:{fragment}"


def thread_url(frontend_url: str, course_id: int, question_id: int) -> str:
    return (
        f"{frontend_url.rstrip('/')}/student/questions/{question_id}?course={course_id}"
    )


def upload_url(
    resource_id: int, path: str, suffix: str, base: str | None, in_zip: bool
) -> str:
    """Upload-path citation: `citation_base_url` (joined with the in-zip path
    for a zip) plus the suffix, else an unlinked `upload://` reference."""
    if not base:
        return f"upload://{resource_id}/{encode_path(path)}{suffix}"
    base, _, query = base.split("#", 1)[0].partition("?")
    url = f"{base.rstrip('/')}/{encode_path(path)}" if in_zip else base
    if suffix.startswith("#page=") and "/-/blob/" in url:
        # The blob page shows the viewer; only raw lets the browser honour #page
        url = url.replace("/-/blob/", "/-/raw/", 1)
    params = [q for q in query.split("&") if q]
    if suffix.startswith("#L") and "/-/blob/" in url and "plain=1" not in params:
        params.append("plain=1")
    if params:
        url += "?" + "&".join(params)
    return url + suffix


@dataclass(frozen=True)
class CitationContext:
    """Where one resource's chunks come from.

    kind: "gitlab" (web + sha), "web" (url), "upload" (base, in_zip) or
    "internal" (historical Q&A: course_id, frontend_url).
    """

    kind: str
    resource_id: int
    web: str | None = None
    sha: str | None = None
    url: str | None = None
    base: str | None = None
    in_zip: bool = False
    course_id: int | None = None
    frontend_url: str | None = None


def _suffix(chunk: Chunk) -> str:
    if chunk.chunk_type == "repo_markdown":
        return _lines_suffix(chunk.line_start, chunk.line_end)
    if chunk.chunk_type == "repo_pdf":
        return f"#page={chunk.page_start}"
    return f"#:~:{text_fragment(chunk.text)}"


def source_url(chunk: Chunk, ctx: CitationContext, rel_path: str | None) -> str:
    """The chunk's `source_url` metadata (§4.1.1)."""
    if chunk.chunk_type == "historical_qa":
        return thread_url(ctx.frontend_url, ctx.course_id, chunk.question_id)
    if ctx.kind == "gitlab":
        if chunk.chunk_type == "repo_markdown":
            return blob_url(
                ctx.web, ctx.sha, rel_path, chunk.line_start, chunk.line_end
            )
        if chunk.chunk_type == "repo_pdf":
            return raw_pdf_url(ctx.web, ctx.sha, rel_path, chunk.page_start)
        return gitlab_html_url(ctx.web, ctx.sha, rel_path, text_fragment(chunk.text))
    if ctx.kind == "web":
        return web_page_url(ctx.url, text_fragment(chunk.text))
    if ctx.kind == "upload":
        return upload_url(
            ctx.resource_id, rel_path, _suffix(chunk), ctx.base, ctx.in_zip
        )
    raise ValueError(f"no citation for {chunk.chunk_type} from {ctx.kind}")


def content_hash(embedded_text: str) -> str:
    return hashlib.sha256(embedded_text.encode()).hexdigest()


def assign_ids(
    chunks: list[Chunk], resource_id: int, rel_path: str | None
) -> list[tuple[str, str]]:
    """(chunk_id, content_hash) per chunk, in order. Call it once per
    (resource, rel_path) group with all of that group's chunks: one file, or
    every thread of the historical-Q&A resource (rel_path None). Identical
    texts in a group are told apart by their ordinal; `chunk_index` is the
    position in the same list."""
    seen: Counter[str] = Counter()
    ids = []
    for chunk in chunks:
        digest = content_hash(chunk.embedded_text)
        key = f"{resource_id}|{rel_path or ''}|{digest}|{seen[digest]}"
        seen[digest] += 1
        ids.append((hashlib.sha256(key.encode()).hexdigest(), digest))
    return ids


def chunk_metadata(
    chunk: Chunk,
    *,
    course_id: int,
    profile_id: int,
    resource_id: int,
    chunk_index: int,
    source_url: str,
    content_hash: str,
    ingest_job_id: int,
    rel_path: str | None = None,
    commit_sha: str | None = None,
) -> dict[str, str | int]:
    """Flat Chroma metadata (§4.1.2); inapplicable keys are omitted, since
    Chroma rejects null."""
    meta = {
        "course_id": course_id,
        "profile_id": profile_id,
        "resource_id": resource_id,
        "chunk_index": chunk_index,
        "resource_type": chunk.chunk_type,
        "source_url": source_url,
        "title": chunk.title,
        "content_hash": content_hash,
        "ingest_job_id": ingest_job_id,
        "rel_path": rel_path,
        "line_start": chunk.line_start,
        "line_end": chunk.line_end,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "question_id": chunk.question_id,
        "commit_sha": commit_sha,
    }
    return {k: v for k, v in meta.items() if v is not None}
