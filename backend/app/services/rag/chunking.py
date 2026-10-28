"""Type-tailored chunkers (design-rag.md §4.5.4).

Every type is first split by its own structure (headings, pages, one thread),
identically in every profile. Only a structural unit larger than the
profile's size goes through the fallback chunker: a sliding window over chunk
tokens or, for syllabus and schedule, semantic splitting. Chunk text is
always sliced from the source characters, never decoded from token ids.
"""

from __future__ import annotations

import io
import math
import re
from bisect import bisect_right
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from bs4 import BeautifulSoup, NavigableString, Tag
from bs4.element import Comment, Declaration, Doctype, ProcessingInstruction

from .presets import fallback_for
from .tokens import Token, count_tokens, tokenize

# Tokens a window may grow by when its ends move out to whole words
EXPANSION_SLACK = 2
PREFIX_SEPARATOR = " > "

Embed = Callable[[list[str]], Awaitable[list[list[float]]]]
Span = tuple[int, int]


@dataclass
class Chunk:
    """One retrievable passage before IDs and URLs are attached."""

    chunk_type: str
    title: str
    prefix: str
    text: str
    line_start: int | None = None
    line_end: int | None = None
    page_start: int | None = None
    page_end: int | None = None
    question_id: int | None = None

    @property
    def embedded_text(self) -> str:
        """Prefix + display text: what is embedded, hashed and returned."""
        return f"{self.prefix}\n{self.text}" if self.prefix else self.text


# Shared pieces


def window(n_tokens: int, size: int, overlap: int) -> list[Span]:
    """Token index ranges [start, end) per the §4.5.4 pseudocode."""
    if n_tokens <= size:
        return [(0, n_tokens)]
    step = size - overlap
    ranges = []
    start = 0
    while True:
        ranges.append((start, min(start + size, n_tokens)))
        if start + size >= n_tokens:
            return ranges
        start += step


def _trim(text: str, a: int, b: int) -> Span:
    while a < b and text[a].isspace():
        a += 1
    while b > a and text[b - 1].isspace():
        b -= 1
    return a, b


def _expand(
    text: str,
    a: int,
    b: int,
    lo: int,
    hi: int,
    limit: int,
    prev_end: int | None = None,
    next_start: int | None = None,
) -> Span:
    """Move [a, b) to whole words within [lo, hi), keeping <= limit tokens.

    Outward first. A side that can't grow drops its cut word instead, but
    only when the neighbouring window (raw span ending at `prev_end` or
    starting at `next_start`) covers that word; otherwise it keeps the exact
    token boundary, so no text is ever lost.
    """
    out_a = a
    while out_a > lo and not text[out_a - 1].isspace():
        out_a -= 1
    out_b = b
    while out_b < hi and not text[out_b].isspace():
        out_b += 1
    in_a = a
    if out_a < a:
        while in_a < b and not text[in_a].isspace():
            in_a += 1
        while in_a < b and text[in_a].isspace():
            in_a += 1
    in_b = b
    if out_b > b:
        while in_b > in_a and not text[in_b - 1].isspace():
            in_b -= 1
        while in_b > in_a and text[in_b - 1].isspace():
            in_b -= 1
    starts = [out_a]
    if prev_end is not None and in_a <= prev_end:
        starts.append(in_a)
    starts.append(a)
    ends = [out_b]
    if next_start is not None and next_start <= in_b:
        ends.append(in_b)
    ends.append(b)
    for s in starts:
        for e in ends:
            if s < e and count_tokens(text[s:e]) <= limit:
                return s, e
    return a, b


def _no_spare(_: int) -> int:
    return 0


def _window_spans(
    text: str,
    tokens: Sequence[Token],
    lo: int,
    hi: int,
    size: int,
    overlap: int,
    spare: Callable[[int], int] = _no_spare,
) -> list[Span]:
    """Character spans of the windows over the tokens inside [lo, hi).
    `spare(start)` is the prefix budget a window starting there leaves
    unused, which whole-word expansion may also spend."""
    inside = [t for t in tokens if t.start >= lo and t.end <= hi]
    if not inside:
        return []
    if len(inside) <= size:
        return [_trim(text, lo, hi)]
    raw = [
        (inside[i].start, inside[j - 1].end)
        for i, j in window(len(inside), size, overlap)
    ]
    spans = []
    for k, (a, b) in enumerate(raw):
        prev_end = raw[k - 1][1] if k > 0 else None
        next_start = raw[k + 1][0] if k + 1 < len(raw) else None
        limit = size + EXPANSION_SLACK + spare(a)
        spans.append(_expand(text, a, b, lo, hi, limit, prev_end, next_start))
    return spans


def _split_unit(
    text: str,
    cfg: dict,
    segments: Sequence[Span] | None = None,
    spare: Callable[[int], int] = _no_spare,
    always_segment: bool = False,
) -> list[Span]:
    """Sliding-window fallback on one structural unit. `segments` are the
    `reset_at` boundaries, used only when the unit is oversized unless
    `always_segment` (PDF pages under `reset_at: page`)."""
    tokens = tokenize(text)
    if not tokens:
        return []
    size, overlap = cfg["chunk_size"], cfg["chunk_overlap"]
    if len(tokens) <= size and not (always_segment and segments):
        return [_trim(text, 0, len(text))]
    if cfg.get("reset_at", "none") == "none" or not segments:
        segments = [(0, len(text))]
    spans = []
    for lo, hi in segments:
        spans.extend(_window_spans(text, tokens, lo, hi, size, overlap, spare))
    return spans


def _spare_after(prefix: str, max_prefix: int) -> Callable[[int], int]:
    unused = max(0, max_prefix - count_tokens(prefix))
    return lambda _: unused


def heading_prefix(components: Sequence[str], max_tokens: int = 30) -> str:
    """`A > B > C`, dropping leading components until it fits; a single
    over-long component is cut at a word boundary."""
    parts = [" ".join(c.split()) for c in components]
    parts = [p for p in parts if p]
    while parts:
        prefix = PREFIX_SEPARATOR.join(parts)
        if count_tokens(prefix) <= max_tokens:
            return prefix
        if len(parts) == 1:
            break
        parts = parts[1:]
    if not parts:
        return ""
    only = parts[0]
    end = tokenize(only)[max_tokens - 1].end
    if end < len(only) and not only[end].isspace():
        space = only.rfind(" ", 0, end)
        if space > 0:
            end = space
    return only[:end].rstrip()


def _starts_of_lines(text: str) -> list[int]:
    return [0] + [m.end() for m in re.finditer("\n", text)]


# Semantic (syllabus and schedule)

_SENTENCE = re.compile(r"\S.*?(?:[.!?]+(?=\s)|$)")


def _sentences(text: str) -> list[Span]:
    """Sentences split on [.!?]+ before whitespace and on line breaks."""
    spans = []
    for start, line in zip(_starts_of_lines(text), text.split("\n")):
        for m in _SENTENCE.finditer(line):
            spans.append(_trim(text, start + m.start(), start + m.end()))
    return [s for s in spans if s[0] < s[1]]


def _cosine(u: Sequence[float], v: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(u, v))
    norm = math.sqrt(sum(x * x for x in u)) * math.sqrt(sum(y * y for y in v))
    return dot / norm if norm else 0.0


async def semantic(
    text: str, cfg: dict, embed: Embed, spare: Callable[[int], int] = _no_spare
) -> list[Span]:
    """Spans close where neighbouring sentences' similarity drops below the
    threshold, never at the cap; an oversized span is windowed, never cut.

    `embed` takes the sentences in one batch and uses the profile's model
    with no query_instruction (that is for queries only).
    """
    tokens = tokenize(text)
    if not tokens:
        return []
    if len(tokens) <= cfg["max_tokens"]:
        return [_trim(text, 0, len(text))]
    sentences = _sentences(text)
    vectors = await embed([text[a:b] for a, b in sentences])
    if len(vectors) != len(sentences):
        raise ValueError("embed returned the wrong number of vectors")

    groups = [[sentences[0]]]
    for i in range(1, len(sentences)):
        if _cosine(vectors[i - 1], vectors[i]) < cfg["similarity_threshold"]:
            groups.append([])
        groups[-1].append(sentences[i])

    oversize = cfg["oversize_window"]
    spans = []
    for group in groups:
        lo, hi = group[0][0], group[-1][1]
        if count_tokens(text[lo:hi]) <= cfg["max_tokens"]:
            spans.append((lo, hi))
        else:
            spans.extend(
                _window_spans(
                    text,
                    tokens,
                    lo,
                    hi,
                    oversize["chunk_size"],
                    oversize["chunk_overlap"],
                    spare,
                )
            )
    return spans


# Markdown

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_SECTION = re.compile(r"^ {0,3}(#{1,3})\s+(.*?)(?:\s+#+)?\s*$")
_SUBHEADING = re.compile(r"^ {0,3}#{4,6}\s")


@dataclass
class _MdSection:
    path: list[str]
    first: int  # 0-based index of the first content line
    last: int  # exclusive
    subheadings: list[int]


def _md_sections(lines: list[str]) -> list[_MdSection]:
    sections = [_MdSection([], 0, 0, [])]
    headings: dict[int, str] = {}
    fence: str | None = None
    for i, line in enumerate(lines):
        if fence is not None:
            stripped = line.strip()
            if stripped.startswith(fence) and set(stripped) == {fence[0]}:
                fence = None
            continue
        m = _FENCE.match(line)
        if m:
            fence = m.group(1)
            continue
        m = _SECTION.match(line)
        if m:
            sections[-1].last = i
            level = len(m.group(1))
            headings = {k: v for k, v in headings.items() if k < level}
            headings[level] = m.group(2)
            path = [headings[k] for k in sorted(headings) if headings[k]]
            sections.append(_MdSection(path, i + 1, i + 1, []))
            continue
        if _SUBHEADING.match(line):
            sections[-1].subheadings.append(i)
    sections[-1].last = len(lines)
    return sections


def chunk_markdown(text: str, file_label: str, chunking: dict) -> list[Chunk]:
    """One section per h1–h3 outside code fences; exact 1-based line ranges."""
    cfg = fallback_for(chunking, "repo_markdown")
    max_prefix = chunking["heading_prefix_max_tokens"]
    # GitLab numbers lines by "\n" only; splitlines() also breaks on \x0c etc.
    lines = [
        line.removesuffix("\r") for line in text.removeprefix("\ufeff").split("\n")
    ]
    if lines and lines[-1] == "":
        lines.pop()
    chunks = []
    for section in _md_sections(lines):
        first, last = section.first, section.last
        while first < last and not lines[first].strip():
            first += 1
        while last > first and not lines[last - 1].strip():
            last -= 1
        if first == last:
            continue
        unit = "\n".join(lines[first:last])
        starts = _starts_of_lines(unit)
        segments = None
        if section.subheadings:
            cuts = sorted(
                {0}
                | {starts[i - first] for i in section.subheadings if first < i < last}
            )
            segments = list(zip(cuts, [*cuts[1:], len(unit)]))
        prefix = heading_prefix([file_label, *section.path], max_prefix)
        spare = _spare_after(prefix, max_prefix)
        for a, b in _split_unit(unit, cfg, segments, spare):
            chunks.append(
                Chunk(
                    chunk_type="repo_markdown",
                    title=prefix,
                    prefix=prefix,
                    text=unit[a:b],
                    line_start=first + bisect_right(starts, a),
                    line_end=first + bisect_right(starts, b - 1),
                )
            )
    return chunks


# HTML (syllabus and schedule)

_REMOVED_TAGS = ["script", "style", "noscript", "nav", "header", "footer"]
_REMOVED_SELECTOR = "[role=navigation], .sr-only"
_SECTION_TAGS = {"h1": 1, "h2": 2, "h3": 3}
_BLOCK_TAGS = {
    "p", "li", "tr", "div", "h4", "h5", "h6", "br", "ul", "ol", "table",
    "thead", "tbody", "tfoot", "section", "article", "aside", "blockquote",
    "pre", "dl", "dt", "dd", "figure", "figcaption", "form", "hr",
}  # fmt: skip
_CELL_TAGS = {"td", "th"}
_SKIPPED_STRINGS = (Comment, Declaration, Doctype, ProcessingInstruction)


def html_sections(html: str | bytes) -> list[tuple[list[str], list[str]]]:
    """(heading path, display lines) per h1–h3 section of the main content."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(_REMOVED_TAGS):
        tag.decompose()
    for tag in soup.select(_REMOVED_SELECTOR):
        tag.decompose()
    root = soup.find("main") or soup.find(id="main-content") or soup.body or soup

    sections: list[tuple[list[str], list[str]]] = []
    headings: dict[int, str] = {}
    lines: list[str] = []
    buffer: list[str] = []

    def flush_line() -> None:
        line = " ".join("".join(buffer).split())
        buffer.clear()
        if line:
            lines.append(line)

    def flush_section() -> None:
        flush_line()
        if lines:
            path = [headings[k] for k in sorted(headings)]
            sections.append((path, list(lines)))
            lines.clear()

    def walk(node: Tag) -> None:
        for child in node.children:
            if isinstance(child, NavigableString):
                if not isinstance(child, _SKIPPED_STRINGS):
                    buffer.append(str(child))
                continue
            if not isinstance(child, Tag):
                continue
            name = child.name
            if name in _SECTION_TAGS:
                flush_section()
                level = _SECTION_TAGS[name]
                for k in [k for k in headings if k >= level]:
                    del headings[k]
                title = " ".join(child.get_text().split())
                if title:
                    headings[level] = title
            elif name in _BLOCK_TAGS:
                flush_line()
                walk(child)
                flush_line()
            elif name in _CELL_TAGS:
                buffer.append(" ")
                walk(child)
                buffer.append(" ")
            else:
                walk(child)

    try:
        walk(root)
    except RecursionError:
        raise ValueError("HTML is nested too deeply to parse") from None
    flush_section()
    return sections


async def chunk_html(
    html: str | bytes, chunk_type: str, chunking: dict, embed: Embed | None = None
) -> list[Chunk]:
    """Sections per h1–h3 with an H1 > H2 > H3 prefix; `embed` is required
    when the type's fallback is semantic."""
    cfg = fallback_for(chunking, chunk_type)
    if cfg["method"] == "semantic" and embed is None:
        raise ValueError(f"semantic chunking of {chunk_type} needs an embedder")
    max_prefix = chunking["heading_prefix_max_tokens"]
    chunks = []
    for path, lines in html_sections(html):
        unit = "\n".join(lines)
        prefix = heading_prefix(path, max_prefix)
        spare = _spare_after(prefix, max_prefix)
        if cfg["method"] == "semantic":
            spans = await semantic(unit, cfg, embed, spare)
        else:
            spans = _split_unit(unit, cfg, spare=spare)
        for a, b in spans:
            chunks.append(
                Chunk(
                    chunk_type=chunk_type,
                    title=prefix or chunk_type,
                    prefix=prefix,
                    text=unit[a:b],
                )
            )
    return chunks


# PDF


def pdf_pages(data: bytes) -> list[str]:
    """Text per page; a page pypdf can't read is empty."""
    from pypdf import PdfReader

    pages = []
    for page in PdfReader(io.BytesIO(data)).pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - one bad page shouldn't sink the file
            pages.append("")
    return pages


def chunk_pdf(pages: Sequence[str], file_label: str, chunking: dict) -> list[Chunk]:
    """Pages streamed together (`reset_at: none`) or windowed alone (`page`);
    each chunk knows its first and last page."""
    cfg = fallback_for(chunking, "repo_pdf")
    max_prefix = chunking["heading_prefix_max_tokens"]
    parts: list[str] = []
    page_numbers: list[int] = []
    first_lines: dict[int, str] = {}
    for number, raw in enumerate(pages, start=1):
        page_lines = [" ".join(line.split()) for line in raw.splitlines()]
        page_lines = [line for line in page_lines if line]
        if page_lines:
            parts.append("\n".join(page_lines))
            page_numbers.append(number)
            first_lines[number] = page_lines[0]
    if not parts:
        return []
    unit = "\n".join(parts)
    starts = [0]
    for part in parts[:-1]:
        starts.append(starts[-1] + len(part) + 1)
    segments = list(zip(starts, [s - 1 for s in starts[1:]] + [len(unit)]))

    def page_at(pos: int) -> int:
        return page_numbers[bisect_right(starts, pos) - 1]

    # Pages are joined by "\n", so a window's expansion never changes its page
    def page_prefix(n: int) -> str:
        # Keep the page label; only the slide's first line is shortened
        label = heading_prefix([f"{file_label} p.{n}"], max_prefix)
        room = max_prefix - count_tokens(label + PREFIX_SEPARATOR)
        line = heading_prefix([first_lines[n]], room) if room > 0 else ""
        return PREFIX_SEPARATOR.join(p for p in (label, line) if p)

    prefixes = {n: page_prefix(n) for n in first_lines}

    def spare(pos: int) -> int:
        return max(0, max_prefix - count_tokens(prefixes[page_at(pos)]))

    chunks = []
    for a, b in _split_unit(unit, cfg, segments, spare, always_segment=True):
        first = page_at(a)
        chunks.append(
            Chunk(
                chunk_type="repo_pdf",
                title=f"{file_label} p.{first}",
                prefix=prefixes[first],
                text=unit[a:b],
                page_start=first,
                page_end=page_at(b - 1),
            )
        )
    return chunks


# Historical Q&A


def qa_answer(question, posts):
    """The answer a thread is indexed with (§4.5.4), or None: the accepted
    non-AI ANSWER, else for a CLOSED thread the latest STAFF ANSWER."""
    answers = [p for p in posts if p.kind == "ANSWER" and p.author_role != "AI"]
    accepted = [p for p in answers if p.is_accepted]
    if accepted:
        return max(accepted, key=lambda p: (p.created_at, p.id))
    if question.status == "CLOSED":
        staff = [p for p in answers if p.author_role == "STAFF"]
        if staff:
            return max(staff, key=lambda p: (p.created_at, p.id))
    return None


def chunk_qa(question_id: int, title: str, body: str, answer: str) -> list[Chunk]:
    """One chunk per pair, never split, whatever its length (T4: pairs are
    atomic). Infinity truncates MiniLM input to 256 tokens, so the embedding
    covers the question and the start of the answer; the prompt clips long
    chunks (prompts.PROMPT_CHUNK_MAX_TOKENS)."""
    title = " ".join(title.split())
    text = f"Question: {title}\n{body.strip()}\n\nAnswer: {answer.strip()}"
    return [Chunk("historical_qa", title, "", text, question_id=question_id)]
