"""Validate relative Markdown links in tracked project documentation."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def broken_links() -> list[str]:
    broken = []
    markdown = [ROOT / "README.md", ROOT / "PLAN.md", ROOT / "STATUS.md"]
    markdown.extend(sorted((ROOT / "docs").glob("*.md")))
    for document in markdown:
        for target in LINK.findall(document.read_text(encoding="utf-8")):
            target = target.strip().split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            resolved = (document.parent / target).resolve()
            if not resolved.exists():
                broken.append(f"{document.relative_to(ROOT)} -> {target}")
    return broken


def main() -> int:
    broken = broken_links()
    if broken:
        for value in broken:
            print(f"BROKEN: {value}", file=sys.stderr)
        return 1
    print("Documentation links valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
