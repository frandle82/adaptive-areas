#!/usr/bin/env python3
"""Validate and update the integration version."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

MANIFEST_PATH = Path("custom_components/adaptive_areas/manifest.json")
VERSION_PATTERN = re.compile(
    r"^(?P<major>0|[1-9]\d*)\."
    r"(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


def main() -> int:
    """Validate the requested version and write it to the manifest."""
    parser = argparse.ArgumentParser()
    parser.add_argument("version")
    parser.add_argument(
        "--release-type",
        choices=("draft", "prerelease", "release"),
        default="draft",
    )
    args = parser.parse_args()

    match = VERSION_PATTERN.fullmatch(args.version)
    if match is None:
        parser.error("version must use SemVer without a leading 'v'")
    if args.release_type == "release" and match.group("prerelease"):
        parser.error("a final release cannot use a prerelease version")
    if args.release_type == "prerelease" and not match.group("prerelease"):
        parser.error("a prerelease requires a suffix such as '-beta.1' or '-rc.1'")

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["version"] = args.version
    MANIFEST_PATH.write_text(
        f"{json.dumps(manifest, indent=2, ensure_ascii=False)}\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
