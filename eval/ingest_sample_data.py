#!/usr/bin/env python3
"""
Ingest eval/sample_data/ into one course under every T6 ingestion profile,
through the staff API's upload path (design-rag.md §11.1, eval/README.md).

Creates the profiles if missing, uploads syllabus.html, schedule.html and a
zip of sample_data/repo/ (each with a citation_base_url on the GitLab blob
path, so every chunk's source_url contains its repo-relative path, which the
harness's hit check needs), then syncs each profile in turn and waits.
Re-running reuses existing profiles and resources by name and title.

Usage (credentials resolve like compare_harness.py: HARNESS_* > .env > env):
    COURSE_ID=<id> HARNESS_BASE_URL=http://<ip> HARNESS_ADMIN_PASSWORD='…' \
        python eval/ingest_sample_data.py

Optional: PROFILES (default "sliding-window type-tailored embedding-alt").
"""

from __future__ import annotations

import io
import os
import sys
import time
import zipfile
from pathlib import Path

import httpx

EVAL_DIR = Path(__file__).parent
REPO_ROOT = EVAL_DIR.parent
SAMPLE = EVAL_DIR / "sample_data"
BLOB = (
    "https://git.doit.wisc.edu/cdis/cs/courses/aicoding/fa26/student-repos/p3/"
    "qna-74/-/blob/main/eval/sample_data"
)


def _env_value(key: str, default: str | None = None) -> str | None:
    """Same order as compare_harness.py: HARNESS_<KEY>, then .env, then env."""
    if f"HARNESS_{key}" in os.environ:
        return os.environ[f"HARNESS_{key}"]
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                if k.strip() == key:
                    return v.strip()
    return os.environ.get(key, default)


BASE_URL = _env_value("BASE_URL", "http://localhost:8000").rstrip("/")
PROFILES = os.environ.get("PROFILES", "sliding-window type-tailored embedding-alt").split()


def check(resp: httpx.Response):
    if resp.is_error:
        sys.exit(
            f"✗ HTTP {resp.status_code} {resp.request.method} "
            f"{resp.request.url.path}: {resp.text[:400]}"
        )
    return resp.json() if resp.content else None


def repo_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted((SAMPLE / "repo").rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(SAMPLE / "repo").as_posix())
    return buf.getvalue()


def main() -> None:
    course_id = os.environ.get("COURSE_ID")
    if not course_id:
        sys.exit("✗ Set COURSE_ID to the eval course's id.")
    api = f"{BASE_URL}/api/courses/{int(course_id)}/rag"

    client = httpx.Client(timeout=120)
    token = check(
        client.post(
            f"{BASE_URL}/api/auth/login",
            json={
                "username": _env_value("ADMIN_USERNAME", "admin"),
                "password": _env_value("ADMIN_PASSWORD"),
            },
        )
    )["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"

    profiles = {p["name"]: p for p in check(client.get(f"{api}/profiles"))}
    for name in PROFILES:
        if name not in profiles:
            profiles[name] = check(
                client.post(f"{api}/profiles", json={"preset": name, "name": name})
            )
            print(f"✓ created profile {name} (id={profiles[name]['id']})")

    titles = {r["title"] for r in check(client.get(f"{api}/resources"))}
    uploads = [
        ("syllabus", "Syllabus", "syllabus.html",
         (SAMPLE / "web/syllabus.html").read_bytes(), f"{BLOB}/web/syllabus.html"),
        ("schedule", "Schedule", "schedule.html",
         (SAMPLE / "web/schedule.html").read_bytes(), f"{BLOB}/web/schedule.html"),
        ("repository", "Course repository (sample_data/repo)", "repo.zip",
         repo_zip(), f"{BLOB}/repo"),
    ]
    for resource_type, title, filename, data, base in uploads:
        if title in titles:
            continue
        resource = check(
            client.post(
                f"{api}/resources/upload",
                data={"resource_type": resource_type, "title": title,
                      "citation_base_url": base},
                files={"file": (filename, data)},
            )
        )
        print(f"✓ uploaded {title} (id={resource['id']})")

    # One profile at a time: gte ingestion is the memory peak (design §4.3.3)
    for name in PROFILES:
        job = check(client.post(f"{api}/profiles/{profiles[name]['id']}/sync"))
        print(f"→ sync {name}: job {job['id']}", flush=True)
        while job["status"] in ("QUEUED", "RUNNING"):
            time.sleep(5)
            job = check(client.get(f"{api}/jobs/{job['id']}"))
        print(f"  {job['status']} {job.get('error') or ''}")
        if job["status"] != "SUCCEEDED":
            sys.exit(1)

    for p in check(client.get(f"{api}/profiles")):
        print(f"  {p['name']}: chunk_count={p['chunk_count']}")


if __name__ == "__main__":
    main()
