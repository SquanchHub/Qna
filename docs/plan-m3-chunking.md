# M3 plan: tokenizer, chunkers and citation helpers

Schedule row 10-27 (vzhou2, T4). Design: `docs/design-rag.md` §4.1 (citations), §4.4.1 (presets), §4.5.4 (chunkers), §10 (unit tests). Branch `feature/rag-chunking`, stacked on `feature/rag-data-model` (MR !18) because both edit `docs/schedule.md`; the MR targets `main`.

M3 is pure code with no I/O beyond reading bytes the caller passes in. Nothing here touches MySQL, Chroma, Infinity or the network; M4 (fetchers and jobs) calls these functions. Done when `test_chunking.py`, `test_citations.py` and `test_presets.py` pass on the real `eval/sample_data/` files.

## 1. Files

| File | Contents |
|---|---|
| `backend/app/services/rag/assets/minilm_tokenizer.json` | Vendored `sentence-transformers/all-MiniLM-L6-v2` tokenizer (snapshot `1110a243…`, sha256 `be50c362…`), copied from the Infinity cache |
| `services/rag/tokens.py` | Chunk-token unit: `Token(start, end)`, `tokenize(text)`, `count_tokens(text)` |
| `services/rag/presets.py` | The four presets, `MAX_INPUT_TOKENS`, `validate_chunking(chunking, model)`, `fallback_for(chunking, chunk_type)` |
| `services/rag/chunking.py` | `Chunk`, `window`, `semantic`, `heading_prefix`, `chunk_markdown`, `chunk_html`, `pdf_pages`, `chunk_pdf`, `qa_answer`, `chunk_qa` |
| `services/rag/citations.py` | Fragment and URL builders, `CitationContext`, `source_url`, `content_hash`, `assign_ids`, `chunk_metadata` |
| `requirements.txt` | `tokenizers`, `beautifulsoup4`, `lxml`, `pypdf` (as §4.3.1 says, added with the milestone that uses them) |
| `tests/unit/test_chunking.py`, `test_citations.py`, `test_presets.py` | §10 unit tests |
| `services/rag/README` or `services/README.md` | One line per new module, as for M1/M2 |

## 2. Tokenizer (`tokens.py`)

- `Tokenizer.from_file(assets/minilm_tokenizer.json)`, loaded lazily once (module-level cache). **The vendored file sets truncation at 128 and fixed padding to 128**, so the loader calls `no_truncation()` and `no_padding()`; a test asserts a 1000-word text counts more than 128 tokens.
- `encode(text, add_special_tokens=False)`: chunk tokens exclude `[CLS]`/`[SEP]` (design Terms). `tokenize(text)` returns `[Token(start, end)]` from `encoding.offsets`, which map to the **original** characters even after BertNormalizer lowercases and strips accents (checked: `Café` → `cafe` at the right offsets; emoji become `[UNK]` with offsets).
- `count_tokens(text) = len(tokenize(text))`.

## 3. Presets (`presets.py`)

`PRESETS: dict[str, dict]` with `preset`, `embedding_model`, `query_instruction` (`""` when none) and `chunking`, exactly the §4.4.1 table. Every `chunking` is the full object (`token_unit`, `heading_prefix_max_tokens`, `default`, `per_type`); `sliding-window`, `embedding-alt` and `bge-small` share one `per_type: {}` config, so their chunks are identical.

`validate_chunking(chunking, model)` raises `ValueError` with a reason:
- `token_unit == "minilm-wordpiece"`; `heading_prefix_max_tokens` is an int ≥ 1.
- Unknown keys are rejected at every level, and sizes must be real ints (not bools or floats).
- `default` must be a `sliding_window` with no `reset_at`, because it also covers markdown, PDF and Q&A.
- `per_type` keys ⊆ `syllabus, schedule, repo_markdown, repo_pdf`; `method` ∈ `sliding_window, semantic`; `semantic` only for syllabus and schedule.
- `sliding_window`: `0 ≤ chunk_overlap < chunk_size`; `reset_at` ∈ `none, page, subheading` (`page` only on `repo_pdf`, `subheading` only on `repo_markdown`).
- `semantic`: `0 < similarity_threshold < 1`, `max_tokens`, and an `oversize_window` that validates as a sliding window.
- Budget: `size + heading_prefix_max_tokens + 4 ≤ MAX_INPUT_TOKENS[model]` for every size (`chunk_size`, `max_tokens`, `oversize_window.chunk_size`), with 256 (MiniLM), 512 (bge-small), 8192 (gte, our cap). An unknown model is an error. The 4 covers `[CLS]`, `[SEP]` and 2 tokens of whole-word expansion slack (§4.1). The newline between the prefix and the text is whitespace and costs no token, so `count(prefix + "\n" + text) = count(prefix) + count(text)`.
- Historical Q&A's fixed 222 is checked against MiniLM too: `222 + 30 + 4 = 256`.

"The model is served by Infinity" needs the network and moves to profile creation in M4.

`fallback_for(chunking, chunk_type)` returns the `per_type` entry, else `default`, with `reset_at` defaulting to `none`. Historical Q&A always uses `default`.

## 4. Chunkers (`chunking.py`)

```python
@dataclass
class Chunk:
    chunk_type: str              # syllabus | schedule | repo_markdown | repo_pdf | historical_qa
    title: str                   # metadata `title` (§4.1.2)
    prefix: str                  # heading prefix, "" when none
    text: str                    # display text: source characters, never decoded ids
    line_start: int | None = None   # repo_markdown, 1-based inclusive
    line_end: int | None = None
    page_start: int | None = None   # repo_pdf, 1-based
    page_end: int | None = None
    question_id: int | None = None  # historical_qa

    @property
    def embedded_text(self) -> str:   # what is embedded and hashed
        return f"{self.prefix}\n{self.text}" if self.prefix else self.text
```

`title` is the heading prefix for markdown and HTML, `slides.pdf p.7` for PDF and the thread title for Q&A.

### 4.1 Shared pieces

- **Unit text.** A structural unit is one string (`unit_text`) plus a character → line (or page) map. Its tokens carry offsets into that string, so every chunk is `unit_text[a:b]` and its line or page range comes from `a` and `b - 1`.
- **`window(tokens, size, overlap)`** returns token index ranges exactly as the §4.5.4 pseudocode: one range when `len ≤ size`; otherwise starts `0, step, 2·step…` with `step = size − overlap`, stopping once `start + size ≥ len`.
- **Whole-word expansion.**
  - A range `[i, j)` becomes characters `[tokens[i].start, tokens[j-1].end)`. The start then moves left and the end moves right to the nearest whitespace (or the unit edge); a "word" is a run of non-whitespace.
  - **Budget (revised after review):** the expanded text may hold at most `size + 2 + spare` tokens. The 2 is `EXPANSION_SLACK`, which is how this plan reads the design's `+ 4`: `[CLS]`, `[SEP]` and 2 tokens of slack. That reading is ours, not stated in the design. `spare` is the part of the 30-token prefix budget that the chunk's own prefix leaves unused. It depends only on the config and the source, so the sliding-window profiles still produce identical chunks.
  - **Fallbacks:** if both sides expanded don't fit, the code tries keeping one side out and dropping the other side's cut word (moving it inward), then dropping both cut words. Only a single word wider than the window keeps the exact token boundaries.
  - **Coverage:** windows are defined by token indices, so consecutive windows tile the unit. A dropped boundary word is covered by the overlap.
  - Tests assert every sample chunk's `count_tokens(embedded_text) ≤ MAX_INPUT_TOKENS − 2`.
- **Semantic (`semantic(unit, cfg, embed)`)** for syllabus and schedule only. Sentences are split on `[.!?]+` followed by whitespace, or on display-line breaks, and each keeps its character span. `embed(sentences)` is an injected `async (list[str]) -> list[list[float]]` (Infinity in M4, a stub in tests) and returns L2-normalised vectors; cosine is the dot product. A new span starts where `cos(v[i-1], v[i]) < similarity_threshold`. Spans close only at similarity drops, never at the cap: a span within `max_tokens` is one chunk, a larger one is windowed with `oversize_window`. Nothing is ever truncated.
- **When the fallback runs.** A unit within the fallback's size (`chunk_size`, or `max_tokens` for semantic) is one chunk. Only an oversized unit is split by `reset_at` segments and then windowed (or semantically split). This follows §4.5.4: "a fallback chunker runs only on oversized units", and the pseudocode's segment-then-window applies inside the fallback.
- **`heading_prefix(components, max_tokens=30)`** joins with ` > `. Over `max_tokens`, it drops leading components until the prefix fits. A single component still too long is cut after its `max_tokens`-th token, then back to the last whitespace (a hard cut at the token boundary if there is none).

### 4.2 Markdown (`chunk_markdown(text, file_label, chunking)`)

- Lines are numbered from 1. Fences: a line whose stripped form starts with three or more backticks, or `~~~`, toggles the fence, and the closing marker must use the same character. Inside a fence a line is content, never a heading or reset, and the markers stay in the text.
- Outside fences, `^#{1,3}\s` starts a section with the H1 > H2 > H3 path (a new H2 clears H3, a new H1 clears both). `^#{4,6}\s` is a sub-heading, used only by `reset_at: subheading`, where it starts a new segment that includes the sub-heading line.
- A section's display text is the lines after its heading line up to the next section heading. Lines before the first heading form a section with path `[]`. The section's heading line belongs to the prefix, not the text, so the cited `#L` range starts at the first content line. Leading and trailing blank lines are trimmed and the line numbers adjusted, and a section with no non-blank lines is dropped.
- Prefix `heading_prefix([file_label, H1, H2, H3])`. M4 passes the file's basename as `file_label` (a full `eval/sample_data/repo/...` path alone would use most of the 30 tokens). `rel_path` goes in metadata, not in the prefix.
- `line_start`/`line_end` come from the chunk's first and last characters. Test: for every chunk, `chunk.text` is a substring of `"\n".join(lines[line_start-1:line_end])`, and that range's first and last lines each overlap the text.

### 4.3 HTML (`chunk_html(html, chunk_type, chunking, embed=None)`, async)

- BeautifulSoup with `lxml`. Remove `script, style, noscript, nav, header, footer, [role=navigation], .sr-only`. The root is `<main>`, else `#main-content`, else `<body>`, else the document.
- Walk the tree in document order with a line buffer. `h1`–`h3` flush and start a new section with the H1 > H2 > H3 path (heading text whitespace-collapsed). Block elements flush before and after: `p, li, tr, div, h4–h6, br, ul, ol, table, thead, tbody, section, article, blockquote, pre, dl, dt, dd, figure, figcaption, form`. `td`/`th` add a space separator. Every display line is whitespace-collapsed (`\s+` → one space, including `&nbsp;`) and stripped, and empties are dropped.
- A section's unit text is its display lines joined by `\n`, with the heading itself only in the prefix. Prefix `heading_prefix([H1, H2, H3])`, no file label: the page is one resource.
- The fallback is the type's (`syllabus`, `schedule`). For `semantic`, `embed` is required, and passing `None` is a `ValueError`. Sliding-window profiles never embed at chunk time.
- Text fragments come from the chunk's display text (§5), which is the rendered text, so U8 can check them against the real page in M5.

### 4.4 PDF (`pdf_pages(data)` and `chunk_pdf(pages, file_label, chunking)`)

- `pdf_pages(data: bytes) -> list[str]` uses `pypdf.PdfReader(io.BytesIO(data))` and `extract_text()` per page (`""` on a page that fails). The 500-page cap and the 60 s thread timeout belong to the fetcher (§4.5.3) and land in M4.
- The structural unit is the whole file: the non-empty pages joined by `\n`, with a character → page map. `reset_at: page` makes each page its own segment, so no chunk crosses a page. With `none`, windows stream across pages and `page_end` can exceed `page_start`.
- Prefix `heading_prefix([f"{file_label} p.{page_start}", first non-empty line of page_start])`, title `f"{file_label} p.{page_start}"`.
- The baseline window is 200/40 and slides are short, so under `sliding-window` the 19-page sample is one stream cut into a few windows. Under `type-tailored` (120/30, page reset), no chunk crosses a page. Slides 7, 17 and 18 are longer than 120 tokens and give 2 chunks each.

### 4.5 Historical Q&A (`qa_answer(question, posts)` and `chunk_qa(...)`)

- `qa_answer(question, posts) -> post | None` is pure and duck-typed on `status`, `kind`, `author_role`, `is_accepted` and `created_at`, so M4 can pass ORM rows and tests can pass simple objects. It returns the accepted ANSWER whose author is not AI. Failing that, if the question is CLOSED, it returns the latest STAFF ANSWER (ties go to the higher id). Otherwise it returns `None`. AI posts never qualify, even when accepted.
- `chunk_qa(question_id, title, body, answer, chunking)`: the text is `f"Question: {title}\n{body}\n\nAnswer: {answer}"`. When it is ≤ 222 tokens (`QA_MAX_TOKENS`, fixed for every profile) it is one chunk with no prefix. Otherwise it is windowed with `chunking["default"]`, each window prefixed `heading_prefix([f"Question: {title}"])`. The title is the thread title.

## 5. Citations (`citations.py`)

- **`encode_word(w)`** mirrors `encodeURIComponent`: `urllib.parse.quote(w, safe="!'()*~")` (UTF-8, so `—` → `%E2%80%94`), then `-` → `%2D`.
- **`text_fragment(display_text)`** takes the non-empty stripped lines and splits them on whitespace into words. A single line of ≤ 12 words gives `text=<words joined by %20>`. Otherwise `text=<first ≤6 words of the first line>,<last ≤6 words of the last line>`, including a single line of more than 12 words. Empty text is a `ValueError`.
- **`encode_path(p)`** is `quote(p, safe="/")`: `/ . - _` (and `~`) stay literal and spaces become `%20`.
- **Builders:**
  - `blob_url(web, sha, path, line_start, line_end)` gives `WEB/-/blob/SHA/PATH?plain=1#L<a>-<b>`, or `#L<a>` when a = b.
  - `raw_pdf_url(web, sha, path, page)` gives `WEB/-/raw/SHA/PATH#page=<n>`.
  - `gitlab_html_url(web, sha, path, fragment)` gives `WEB/-/blob/SHA/PATH#:~:text=…`.
  - `web_page_url(url, fragment)` gives the registered URL with any existing `#…` removed, plus `#:~:text=…`.
  - `thread_url(frontend_url, course_id, question_id)` gives `FRONTEND_URL/student/questions/<qid>?course=<cid>`, with any trailing `/` on `FRONTEND_URL` stripped.
  - `upload_url(resource_id, path, suffix, base, in_zip)`:
    - with a base, a zip joins `base.rstrip("/") + "/" + encode_path(path)`, and a single file uses the base as is;
    - a markdown suffix gets `?plain=1` inserted before `#L` when the base contains `/-/blob/`;
    - with no base, the result is `upload://<resource_id>/<encode_path(path)><suffix>`.
- **`CitationContext`** (a frozen dataclass) describes where one resource's chunks come from:
  - `kind`: `gitlab`, `web`, `upload` or `internal`;
  - `web`, `sha`, `url`, `base`, `in_zip`, `resource_id`, `course_id`, `frontend_url`.

  `source_url(chunk, ctx, rel_path)` dispatches by `chunk.chunk_type` and `ctx.kind`, so M4's job code never builds a URL by hand.
- **IDs:**
  - `content_hash(embedded_text)` is the sha256 hex.
  - `assign_ids(chunks, resource_id, rel_path)` returns `(chunk_id, content_hash)` per chunk, in order.
  - `dup_ordinal` counts earlier chunks with the same `content_hash` in that file.
  - `chunk_id = sha256(f"{resource_id}|{rel_path or ''}|{content_hash}|{dup_ordinal}")`.
- **`chunk_metadata(...)`** returns flat scalars per §4.1.2 and omits `None` values, since Chroma rejects null. `ingest_job_id` is a parameter.

## 6. Tests (written first)

`test_chunking.py`:
- Tokenizer:
  - no truncation (> 128 tokens);
  - offsets slice back to source text;
  - `[CLS]`/`[SEP]` not counted.
- `window`:
  - `len ≤ size` gives one range;
  - exact starts for 10 tokens with size 4 and overlap 1;
  - the last window reaches the end.
- Whole-word expansion:
  - never splits a spaced word;
  - falls back to token boundaries on a 300-character unspaced string and stays within `size + 2`;
  - with `chunk_overlap = 0`, the windows cover every source character;
  - chunk text is always a substring of the source.
- `heading_prefix`:
  - drops leading components;
  - cuts a single long component at a word;
  - always ≤ 30 tokens.
- Markdown (synthetic):
  - a fence containing `# not a heading` doesn't start a section;
  - `~~~` fences;
  - an unclosed fence runs to the end of the file;
  - windowed line ranges are exact;
  - the sub-heading reset starts segments at `####`, and only when the section is oversized;
  - text before the first heading forms its own section.
- Markdown (real):
  - `realtime.md`'s fenced `# Scripted …` lines stay inside "Seeing it live";
  - every chunk's line range is exact (see the invariant in §4.2).
- HTML (real `syllabus.html`/`schedule.html`):
  - no nav, `sr-only` or footer text ("opens in new tab", "Toggle navigation");
  - one section per h1–h3, with the section count equal to the number of non-empty h1–h3 sections;
  - the schedule prefix is truncated to ≤ 30 tokens and keeps the day heading;
  - `Late Policy — Slip Days:` is one display line;
  - `&nbsp;` is collapsed.
- Semantic (stub embedder):
  - splits exactly at the stubbed similarity drops;
  - an oversized span is windowed and not truncated (the concatenated chunks cover every sentence);
  - `embed=None` raises.
- PDF (real `slides.pdf`):
  - 19 pages;
  - under `type-tailored`, every page has a chunk, no chunk crosses a page, and only pages 7, 17 and 18 split;
  - the `sliding-window` `page_start`s are monotonic;
  - the prefix contains the slide title.
- Q&A:
  - `qa_answer` selection matrix: accepted student, accepted AI (excluded), closed with a staff answer, closed with neither, open unaccepted, latest staff answer;
  - a 223+-token pair is windowed and every window starts with `Question: <title>`;
  - a 222-token pair is a single chunk.
- On every sample file under every preset:
  - non-empty chunks;
  - `count_tokens(embedded_text) ≤ MAX_INPUT_TOKENS[model] − 2`;
  - unique chunk IDs;
  - every ground-truth `expected_source_section` (split on ` / `, whitespace-normalised) appears in some chunk's `embedded_text` for that file;
  - `sliding-window` and `bge-small` chunks are byte-identical.

`test_citations.py`:
- Fragments:
  - `-` → `%2D`;
  - em dash → `%E2%80%94`;
  - `,` and `&` encoded;
  - a one-line chunk of ≤ 12 words gives `text=` with no comma;
  - a 13-word single line gives start and end terms;
  - a multi-line chunk takes the first 6 and last 6 words.
- Builders:
  - blob `?plain=1#L3-9` and `#L4`;
  - raw `#page=14`;
  - web URL with an existing `#x` replaced;
  - thread URL with a trailing slash;
  - upload with and without a base, a zip join, and `?plain=1` inserted for a `/-/blob/` base.
- Ground truth: every `expected_source` path is a substring of the URL `source_url` builds for that file (the blob, raw and GitLab-HTML forms).
- IDs:
  - stable across runs;
  - a heading rename changes the ID;
  - two identical texts in one file get different IDs, `dup_ordinal` 0 and 1.
- Metadata has no `None` values and contains exactly the keys present for each type.

`test_presets.py`:
- all four presets validate against their own model;
- `chunk_size` 240 with MiniLM fails;
- `semantic` on `repo_pdf` fails;
- `chunk_overlap == chunk_size` fails;
- `reset_at: page` on markdown fails;
- `sliding-window`, `embedding-alt` and `bge-small` share an identical `chunking`;
- `fallback_for` defaults.

## 7. Out of scope (M4/M5)

- Fetchers, zip safety, PDF limits and timeouts, Infinity `embed`, and the "model served" check;
- jobs and re-sync;
- selecting threads from MySQL (M4 calls `qa_answer` on ORM rows);
- the `limits` and `served` fields;
- U8, the browser check of fragments (M5).

## 8. Verification

- The three test files pass, together with the 86 existing unit tests.
- `ruff check` and `ruff format --check` are clean.
- A chunk-count table per preset on `eval/sample_data/` is recorded in this file, since §4.4.1 tunes sizes on chunk counts.
- The Docker image builds with the new requirements, and the backend imports `chunking` inside the container.

## 9. Goldfish plan review (fresh subagent) and how each finding was handled

| # | Finding | Outcome |
|---|---|---|
| 1 | **Blocker.** A fixed 2-token slack forces 16 of 45 windows on the real markdown to cut a word, since about 29% of tokens sit in words of 3 or more tokens | **Adopted.** Slack is now `2 + unused prefix budget`, and a side that still can't grow drops its cut word instead. Real line ranges are tested to start and end on word boundaries |
| 2 | **Blocker.** The "one chunk per page" test fails: slides 7, 17 and 18 exceed 120 tokens | **Adopted.** The test asserts no chunk crosses a page, every page has a chunk, and exactly 7, 17 and 18 split |
| 3 | No real schedule or markdown prefix is over 30 tokens | **Adopted.** Truncation is tested on synthetic headings. The real-file tests assert ≤ 30 tokens and that the h3 is kept |
| 4 | `reset_at: subheading` never fires: the sample markdown has no `####` (sub-topics are `**bold**` lines) | **Recorded** in design §4.4.1 "As built": type-tailored markdown is effectively a 150/30 window on this corpus. The rule is unchanged and kept by a synthetic test. Changing it is a tuning decision for before the eval |
| 5 | The budget test (`≤ max_input − 2`) can't catch a regression | **Adopted.** Each chunk is checked for prefix ≤ 30 and text ≤ the type's size + 2 + spare |
| 6 | Ground-truth tests need explicit skips and are weak | **Adopted.** Q&A and no-match questions are skipped by type. Markdown and schedule sections must appear in a chunk's **prefix**, other types in its whitespace-normalised text, and `P3 Released / Lecture 16` is matched part by part |
| 7 | Heading text must not insert separators (`Tue : Lecture 13`) | Already `get_text()` with no separator. **Test added** that expects `Thu: Lecture 13 — …` |
| 8 | `validate_chunking` gaps | **Adopted:** `default` is a plain window, unknown keys are rejected, and sizes must be ints |
| 9 | `assign_ids` scope for Q&A | **Adopted:** call it once per (resource, rel_path) group, with all threads together; `chunk_index` is the position in that list (docstring and README) |
| 10 | Async boundary: only `chunk_html` is async | **Kept.** Chunking all 8 sample files takes about 0.2 s, and M4 can run the sync chunkers in `to_thread`. The docstring now says `embed` batches the sentences, uses the profile's model and leaves out `query_instruction` |
| 11 | PDF page numbers, cut-off titles, double spaces | Original page numbers were already kept (tested with a blank page), and lines are whitespace-collapsed. The cut-off title on p.15 is accepted: the full title is in the text |
| 12 | A closing fence must be only fence characters | Already so; ```` ```js ```` inside a fence doesn't close it |
| 13 | Block-element list goes beyond the design's; `<header>` removal; banners | **Noted:** the list adds `ul, ol, table, section, …`, which are all block-level. `<header>` removal follows the design. The banner landing in the previous section is harmless |
| 14 | `upload_url` should drop the base's `#…` and not double `?plain=1` | **Adopted**, with a test |
| 15 | Tokenizer claims | Confirmed by the reviewer |
| 16 | Commit order | Each module is committed with its tests |

## 10. Results

- **Unit tests:** 190 pass, 104 of them new: `test_chunking` 59, `test_citations` 25, `test_presets` 20.
- **Lint:** `ruff check` (backend, scripts, tests/unit) and `ruff format --check` (backend, scripts, as in CI) are clean.
- **Docker:** the image builds with the pinned requirements (`tokenizers` 0.23.3, `beautifulsoup4` 4.15.0, `lxml` 6.1.3, `pypdf` 6.21.2), and inside it the tokenizer loads without truncation (500 tokens counted for 500 words).

Chunk counts on `eval/sample_data/` (semantic split with a stub embedder; real counts come from Infinity in M4):

| File | `sliding-window` (also `embedding-alt`, `bge-small`) | `type-tailored` |
|---|---|---|
| p1-side-scroller/instructions.md | 18 | 22 |
| p1-side-scroller/rubric.md | 14 | 14 |
| p2-buzzer/instructions.md | 31 | 39 |
| p2-buzzer/rubric.md | 15 | 17 |
| p2-buzzer/docs/realtime.md | 10 | 16 |
| web/syllabus.html | 31 | 42 |
| web/schedule.html | 50 | 56 |
| lecture-10/slides.pdf | 11 | 22 |
| **Total** | **180** | **228** |

The largest embedded chunk is 233 tokens, within MiniLM's 254 after `[CLS]`/`[SEP]`.

## 11. Goldfish diff review (fresh subagent) and how each finding was handled

| # | Finding | Outcome |
|---|---|---|
| 1 | **Bug.** A small multi-page PDF under `reset_at: page` became one chunk that crosses pages | **Fixed:** under a page reset, pages are always their own units. Test added |
| 2 | **Bug.** `splitlines()` also breaks on `\u2028`, `\x0c` and similar, so markdown line numbers drift from GitLab's | **Fixed:** the text is split on `\n` only, with any trailing `\r` removed. Tests added for CRLF and `\u2028` |
| 3 | **Bug.** A zip base with a query had the path appended after the query | **Fixed:** the query is split off and put back after the path, and `plain=1` is never doubled. Test added |
| 4 | Dropping a cut word can lose a word longer than the overlap | **Fixed:** a cut word is dropped only if the neighbouring window's raw span covers it; otherwise the exact token boundary is kept. Coverage test with a long link at 58 positions |
| 5 | Deep HTML nesting raises `RecursionError` | **Fixed:** it is raised as `ValueError`, so M4 marks the resource FAILED |
| 6 | A UTF-8 BOM hides the first heading; HTML bytes without a charset | **Fixed** (BOM stripped). **M4:** the fetcher decodes using the HTTP charset |
| 7 | A long first line on a PDF page pushes out the `file p.N` label | **Fixed:** the label is always kept and only the line is shortened. Test added |
| 8 | Table rows: a fragment spanning cells won't highlight | **Noted** for U8 (M5); the sample HTML has no tables |
| 9 | The parsing libraries are unpinned, so an upgrade changes chunk IDs | **Pinned** to the tested versions |
| 10 | A non-object `per_type` value raises `AttributeError` | **Fixed:** it raises `ValueError`. Test added |
| 11 | `Chunk.title` used the unstripped title | **Fixed** |
| 12 | Headings indented by 1–3 spaces aren't detected | **Fixed**, with a test |
| 13 | Coverage tests never reached the word-dropping path | **Fixed** by the test in #4 |
| 14 | The identical-chunks test passes trivially | **Kept** as a guard that the three configs stay equal and the chunkers stay model-independent |
| 15 | No upload HTML or PDF `source_url` test; a PDF with a blob base won't jump to the page | **Fixed:** a `/-/blob/` base is rewritten to `/-/raw/` for `#page=`. Tests added |

Chunk counts and the largest chunk are unchanged after these fixes.
