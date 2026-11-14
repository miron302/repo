#!/usr/bin/env python3
"""Generate packages.json for the landing page from a Packages index.

The landing page shows one card per package name, using the newest version
found in the index. Every field comes from the Debian control data; absent
fields stay absent.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aptlib import compare_versions, description, read_control  # noqa: E402


def as_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def build_entries(stanzas: list[dict[str, str]]) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for stanza in stanzas:
        package = stanza.get("Package")
        if not package:
            raise ValueError("a package stanza is missing the Package field")
        grouped.setdefault(package, []).append(stanza)

    entries: list[dict[str, object]] = []

    for package, items in grouped.items():
        latest = items[0]
        for item in items[1:]:
            if compare_versions(item["Version"], latest["Version"]) > 0:
                latest = item

        version = latest["Version"]
        architectures: list[str] = []
        for item in items:
            if item.get("Version") != version:
                continue
            architecture = item.get("Architecture")
            if architecture and architecture not in architectures:
                architectures.append(architecture)

        desc = description(latest)

        entries.append(
            {
                "package": package,
                "name": latest.get("Name") or None,
                "version": version,
                "architectures": architectures,
                "section": latest.get("Section") or None,
                "description": desc,
                "summary": desc.splitlines()[0] if desc else "",
                "author": latest.get("Author") or None,
                "maintainer": latest.get("Maintainer") or None,
                "depends": latest.get("Depends") or None,
                "homepage": latest.get("Homepage") or None,
                "depiction": latest.get("SileoDepiction")
                or latest.get("Depiction")
                or None,
                "icon": latest.get("Icon") or None,
                "filename": latest.get("Filename") or None,
                "size": as_int(latest.get("Size")),
                "installedSize": as_int(latest.get("Installed-Size")),
                "sha256": latest.get("SHA256") or None,
            }
        )

    entries.sort(key=lambda entry: (str(entry["name"] or entry["package"]).casefold(), entry["package"]))
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packages", type=Path, help="Packages index to read")
    parser.add_argument("output", type=Path, help="packages.json file to write")
    parser.add_argument("--name", required=True, help="repository display name")
    parser.add_argument("--url", required=True, help="repository public URL")
    parser.add_argument(
        "--generated-at",
        default=None,
        help="ISO-8601 build timestamp (defaults to the current UTC time)",
    )
    args = parser.parse_args()

    stanzas = read_control(args.packages)
    entries = build_entries(stanzas)
    architectures = sorted(
        {stanza["Architecture"] for stanza in stanzas if stanza.get("Architecture")}
    )

    generated_at = args.generated_at or datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    data = {
        "repository": {
            "name": args.name,
            "url": args.url.rstrip("/") + "/",
            "generatedAt": generated_at,
            "packageCount": len(entries),
            "packageFileCount": len(stanzas),
            "architectures": architectures,
        },
        "packages": entries,
    }

    args.output.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
