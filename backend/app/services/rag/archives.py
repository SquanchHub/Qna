"""Zip extraction and upload file names (design-rag.md §4.5.3).

``read_zip`` never writes to disk. It returns the ``.md`` and ``.pdf`` members
in memory, after checking every entry. It runs at upload, so a bad archive is
rejected with 422, and again at each sync, which reads the stored zip.
"""

from __future__ import annotations

import io
import posixpath
import re
import stat
import zipfile
import zlib

ALLOWED_SUFFIXES = (".md", ".pdf")
MAX_ENTRIES = 2000
MAX_TOTAL_BYTES = 200 * 1024 * 1024
_READ_CHUNK = 65536
_DRIVE = re.compile(r"^[A-Za-z]:")
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")
MAX_FILENAME = 100


class UnsafeArchive(ValueError):
    """The zip has an entry we refuse to extract."""


def _check_name(name: str) -> None:
    if "\\" in name or "\x00" in name:
        raise UnsafeArchive(f"unsafe path in archive: {name!r}")
    if name.startswith("/") or _DRIVE.match(name):
        raise UnsafeArchive(f"absolute path in archive: {name!r}")
    if ".." in name.split("/"):
        raise UnsafeArchive(f"path escapes the archive: {name!r}")


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK(info.external_attr >> 16)


def _read_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo, budget: int) -> bytes:
    """Read one member, counting actual bytes (a header can lie about size)."""
    out, total = [], 0
    try:
        with zf.open(info) as member:
            while chunk := member.read(_READ_CHUNK):
                total += len(chunk)
                if total > budget:
                    raise UnsafeArchive("archive too large: over 200 MB decompressed")
                out.append(chunk)
    # A corrupt deflate stream, or a method zipfile lacks (Deflate64 from
    # Windows Explorer), surfaces here rather than as BadZipFile
    except (zlib.error, NotImplementedError, EOFError, OSError) as exc:
        raise UnsafeArchive(f"unreadable entry in archive: {info.filename!r}") from exc
    return b"".join(out)


def _strip_shared_top(paths: list[str]) -> list[str]:
    tops = {p.split("/", 1)[0] for p in paths}
    if len(tops) == 1 and all("/" in p for p in paths):
        return [p.split("/", 1)[1] for p in paths]
    return paths


def read_zip(data: bytes) -> list[tuple[str, bytes]]:
    """The archive's .md and .pdf files as (path, bytes), sorted by path.

    Raises UnsafeArchive for absolute or escaping paths, backslashes, symlinks,
    encrypted entries, more than MAX_ENTRIES entries or MAX_TOTAL_BYTES
    decompressed. Raises zipfile.BadZipFile if it isn't a zip.
    """
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        infos = zf.infolist()
        if len(infos) > MAX_ENTRIES:
            raise UnsafeArchive(f"archive has more than {MAX_ENTRIES} entries")
        for info in infos:
            _check_name(info.filename)
            if _is_symlink(info):
                raise UnsafeArchive(f"symlink in archive: {info.filename!r}")
            if info.flag_bits & 0x1:
                raise UnsafeArchive(f"encrypted entry in archive: {info.filename!r}")

        kept: list[tuple[str, bytes]] = []
        budget = MAX_TOTAL_BYTES
        for info in infos:
            name = info.filename
            if info.is_dir() or name.split("/", 1)[0] == "__MACOSX":
                continue
            if not name.lower().endswith(ALLOWED_SUFFIXES):
                continue
            body = _read_member(zf, info, budget)
            budget -= len(body)
            kept.append((posixpath.normpath(name), body))

    paths = _strip_shared_top([p for p, _ in kept])
    return sorted(zip(paths, (b for _, b in kept)), key=lambda item: item[0])


def safe_filename(name: str) -> str:
    """A storage-safe basename: [A-Za-z0-9._-] only, at most 100 characters,
    extension kept. Nothing left of the stem gives ``upload<ext>``."""
    base = re.split(r"[\\/]", name)[-1]
    stem, dot, ext = base.rpartition(".")
    if not dot:
        stem, ext = base, ""
    ext = _UNSAFE_CHARS.sub("_", ext)[:10]
    suffix = f".{ext}" if ext else ""
    stem = _UNSAFE_CHARS.sub("_", stem).strip(".")
    if not stem:
        stem = "upload"
    return stem[: MAX_FILENAME - len(suffix)] + suffix
