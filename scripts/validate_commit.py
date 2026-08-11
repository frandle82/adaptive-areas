#!/usr/bin/env python3
"""Validate Conventional Commit subjects."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys

COMMIT_PATTERN = re.compile(
    r"^(?:build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)"
    r"(?:\([a-z0-9][a-z0-9._/-]*\))?!?: .+[^.]$"
)
IGNORED_PATTERNS = (
    re.compile(r"^Merge "),
    re.compile(r"^Revert \""),
)


def is_valid(subject: str) -> bool:
    """Return whether a commit subject follows the project convention."""
    return bool(COMMIT_PATTERN.fullmatch(subject)) or any(
        pattern.match(subject) for pattern in IGNORED_PATTERNS
    )


def subjects_from_range(commit_range: str) -> list[str]:
    """Read commit subjects from a Git revision range."""
    result = subprocess.run(
        ["git", "log", "--format=%s", commit_range],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines()


def main() -> int:
    """Validate messages supplied directly, by file, or by Git range."""
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--message", action="append", default=[])
    parser.add_argument("--range", dest="commit_range")
    args = parser.parse_args()

    subjects = list(args.message)
    subjects.extend(
        path.read_text(encoding="utf-8").splitlines()[0] for path in args.files
    )
    if args.commit_range:
        subjects.extend(subjects_from_range(args.commit_range))

    if not subjects:
        parser.error("provide a commit message, commit message file, or Git range")

    invalid = [subject for subject in subjects if not is_valid(subject)]
    if not invalid:
        return 0

    print("Invalid Conventional Commit subject(s):", file=sys.stderr)
    for subject in invalid:
        print(f"  - {subject}", file=sys.stderr)
    print(
        "Expected: type(optional-scope): concise description without a trailing period",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
