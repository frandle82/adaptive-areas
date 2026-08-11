#!/usr/bin/env python3
"""Validate JSON files and reject duplicate object keys."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build an object while rejecting duplicate keys."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key: {key}")
        result[key] = value
    return result


def main() -> int:
    """Validate every JSON file supplied by pre-commit."""
    invalid = False
    for filename in sys.argv[1:]:
        path = Path(filename)
        try:
            json.loads(
                path.read_text(encoding="utf-8"),
                object_pairs_hook=reject_duplicate_keys,
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            print(f"{path}: {error}", file=sys.stderr)
            invalid = True
    return int(invalid)


if __name__ == "__main__":
    raise SystemExit(main())
