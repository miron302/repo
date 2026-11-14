#!/usr/bin/env python3
"""Shared helpers for parsing APT repository metadata.

Only metadata that is present in a Debian control file is exposed. Missing
fields are returned as ``None`` rather than being filled with invented values.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


class ControlError(ValueError):
    """Raised when a control file cannot be parsed."""


def parse_control(text: str) -> list[dict[str, str]]:
    """Parse one or more RFC 822-style control paragraphs.

    Continuation lines (those starting with a space or tab) are appended to
    the previous field, preserving everything after the first whitespace
    character. This is enough to keep multi-line ``Description`` values intact.
    """

    stanzas: list[dict[str, str]] = []
    current: dict[str, str] = {}
    last_key: str | None = None

    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip("\r")

        if not line.strip():
            if current:
                stanzas.append(current)
                current = {}
                last_key = None
            continue

        if line[0] in (" ", "\t"):
            if last_key is None:
                raise ControlError(f"line {number}: continuation without a field")
            current[last_key] += "\n" + line[1:]
            continue

        if ":" not in line:
            raise ControlError(f"line {number}: expected 'Field: value'")

        key, value = line.split(":", 1)
        key = key.strip()
        if not key:
            raise ControlError(f"line {number}: empty field name")
        if key in current:
            raise ControlError(f"line {number}: duplicate field {key!r}")

        current[key] = value.lstrip()
        last_key = key

    if current:
        stanzas.append(current)

    return stanzas


def read_control(path: Path) -> list[dict[str, str]]:
    """Read and parse a control file from disk."""

    return parse_control(path.read_text(encoding="utf-8", errors="replace"))


def description(stanza: dict[str, str]) -> str:
    """Return a readable Description value.

    Debian encodes blank lines in extended descriptions as a single ``.``.
    """

    raw = stanza.get("Description", "")
    if not raw:
        return ""

    lines = raw.splitlines()
    rendered = [lines[0]]
    for line in lines[1:]:
        rendered.append("" if line.strip() == "." else line)

    return "\n".join(rendered).strip()


def compare_versions(left: str, right: str) -> int:
    """Compare two Debian versions using dpkg's own algorithm.

    Returns -1, 0 or 1. Raises RuntimeError if dpkg rejects either version.
    """

    def run(operator: str) -> bool:
        result = subprocess.run(
            ["dpkg", "--compare-versions", left, operator, right],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode not in (0, 1):
            detail = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(
                f"cannot compare Debian versions {left!r} and {right!r}: {detail}"
            )
        return result.returncode == 0

    if run("eq"):
        return 0
    if run("lt"):
        return -1
    if run("gt"):
        return 1

    raise RuntimeError(f"cannot compare Debian versions {left!r} and {right!r}")


def parse_release(path: Path) -> dict[str, str]:
    """Parse a Release file (which contains exactly one stanza)."""

    stanzas = read_control(path)
    if not stanzas:
        raise ControlError(f"{path} is empty")
    return stanzas[0]
