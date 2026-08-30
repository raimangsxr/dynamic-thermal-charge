#!/usr/bin/env python3
"""Validate, compact, and archive an AES OpenSpec change without delta-spec sync."""
from __future__ import annotations

import argparse
import datetime as dt
import re
import shutil
import sys
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
UNCHECKED_RE = re.compile(r"^\s*-\s*\[ \]\s+", re.MULTILINE)
CHECKED_RE = re.compile(r"^\s*-\s*\[[xX]\]\s+", re.MULTILINE)
APPROVED_RE = re.compile(r"(?mi)^Status:\s*approved\s*$")
TASKS_SECTION_RE = re.compile(r"(?ms)^## Tasks\s*\n.*?(?=^##\s|\Z)")


def compact_archived_change(path: Path) -> None:
    content = path.read_text(encoding="utf-8")
    content = TASKS_SECTION_RE.sub("", content).rstrip() + "\n"
    path.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("change", help="kebab-case active change name")
    parser.add_argument("--project", default=".", help="project root (default: cwd)")
    args = parser.parse_args()

    if not NAME_RE.fullmatch(args.change):
        print("ERROR: change name must be lowercase kebab-case", file=sys.stderr)
        return 2

    root = Path(args.project).resolve()
    src = root / "openspec" / "changes" / args.change
    change_file = src / "change.md"
    if not src.is_dir():
        print(f"ERROR: active change not found: {src}", file=sys.stderr)
        return 2
    if not change_file.is_file():
        print(f"ERROR: change.md not found: {change_file}", file=sys.stderr)
        return 2

    content = change_file.read_text(encoding="utf-8")
    if not APPROVED_RE.search(content):
        print("ERROR: change.md is not explicitly approved (expected `Status: approved`)", file=sys.stderr)
        return 2
    if UNCHECKED_RE.search(content):
        print("ERROR: change.md still contains incomplete task checkboxes", file=sys.stderr)
        return 2
    if not CHECKED_RE.search(content):
        print("ERROR: change.md has no completed task checkboxes; do not delete Tasks before archiving", file=sys.stderr)
        return 2

    archive_root = root / "openspec" / "changes" / "archive"
    archive_root.mkdir(parents=True, exist_ok=True)
    prefix = dt.date.today().isoformat()
    dest = archive_root / f"{prefix}-{args.change}"
    if dest.exists():
        print(f"ERROR: archive destination already exists: {dest}", file=sys.stderr)
        return 2

    shutil.move(str(src), str(dest))
    compact_archived_change(dest / "change.md")
    print(dest.relative_to(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
