"""Fail if tracked paths include credentials, raw evidence or private research data."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PATHS = (
    re.compile(r"(^|/)\.env($|\.)"),
    re.compile(r"(^|/)\.venv/"),
    re.compile(r"(^|/)__pycache__/"),
    re.compile(r"(^|/)\.pytest_cache/"),
    re.compile(r"^\.streamlit/secrets\.toml$"),
    re.compile(r"^data/raw/runs/(?!\.gitkeep$)"),
    re.compile(r"^data/raw/screens/(?!\.gitkeep$)"),
    re.compile(r"^data/raw/study-v2/(?!\.gitkeep$)"),
    re.compile(r"^data/raw/study-preflight/(?!\.gitkeep$)"),
    re.compile(r"^data/raw/pilot-v4-qualification/"),
    re.compile(r"^data/raw/pilot-v5-qualification/"),
    re.compile(r"^data/annotations/(?!\.gitkeep$)"),
    re.compile(r"^data/derived/(?!\.gitkeep$)"),
    re.compile(r"^data/private/"),
)
SECRET_PATTERNS = (
    re.compile(rb"sk-or-v1-[A-Za-z0-9_-]{20,}"),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


def tracked_paths() -> list[str]:
    output = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    return [value.decode("utf-8") for value in output.split(b"\0") if value]


def audit_tracked_files() -> list[str]:
    suspicious = []
    for relative in tracked_paths():
        if relative == ".env.example":
            continue
        if any(pattern.search(relative) for pattern in FORBIDDEN_PATHS):
            suspicious.append(relative)
            continue
        path = ROOT / relative
        if path.is_file():
            content = path.read_bytes()
            if any(pattern.search(content) for pattern in SECRET_PATTERNS):
                suspicious.append(relative)
    return sorted(set(suspicious))


def main() -> int:
    suspicious = audit_tracked_files()
    if suspicious:
        print("Repository safety check failed; suspicious tracked filenames:", file=sys.stderr)
        for path in suspicious:
            print(path, file=sys.stderr)
        return 1
    print("Repository safety check passed: no tracked secrets or private/raw evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
