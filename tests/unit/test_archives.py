"""Zip safety and upload file names (design-rag.md §4.5.3)."""

import io
import zipfile

import pytest

from app.services.rag import archives
from app.services.rag.archives import UnsafeArchive, read_zip, safe_filename


def _zip(entries) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return buf.getvalue()


def _symlink_entry(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = 0o120777 << 16
    return info


@pytest.mark.parametrize(
    "name",
    ["../evil.md", "top/../../evil.md", "/abs/evil.md", "C:/evil.md", "dir\\evil.md"],
)
def test_unsafe_names_are_refused(name):
    with pytest.raises(UnsafeArchive):
        read_zip(_zip([("top/ok.md", b"# ok"), (name, b"# evil")]))


def test_symlink_is_refused():
    data = _zip(
        [("top/real.md", b"# real"), (_symlink_entry("top/link.md"), b"/etc/passwd")]
    )
    with pytest.raises(UnsafeArchive, match="symlink"):
        read_zip(data)


def test_encrypted_entry_is_refused():
    data = bytearray(_zip([("a.md", b"# a")]))
    # Set the encryption bit in the local and central headers
    for sig in (b"PK\x03\x04", b"PK\x01\x02"):
        at = data.index(sig)
        flag_at = at + (6 if sig == b"PK\x03\x04" else 8)
        data[flag_at] |= 0x1
    with pytest.raises(UnsafeArchive, match="encrypted"):
        read_zip(bytes(data))


def test_decompressed_size_counts_actual_bytes(monkeypatch):
    monkeypatch.setattr(archives, "MAX_TOTAL_BYTES", 1024)
    with pytest.raises(UnsafeArchive, match="too large"):
        read_zip(_zip([("a.md", b"a" * 600), ("b.md", b"b" * 600)]))


def test_lying_size_header_is_not_trusted():
    """zipfile stops at the declared size and then fails the CRC, so a header
    that understates the size can't smuggle extra bytes past the count."""
    data = bytearray(_zip([("a.md", b"a" * 5000)]))
    at = data.index(b"PK\x01\x02")
    data[at + 24 : at + 28] = (10).to_bytes(4, "little")
    with pytest.raises(zipfile.BadZipFile):
        read_zip(bytes(data))


def test_corrupt_deflate_stream_is_unsafe_archive():
    data = bytearray(_zip([("notes.md", b"# notes\n" + b"body text " * 500)]))
    start = data.index(b"notes.md") + len("notes.md")  # first byte of file data
    data[start + 5 : start + 40] = b"\xff" * 35
    with pytest.raises(UnsafeArchive, match="unreadable"):
        read_zip(bytes(data))


def test_unsupported_compression_method_is_unsafe_archive():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("notes.md", b"# notes")
    data = bytearray(buf.getvalue())
    # Mark the entry as Deflate64 (method 9) in the local and central headers
    local, central = data.index(b"PK\x03\x04"), data.index(b"PK\x01\x02")
    data[local + 8 : local + 10] = (9).to_bytes(2, "little")
    data[central + 10 : central + 12] = (9).to_bytes(2, "little")
    with pytest.raises(UnsafeArchive, match="unreadable"):
        read_zip(bytes(data))


def test_entry_count_limit(monkeypatch):
    monkeypatch.setattr(archives, "MAX_ENTRIES", 3)
    with pytest.raises(UnsafeArchive, match="entries"):
        read_zip(_zip([(f"{i}.md", b"x") for i in range(4)]))


def test_strips_one_shared_top_directory_and_filters_types():
    data = _zip(
        [
            ("top/notes.md", b"# n"),
            ("top/docs/slides.PDF", b"%PDF"),
            ("top/readme.txt", b"no"),
            ("__MACOSX/top/._notes.md", b"junk"),
            ("top/docs/", b""),
        ]
    )
    assert [p for p, _ in read_zip(data)] == ["docs/slides.PDF", "notes.md"]


def test_keeps_paths_without_a_single_shared_top():
    assert [p for p, _ in read_zip(_zip([("a/x.md", b"x"), ("b/y.md", b"y")]))] == [
        "a/x.md",
        "b/y.md",
    ]
    assert [p for p, _ in read_zip(_zip([("a/x.md", b"x"), ("y.md", b"y")]))] == [
        "a/x.md",
        "y.md",
    ]


def test_top_directory_holding_only_one_file_is_kept_as_its_name():
    # Stripping "top/" from a lone "top/x.md" is still the file name
    assert [p for p, _ in read_zip(_zip([("top/x.md", b"x")]))] == ["x.md"]


def test_not_a_zip():
    with pytest.raises(zipfile.BadZipFile):
        read_zip(b"not a zip")


@pytest.mark.parametrize(
    "name,expected",
    [
        ("notes.md", "notes.md"),
        ("../../etc/passwd.md", "passwd.md"),
        ("C:\\Users\\me\\my notes.md", "my_notes.md"),
        ("...md", "upload.md"),
        ("", "upload"),
        ("ünïcode.pdf", "_n_code.pdf"),
    ],
)
def test_safe_filename(name, expected):
    assert safe_filename(name) == expected


def test_safe_filename_keeps_extension_when_truncating():
    name = safe_filename("a" * 300 + ".pdf")
    assert len(name) <= 100 and name.endswith(".pdf")
