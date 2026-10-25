"""Fetchers: GitLab URL parsing, git env, token scrubbing, the repository walk,
PDF limits and error mapping (design-rag.md §4.5.2, §4.5.3, §4.6)."""

import base64
import json
import os
import shutil
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.rag import fetchers
from app.services.rag.fetchers import (
    FetchError,
    fetch,
    git_env,
    parse_gitlab_file_url,
    parse_repo_url,
    scrub,
    walk_repo,
)
from app.services.rag.ssrf import FetchResult

HOST = "git.doit.wisc.edu"
PROJECT = "cdis/cs/courses/aicoding/fa26/student-repos/p3/qna-74"
WEB = f"https://{HOST}/{PROJECT}"
SHA = "0123456789abcdef0123456789abcdef01234567"
TOKEN = "glpat-secretsecret123"


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setattr(fetchers.settings, "GITLAB_TOKEN", TOKEN)
    monkeypatch.setattr(fetchers.settings, "GITLAB_HOST", HOST)
    return TOKEN


# URL parsing


def test_parse_gitlab_blob_and_raw_urls():
    blob = parse_gitlab_file_url(
        f"{WEB}/-/blob/main/eval/sample_data/web/syllabus.html"
    )
    assert (blob.web, blob.project, blob.ref, blob.path) == (
        WEB,
        PROJECT,
        "main",
        "eval/sample_data/web/syllabus.html",
    )
    raw = parse_gitlab_file_url(
        f"https://{HOST.upper()}./{PROJECT}/-/raw/{SHA}/a%20b.html"
    )
    assert (raw.ref, raw.path) == (SHA, "a b.html")


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/x/-/blob/main/a.html",  # not GITLAB_HOST
        f"{WEB}/-/tree/main/eval",
        f"{WEB}",
    ],
)
def test_non_file_urls_are_not_gitlab_files(url):
    assert parse_gitlab_file_url(url) is None


@pytest.mark.parametrize(
    "url",
    [f"{WEB}/-/blob/main/", f"{WEB}/-/blob/main", f"{WEB}/-/blob/main/a/../b.html"],
)
def test_bad_gitlab_file_paths_are_errors(url):
    with pytest.raises(ValueError):
        parse_gitlab_file_url(url)


def test_parse_repo_url():
    assert parse_repo_url(f"{WEB}.git/").web == WEB
    assert parse_repo_url(f"https://{HOST.upper()}/{PROJECT}").host == HOST
    for bad in (
        f"http://{HOST}/{PROJECT}",
        f"{WEB}?ref=main",
        f"{WEB}#readme",
        f"https://user:pw@{HOST}/{PROJECT}",
        f"https://{HOST}/",
    ):
        with pytest.raises(ValueError):
            parse_repo_url(bad)


# git env and scrubbing


def _config(env: dict) -> dict:
    n = int(env["GIT_CONFIG_COUNT"])
    return {env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"] for i in range(n)}


def test_git_env_sends_the_token_only_to_gitlab(token):
    env = git_env(HOST)
    config = _config(env)
    assert config["protocol.allow"] == "never"
    assert config["protocol.https.allow"] == "always"
    assert config["http.followRedirects"] == "false"
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    basic = base64.b64encode(f"oauth2:{TOKEN}".encode()).decode()
    assert config["http.extraHeader"] == f"Authorization: Basic {basic}"
    assert "http.extraHeader" not in _config(git_env("github.com"))
    # Nothing inherited from the backend's environment (MySQL, JWT keys, token)
    assert "GITLAB_TOKEN" not in env and "MYSQL_PASSWORD" not in env


def test_git_env_without_token_has_no_header(monkeypatch):
    monkeypatch.setattr(fetchers.settings, "GITLAB_TOKEN", "")
    assert "http.extraHeader" not in _config(git_env(HOST))


def test_scrub_removes_every_form_of_the_token(token):
    basic = base64.b64encode(f"oauth2:{TOKEN}".encode()).decode()
    text = (
        f"fatal: https://oauth2:{TOKEN}@{HOST}/x failed; header Authorization: Basic "
        f"{basic}; raw {TOKEN}; other glpat-abcdefABCDEF0123"
    )
    out = scrub(text)
    assert TOKEN not in out and basic not in out
    assert "oauth2:" not in out and "glpat-" not in out


# Fetching a GitLab file


def _resource(**kw):
    defaults = dict(
        id=7,
        course_id=3,
        resource_type="syllabus",
        source_kind="url",
        url=None,
        git_ref=None,
        subpath=None,
        upload_path=None,
        citation_base_url=None,
    )
    return SimpleNamespace(**{**defaults, **kw})


async def test_gitlab_file_fetch_uses_the_files_api(token, monkeypatch):
    calls = []

    async def fake_get(url, **kw):
        calls.append((url, kw))
        body = json.dumps(
            {"content": base64.b64encode(b"<h1>S</h1>").decode(), "last_commit_id": SHA}
        )
        return FetchResult(url, 200, {}, body.encode())

    monkeypatch.setattr(fetchers, "guarded_get", fake_get)
    res = _resource(url=f"{WEB}/-/blob/main/eval/sample_data/web/syllabus.html")
    fetched = await fetch(res)
    url, kw = calls[0]
    assert url == (
        f"https://{HOST}/api/v4/projects/{PROJECT.replace('/', '%2F')}"
        "/repository/files/eval%2Fsample_data%2Fweb%2Fsyllabus.html?ref=main"
    )
    assert kw["headers"] == {"PRIVATE-TOKEN": TOKEN}
    assert kw["allow_redirects"] is False
    [doc] = fetched.documents
    assert (doc.rel_path, doc.kind, doc.data) == (
        "eval/sample_data/web/syllabus.html",
        "html",
        b"<h1>S</h1>",
    )
    assert (fetched.ctx.kind, fetched.ctx.web, fetched.ctx.sha) == ("gitlab", WEB, SHA)
    assert fetched.commit_sha == SHA


async def test_gitlab_404_is_a_fetch_error(token, monkeypatch):
    async def fake_get(url, **kw):
        raise FetchError(f"HTTP 404 from {HOST}")

    monkeypatch.setattr(fetchers, "guarded_get", fake_get)
    with pytest.raises(FetchError, match="not found"):
        await fetch(_resource(url=f"{WEB}/-/blob/main/missing.html"))


async def test_bad_gitlab_json_is_a_fetch_error(token, monkeypatch):
    async def fake_get(url, **kw):
        return FetchResult(url, 200, {}, b'{"content": "!!!", "last_commit_id": "x"}')

    monkeypatch.setattr(fetchers, "guarded_get", fake_get)
    with pytest.raises(FetchError):
        await fetch(_resource(url=f"{WEB}/-/blob/main/a.html"))


@pytest.mark.parametrize(
    "exc",
    [socket.gaierror("dns"), ConnectionError("refused"), TimeoutError(), KeyError("x")],
)
async def test_every_failure_becomes_a_scrubbed_fetch_error(token, monkeypatch, exc):
    async def fake_get(url, **kw):
        raise exc

    monkeypatch.setattr(fetchers, "guarded_get", fake_get)
    with pytest.raises(FetchError) as info:
        await fetch(_resource(url="https://example.com/s.html"))
    assert str(info.value)
    assert TOKEN not in str(info.value)


async def test_web_page_keeps_the_registered_url_and_charset(monkeypatch):
    async def fake_get(url, **kw):
        return FetchResult(url + "?moved", 200, {}, b"<p>x</p>", "iso-8859-1")

    monkeypatch.setattr(fetchers, "guarded_get", fake_get)
    fetched = await fetch(_resource(url="https://example.com/s.html"))
    assert fetched.ctx.kind == "web" and fetched.ctx.url == "https://example.com/s.html"
    [doc] = fetched.documents
    assert doc.charset == "iso-8859-1" and doc.rel_path is None


# Uploads


async def test_upload_single_file_and_zip(tmp_path):
    md = tmp_path / "notes.md"
    md.write_bytes(b"# n")
    fetched = await fetch(
        _resource(resource_type="repository", source_kind="upload", upload_path=str(md))
    )
    assert [(d.rel_path, d.kind) for d in fetched.documents] == [("notes.md", "md")]
    assert fetched.ctx.kind == "upload" and fetched.ctx.in_zip is False

    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("top/a.md", "# a")
        zf.writestr("top/d/s.pdf", "%PDF")
    z = tmp_path / "repo.zip"
    z.write_bytes(buf.getvalue())
    fetched = await fetch(
        _resource(
            resource_type="repository",
            source_kind="upload",
            upload_path=str(z),
            citation_base_url="https://x.test/b/",
        )
    )
    assert [(d.rel_path, d.kind) for d in fetched.documents] == [
        ("a.md", "md"),
        ("d/s.pdf", "pdf"),
    ]
    assert fetched.ctx.in_zip is True and fetched.ctx.base == "https://x.test/b/"


async def test_missing_upload_is_a_fetch_error(tmp_path):
    with pytest.raises(FetchError):
        await fetch(
            _resource(source_kind="upload", upload_path=str(tmp_path / "gone.html"))
        )


# Repository walk


@pytest.fixture
def repo(tmp_path) -> Path:
    root = tmp_path / "repo"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("# secret")
    files = {
        "top.md": "# top",
        ".git/HEAD.md": "x",
        "node_modules/pkg/readme.md": "x",
        "eval/repo/a.md": "# a",
        "eval/repo/sub/b.PDF": "%PDF",
        "eval/repo/notes.txt": "no",
    }
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    os.symlink(outside / "secret.md", root / "eval/repo/link.md")
    os.symlink(outside, root / "eval/repo/linkdir")
    os.symlink(outside, root / "escape")
    return root


def test_walk_skips_symlinks_git_and_node_modules(repo):
    docs = walk_repo(repo, "eval/repo")
    assert [(d.rel_path, d.kind) for d in docs] == [
        ("eval/repo/a.md", "md"),
        ("eval/repo/sub/b.PDF", "pdf"),
    ]
    assert [d.rel_path for d in walk_repo(repo, None)] == [
        "eval/repo/a.md",
        "eval/repo/sub/b.PDF",
        "top.md",
    ]


def test_walk_refuses_missing_and_escaping_subpaths(repo):
    with pytest.raises(FetchError, match="subpath"):
        walk_repo(repo, "nope")
    with pytest.raises(FetchError, match="subpath"):
        walk_repo(repo, "escape")


def test_walk_file_limit(repo, monkeypatch):
    monkeypatch.setattr(fetchers, "MAX_REPO_FILES", 1)
    with pytest.raises(FetchError, match="files"):
        walk_repo(repo, None)


async def test_clone_passes_ref_and_cleans_up(token, repo, monkeypatch, tmp_path):
    monkeypatch.setattr(fetchers.settings, "CLONE_TMP_DIR", str(tmp_path))
    seen = {}

    async def fake_resolve(host, port):
        return "93.184.216.34"

    async def fake_git(args, env, watch=None):
        if args[0] == "clone":
            seen["args"], seen["env"] = args, env
            dest = Path(args[-1])
            shutil.rmtree(dest)
            shutil.copytree(repo, dest, symlinks=True)
            return ""
        return SHA + "\n"

    monkeypatch.setattr(fetchers, "resolve_public", fake_resolve)
    monkeypatch.setattr(fetchers, "_run_git", fake_git)
    res = _resource(
        resource_type="repository",
        url=f"{WEB}.git",
        git_ref="main",
        subpath="eval/repo",
    )
    fetched = await fetch(res)
    assert seen["args"][:6] == [
        "clone",
        "--depth",
        "1",
        "--single-branch",
        "--no-tags",
        "--branch",
    ]
    assert seen["args"][6:9] == ["main", "--", f"{WEB}.git"]
    assert all(TOKEN not in a for a in seen["args"])
    assert fetched.commit_sha == SHA
    assert (fetched.ctx.kind, fetched.ctx.web, fetched.ctx.sha) == ("gitlab", WEB, SHA)
    assert [d.rel_path for d in fetched.documents] == [
        "eval/repo/a.md",
        "eval/repo/sub/b.PDF",
    ]
    assert not [p for p in tmp_path.iterdir() if p.name.startswith("qna-clone-")]


async def test_clone_failure_is_scrubbed(token, monkeypatch, tmp_path):
    monkeypatch.setattr(fetchers.settings, "CLONE_TMP_DIR", str(tmp_path))
    basic = base64.b64encode(f"oauth2:{TOKEN}".encode()).decode()

    async def fake_resolve(host, port):
        return "93.184.216.34"

    async def fake_git(args, env, watch=None):
        raise FetchError(f"git clone failed: Authorization: Basic {basic} rejected")

    monkeypatch.setattr(fetchers, "resolve_public", fake_resolve)
    monkeypatch.setattr(fetchers, "_run_git", fake_git)
    with pytest.raises(FetchError) as info:
        await fetch(_resource(resource_type="repository", url=WEB))
    assert basic not in str(info.value) and TOKEN not in str(info.value)
    assert not [p for p in tmp_path.iterdir() if p.name.startswith("qna-clone-")]


async def test_run_git_reports_stderr_and_kills_on_timeout(monkeypatch, tmp_path):
    with pytest.raises(FetchError, match="not a git command|git"):
        await fetchers._run_git(["no-such-subcommand"], {"PATH": os.environ["PATH"]})
    monkeypatch.setattr(fetchers, "GIT_TIMEOUT_S", 0.5)
    with pytest.raises(FetchError, match="timed out"):
        # `git daemon` style long runner: `git var` is instant, so use a hook-less sleep
        await fetchers._run_git(
            ["-c", "alias.zz=!sleep 5", "zz"], {"PATH": os.environ["PATH"]}
        )


# PDF limits


async def test_pdf_page_limit(monkeypatch):
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=72, height=72)
    import io

    buf = io.BytesIO()
    writer.write(buf)
    assert await fetchers.parse_pdf(buf.getvalue()) == ["", "", ""]
    monkeypatch.setattr(fetchers, "MAX_PDF_PAGES", 2)
    with pytest.raises(FetchError, match="pages"):
        await fetchers.parse_pdf(buf.getvalue())
    with pytest.raises(FetchError):
        await fetchers.parse_pdf(b"not a pdf")
