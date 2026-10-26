"""
Regenerate slides.pdf and repo.zip for the RAG integration tests.

Both outputs are committed. This script exists so they can be rebuilt
byte for byte (fixed zip timestamps, no PDF creation date) without any
third-party dependency. Run from anywhere:

    python tests/integration/fixtures/rag/make_fixtures.py

slides.pdf has three pages, each about 100 MiniLM tokens with its own
nonsense term on the first and last line. That matters for two tests: the
`sliding-window` preset streams PDF pages together (200/40 window, no
resets) while `type-tailored` windows each page alone (120/30, reset at
page), so the two profiles produce different chunk counts (test-plan C1);
and the term on a page's last line lets a test infer a chunk's start page
from its text (R6).

repo.zip holds top/notes.md and top/docs/slides.pdf under one shared
top-level directory, which ingestion must strip (design §4.5.3), plus
top/ignored.txt, whose term must never be retrievable because only .md and
.pdf are extracted.
"""

from __future__ import annotations

import pathlib
import zipfile

HERE = pathlib.Path(__file__).parent

PAGES = [
    (
        "Brambleflux",
        [
            "Brambleflux scheduling overview",
            "The Brambleflux scheduler assigns each lecture task to a worker queue.",
            "Queues are drained in priority order, and a task that waits longer",
            "than its deadline is promoted one level so it cannot starve forever.",
            "Workers report progress every few seconds so the scheduler can",
            "rebalance load when one queue grows much longer than the others.",
            "Summary: Brambleflux promotes waiting tasks instead of dropping them.",
        ],
    ),
    (
        "Zorvatic",
        [
            "Zorvatic caching rules",
            "A Zorvatic cache keeps the most recent answer for each query key.",
            "Entries expire after one hour, and any write to the underlying table",
            "invalidates every cached entry that was computed from that table.",
            "Readers that miss the cache recompute the value and store it again,",
            "so a burst of misses after an invalidation is expected and harmless.",
            "Summary: Zorvatic caches are invalidated by writes, not by size.",
        ],
    ),
    (
        "Plimquist",
        [
            "Plimquist review checklist",
            "Every Plimquist review checks naming, error handling and test coverage.",
            "Reviewers leave one comment per issue and mark blocking issues clearly,",
            "and the author must resolve every blocking comment before merging.",
            "Non-blocking suggestions may be deferred to a follow-up change when",
            "the author explains why in a reply on the merge request thread.",
            "Summary: Plimquist reviews block merges only on marked issues.",
        ],
    ),
]


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf() -> bytes:
    """A minimal PDF 1.4: one Helvetica font, one text stream per page."""
    objects: list[bytes] = []

    def add(body: str | bytes) -> int:
        objects.append(body.encode("latin-1") if isinstance(body, str) else body)
        return len(objects)

    catalog = add("")  # placeholder, filled once the pages object exists
    pages = add("")
    font = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    page_ids = []
    for _, lines in PAGES:
        ops = ["BT", "/F1 12 Tf", "16 TL", "72 720 Td"]
        for line in lines:
            ops.append(f"({_pdf_escape(line)}) Tj T*")
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
        content = add(
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
        )
        page_ids.append(
            add(
                f"<< /Type /Page /Parent {pages} 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {font} 0 R >> >> /Contents {content} 0 R >>"
            )
        )

    kids = " ".join(f"{p} 0 R" for p in page_ids)
    objects[catalog - 1] = f"<< /Type /Catalog /Pages {pages} 0 R >>".encode()
    objects[pages - 1] = (
        f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()
    )

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        catalog,
        xref,
    )
    return bytes(out)


def build_zip(notes: bytes, pdf: bytes) -> bytes:
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in [
            ("top/notes.md", notes),
            ("top/docs/slides.pdf", pdf),
            (
                "top/ignored.txt",
                b"The Gribbletoast rule: plain text files are never ingested.\n",
            ),
        ]:
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
    return buf.getvalue()


def main() -> None:
    pdf = build_pdf()
    (HERE / "slides.pdf").write_bytes(pdf)
    (HERE / "repo.zip").write_bytes(build_zip((HERE / "notes.md").read_bytes(), pdf))
    print(f"wrote {HERE / 'slides.pdf'} and {HERE / 'repo.zip'}")


if __name__ == "__main__":
    main()
