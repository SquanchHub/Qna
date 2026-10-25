"""Fetch a resource's source documents (design-rag.md §4.5.2, §4.5.3).

``fetch(resource)`` returns the documents plus the citation context, and maps
every failure (DNS, network, HTTP status, bad JSON, git errors, limits) to a
``FetchError`` whose message is scrubbed of the GitLab token, so callers can
store and show it. Historical Q&A is read from MySQL by the ingest job instead.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import io
import json
import os
import re
import shutil
import signal
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urlsplit

import structlog

from ...config import settings
from .archives import read_zip
from .chunking import pdf_pages
from .citations import CitationContext
from .ssrf import FetchError, guarded_get, resolve_public

logger = structlog.get_logger()

__all__ = ["FetchError", "fetch"]

MB = 1024 * 1024
GIT_TIMEOUT_S = 120.0
CLONE_MAX_BYTES = 500 * MB
MAX_REPO_FILES = 2000
MAX_REPO_BYTES = 200 * MB
MAX_PDF_PAGES = 500
PDF_TIMEOUT_S = 60.0
SKIPPED_DIRS = {".git", "node_modules"}
_SHA = re.compile(r"^[0-9a-f]{40}$")
_GLPAT = re.compile(r"glpat-[A-Za-z0-9_\-]+")
_BASIC = re.compile(r"(Authorization:\s*Basic\s+)\S+", re.IGNORECASE)
_USERINFO = re.compile(r"(https?://)[^/@\s]+@")
_MAX_ERROR = 500


@dataclass
class Document:
    rel_path: str | None
    data: bytes
    kind: str  # "md", "pdf" or "html"
    charset: str | None = None


@dataclass
class Fetched:
    documents: list[Document]
    ctx: CitationContext
    commit_sha: str | None


# Token handling


def scrub(text: str) -> str:
    """Remove the GitLab token in every form it could take in an error."""
    token = settings.GITLAB_TOKEN
    if token:
        basic = base64.b64encode(f"oauth2:{token}".encode()).decode()
        for secret in (f"oauth2:{token}", basic, token):
            text = text.replace(secret, "***")
    text = _BASIC.sub(r"\1***", text)
    text = _USERINFO.sub(r"\1***@", text)
    return _GLPAT.sub("***", text).replace("oauth2:", "***:")


def _host(host: str | None) -> str:
    return (host or "").strip().rstrip(".").lower()


def is_gitlab_host(host: str | None) -> bool:
    return _host(host) == _host(settings.GITLAB_HOST)


def git_env(host: str) -> dict[str, str]:
    """A minimal environment for git. Config comes only from GIT_CONFIG_*
    (never argv, URLs or .git/config), and the token header is added only for
    GITLAB_HOST."""
    config = [
        ("protocol.allow", "never"),
        ("protocol.https.allow", "always"),
        ("http.followRedirects", "false"),
        ("core.symlinks", "false"),
        ("core.hooksPath", "/dev/null"),
    ]
    if settings.GITLAB_TOKEN and is_gitlab_host(host):
        basic = base64.b64encode(f"oauth2:{settings.GITLAB_TOKEN}".encode()).decode()
        config.append(("http.extraHeader", f"Authorization: Basic {basic}"))
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": tempfile.gettempdir(),
        "LC_ALL": "C",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "/bin/true",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_COUNT": str(len(config)),
    }
    for i, (key, value) in enumerate(config):
        env[f"GIT_CONFIG_KEY_{i}"] = key
        env[f"GIT_CONFIG_VALUE_{i}"] = value
    return env


# URL parsing


@dataclass
class GitLabFile:
    web: str
    project: str
    ref: str
    path: str


@dataclass
class RepoUrl:
    web: str
    host: str


def parse_gitlab_file_url(url: str) -> GitLabFile | None:
    """``/<project>/-/(blob|raw)/<ref>/<file>`` on GITLAB_HOST, else None.

    The ref is the first segment after blob/ or raw/: a URL can't say where a
    ref containing "/" ends, so such branches must be named by tag or SHA.
    Raises ValueError for a GitLab file URL with no file or a ".." segment.
    """
    parts = urlsplit(url)
    if not is_gitlab_host(parts.hostname):
        return None
    project, sep, rest = parts.path.strip("/").partition("/-/")
    kind, _, rest = rest.partition("/")
    if not sep or kind not in ("blob", "raw") or not project:
        return None
    ref, _, path = rest.partition("/")
    path = unquote(path).strip("/")
    if not ref or not path:
        raise ValueError("GitLab file URL needs a ref and a file path")
    if ".." in path.split("/"):
        raise ValueError("GitLab file path may not contain '..'")
    project = unquote(project)
    host = _host(parts.hostname)
    return GitLabFile(f"https://{host}/{project}", project, unquote(ref), path)


def parse_repo_url(url: str) -> RepoUrl:
    """https only, no userinfo, query or fragment; trailing / and .git dropped."""
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise ValueError("repository URLs must use https")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise ValueError("repository URL may not contain credentials")
    if parts.query or parts.fragment:
        raise ValueError("repository URL may not have a query or fragment")
    path = parts.path.rstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    path = path.strip("/")
    host = _host(parts.hostname)
    if not host or not path:
        raise ValueError("repository URL needs a host and a project path")
    port = f":{parts.port}" if parts.port else ""
    return RepoUrl(f"https://{host}{port}/{path}", host)


# Upload


def _kind(name: str, resource_type: str) -> str:
    if resource_type in ("syllabus", "schedule"):
        return "html"
    return "pdf" if name.lower().endswith(".pdf") else "md"


async def _fetch_upload(resource) -> Fetched:
    path = Path(resource.upload_path or "")
    try:
        data = await asyncio.to_thread(path.read_bytes)
    except OSError as exc:
        raise FetchError("uploaded file is missing") from exc
    in_zip = path.suffix.lower() == ".zip"
    if in_zip:
        try:
            members = await asyncio.to_thread(read_zip, data)
        except (zipfile.BadZipFile, ValueError) as exc:
            raise FetchError(f"stored archive is unreadable: {exc}") from exc
        docs = [
            Document(name, body, _kind(name, resource.resource_type))
            for name, body in members
        ]
    else:
        docs = [Document(path.name, data, _kind(path.name, resource.resource_type))]
    ctx = CitationContext(
        kind="upload",
        resource_id=resource.id,
        base=resource.citation_base_url,
        in_zip=in_zip,
    )
    return Fetched(docs, ctx, None)


# Web page and GitLab file


async def _fetch_web(resource) -> Fetched:
    result = await guarded_get(resource.url, max_bytes=settings.MAX_FETCH_MB * MB)
    doc = Document(None, result.body, "html", result.charset)
    ctx = CitationContext(kind="web", resource_id=resource.id, url=resource.url)
    return Fetched([doc], ctx, None)


async def _fetch_gitlab_file(resource, file: GitLabFile) -> Fetched:
    host = urlsplit(file.web).hostname
    api = (
        f"https://{host}/api/v4/projects/{quote(file.project, safe='')}"
        f"/repository/files/{quote(file.path, safe='')}?ref={quote(file.ref, safe='')}"
    )
    headers = {"PRIVATE-TOKEN": settings.GITLAB_TOKEN} if settings.GITLAB_TOKEN else {}
    try:
        # base64 inflates by 4/3, plus the JSON around it
        result = await guarded_get(
            api,
            headers=headers,
            max_bytes=settings.MAX_FETCH_MB * MB * 4 // 3 + 64 * 1024,
            allow_redirects=False,
        )
    except FetchError as exc:
        if "HTTP 404" in str(exc):
            raise FetchError(f"file not found on GitLab: {file.path}") from exc
        raise
    try:
        payload = json.loads(result.body)
        content = base64.b64decode(payload["content"], validate=True)
        sha = payload["last_commit_id"]
    except (ValueError, KeyError, TypeError, binascii.Error) as exc:
        raise FetchError("unexpected response from the GitLab files API") from exc
    if not isinstance(sha, str) or not _SHA.match(sha):
        raise FetchError("GitLab returned no commit id")
    if len(content) > settings.MAX_FETCH_MB * MB:
        raise FetchError(f"file larger than {settings.MAX_FETCH_MB} MB")
    doc = Document(file.path, content, "html")
    ctx = CitationContext(kind="gitlab", resource_id=resource.id, web=file.web, sha=sha)
    return Fetched([doc], ctx, sha)


# Repository clone


def _dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


async def _run_git(args: list[str], env: dict, watch: str | None = None) -> str:
    """Run git with a timeout (and a size cap on `watch`); returns stdout."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            env=env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # Its own process group, so a kill also stops git-remote-https
            start_new_session=True,
        )
    except OSError as exc:
        raise FetchError("git is not available") from exc
    output = asyncio.ensure_future(proc.communicate())
    deadline = asyncio.get_running_loop().time() + GIT_TIMEOUT_S
    try:
        while not output.done():
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise FetchError(f"git {args[0]} timed out after {GIT_TIMEOUT_S:g} s")
            await asyncio.wait({output}, timeout=min(1.0, remaining))
            if watch and not output.done():
                if await asyncio.to_thread(_dir_size, watch) > CLONE_MAX_BYTES:
                    raise FetchError(
                        f"repository larger than {CLONE_MAX_BYTES // MB} MB"
                    )
    except BaseException:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
        output.cancel()
        await proc.wait()
        raise
    stdout, stderr = output.result()
    if proc.returncode != 0:
        message = stderr.decode("utf-8", "replace").strip()
        raise FetchError(
            f"git {args[0]} failed: {scrub(message)[-_MAX_ERROR:] or proc.returncode}"
        )
    return stdout.decode("utf-8", "replace")


def walk_repo(root: Path, subpath: str | None) -> list[Document]:
    """*.md and *.pdf under root/subpath, rel_path relative to root. Symlinks,
    .git and node_modules are skipped, and nothing outside root is read."""
    root = root.resolve()
    start = (root / subpath) if subpath else root
    if start.is_symlink() or not start.is_dir():
        raise FetchError(f"subpath not found in repository: {subpath}")
    real = start.resolve()
    if real != root and root not in real.parents:
        raise FetchError(f"subpath not found in repository: {subpath}")

    docs: list[Document] = []
    total = 0
    for dirpath, dirnames, filenames in os.walk(real, followlinks=False):
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in SKIPPED_DIRS and not os.path.islink(os.path.join(dirpath, d))
        )
        for name in sorted(filenames):
            if not name.lower().endswith((".md", ".pdf")):
                continue
            path = Path(dirpath, name)
            if path.is_symlink() or not path.is_file():
                continue
            resolved = path.resolve()
            if root not in resolved.parents:
                continue
            size = path.stat().st_size
            if size > settings.MAX_ZIP_MB * MB:
                logger.warning(
                    "rag_repo_file_skipped", path=str(path.relative_to(root))
                )
                continue
            total += size
            if len(docs) >= MAX_REPO_FILES:
                raise FetchError(f"repository has more than {MAX_REPO_FILES} files")
            if total > MAX_REPO_BYTES:
                raise FetchError(f"repository files exceed {MAX_REPO_BYTES // MB} MB")
            rel = PurePosixPath(*path.relative_to(root).parts).as_posix()
            docs.append(Document(rel, path.read_bytes(), _kind(name, "repository")))
    return sorted(docs, key=lambda d: d.rel_path)


async def _clone_repository(resource) -> Fetched:
    repo = parse_repo_url(resource.url)
    await resolve_public(repo.host, 443)
    env = git_env(repo.host)
    os.makedirs(settings.CLONE_TMP_DIR, exist_ok=True)
    tmp = tempfile.mkdtemp(dir=settings.CLONE_TMP_DIR, prefix="qna-clone-")
    try:
        dest = os.path.join(tmp, "repo")
        os.mkdir(dest)
        args = ["clone", "--depth", "1", "--single-branch", "--no-tags"]
        if resource.git_ref:
            args += ["--branch", resource.git_ref]
        await _run_git([*args, "--", f"{repo.web}.git", dest], env, watch=tmp)
        sha = (await _run_git(["-C", dest, "rev-parse", "HEAD"], env)).strip()
        if not _SHA.match(sha):
            raise FetchError("could not read the cloned commit")
        docs = await asyncio.to_thread(walk_repo, Path(dest), resource.subpath)
    finally:
        await asyncio.to_thread(shutil.rmtree, tmp, True)
    ctx = CitationContext(kind="gitlab", resource_id=resource.id, web=repo.web, sha=sha)
    return Fetched(docs, ctx, sha)


# PDF


def _pdf_page_count(data: bytes) -> int:
    from pypdf import PdfReader

    return len(PdfReader(io.BytesIO(data)).pages)


def _parse_pdf_sync(data: bytes) -> list[str]:
    if _pdf_page_count(data) > MAX_PDF_PAGES:
        raise FetchError(f"PDF has more than {MAX_PDF_PAGES} pages")
    return pdf_pages(data)


async def _bounded(fn, data: bytes):
    # A timed-out thread can't be killed; it finishes in the background
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn, data), PDF_TIMEOUT_S)
    except TimeoutError as exc:
        raise FetchError("PDF parse timed out") from exc
    except FetchError:
        raise
    except Exception as exc:  # noqa: BLE001 - pypdf raises many types
        raise FetchError(f"unreadable PDF: {type(exc).__name__}") from exc


async def parse_pdf(data: bytes) -> list[str]:
    """Page texts, refusing more than MAX_PDF_PAGES pages or PDF_TIMEOUT_S."""
    return await _bounded(_parse_pdf_sync, data)


async def pdf_page_count(data: bytes) -> int:
    """For the upload check; raises FetchError on an unreadable PDF."""
    return await _bounded(_pdf_page_count, data)


# Dispatch


async def _fetch(resource) -> Fetched:
    if resource.source_kind == "upload":
        return await _fetch_upload(resource)
    if resource.resource_type == "repository":
        try:
            return await _clone_repository(resource)
        except ValueError as exc:
            raise FetchError(str(exc)) from exc
    try:
        file = parse_gitlab_file_url(resource.url)
    except ValueError as exc:
        raise FetchError(str(exc)) from exc
    if file is not None:
        return await _fetch_gitlab_file(resource, file)
    return await _fetch_web(resource)


async def fetch(resource) -> Fetched:
    """The resource's documents; every failure is a scrubbed FetchError."""
    try:
        return await _fetch(resource)
    except FetchError as exc:
        raise FetchError(scrub(str(exc))[:_MAX_ERROR]) from None
    except Exception as exc:  # noqa: BLE001 - one bad source must not crash the job
        detail = scrub(f"{type(exc).__name__}: {exc}")[:_MAX_ERROR]
        raise FetchError(f"fetch failed: {detail}") from None
