#!/usr/bin/env python3
"""Validate an APT repository before it is published.

Checks performed:
  * every package stanza has the fields clients need;
  * every referenced .deb exists, is inside debs/, and matches its size/hashes;
  * Packages.gz decompresses to exactly the same bytes as Packages;
  * Release checksums match Packages and Packages.gz;
  * every architecture used by a package is advertised in Release;
  * packages.json agrees with the Packages index.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aptlib import ControlError, parse_control  # noqa: E402

REQUIRED_PACKAGE_FIELDS = (
    "Package",
    "Version",
    "Architecture",
    "Description",
    "Filename",
    "Size",
    "MD5sum",
    "SHA1",
    "SHA256",
)

REQUIRED_RELEASE_FIELDS = (
    "Origin",
    "Label",
    "Suite",
    "Version",
    "Codename",
    "Architectures",
    "Components",
    "Description",
    "Date",
)


def hash_file(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checksum_section(release_text: str, field: str) -> dict[str, tuple[str, int]]:
    entries: dict[str, tuple[str, int]] = {}
    active = False

    for line in release_text.splitlines():
        if line.rstrip() == f"{field}:":
            active = True
            continue
        if not active:
            continue
        if not line.startswith((" ", "\t")):
            break

        parts = line.split()
        if len(parts) != 3:
            continue
        checksum, size, name = parts
        try:
            entries[name] = (checksum.lower(), int(size))
        except ValueError:
            continue

    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--packages-file", type=Path, default=None)
    parser.add_argument("--gz-file", type=Path, default=None)
    parser.add_argument("--release-file", type=Path, default=None)
    parser.add_argument("--json-file", type=Path, default=None)
    args = parser.parse_args()

    root = args.root.resolve()
    packages_path = (args.packages_file or root / "Packages").resolve()
    gz_path = (args.gz_file or root / "Packages.gz").resolve()
    release_path = (args.release_file or root / "Release").resolve()
    json_path = (args.json_file or root / "packages.json").resolve()

    errors: list[str] = []

    def error(message: str) -> None:
        errors.append(message)

    for label, path in (
        ("Packages", packages_path),
        ("Packages.gz", gz_path),
        ("Release", release_path),
        ("packages.json", json_path),
    ):
        if not path.is_file():
            error(f"{label} not found at {path}")

    if errors:
        for message in errors:
            print(f"  ✗ {message}", file=sys.stderr)
        return 1

    packages_text = packages_path.read_text(encoding="utf-8", errors="replace")
    release_text = release_path.read_text(encoding="utf-8", errors="replace")

    try:
        stanzas = parse_control(packages_text)
    except ControlError as exc:
        print(f"  ✗ Packages: {exc}", file=sys.stderr)
        return 1

    seen: dict[tuple[str, str, str], str] = {}
    architectures: set[str] = set()

    for index, stanza in enumerate(stanzas, 1):
        for field in REQUIRED_PACKAGE_FIELDS:
            if not stanza.get(field):
                error(f"Packages stanza {index}: missing {field}")

        package = stanza.get("Package", f"stanza-{index}")
        version = stanza.get("Version", "")
        architecture = stanza.get("Architecture", "")
        filename = stanza.get("Filename", "")

        if architecture:
            architectures.add(architecture)

        key = (package, version, architecture)
        if key in seen:
            error(
                f"Packages: duplicate {package} {version} ({architecture}) "
                f"in {seen[key]} and {filename}"
            )
        else:
            seen[key] = filename

        if not filename:
            continue

        relative = Path(filename)
        if relative.is_absolute() or ".." in relative.parts:
            error(f"{package}: unsafe Filename {filename!r}")
            continue
        if not relative.parts or relative.parts[0] != "debs":
            error(f"{package}: Filename must live under debs/, got {filename!r}")
            continue

        deb_path = (root / relative).resolve()
        try:
            deb_path.relative_to(root)
        except ValueError:
            error(f"{package}: Filename escapes the repository: {filename!r}")
            continue

        if not deb_path.is_file():
            error(f"{package}: missing package file {filename}")
            continue

        actual_size = deb_path.stat().st_size
        try:
            declared_size = int(stanza.get("Size", ""))
        except ValueError:
            error(f"{package}: invalid Size field {stanza.get('Size')!r}")
        else:
            if actual_size != declared_size:
                error(
                    f"{package}: Size mismatch (index {declared_size}, file {actual_size})"
                )

        for field, algorithm in (
            ("MD5sum", "md5"),
            ("SHA1", "sha1"),
            ("SHA256", "sha256"),
        ):
            declared = stanza.get(field)
            if not declared:
                continue
            actual = hash_file(deb_path, algorithm)
            if actual != declared.lower():
                error(f"{package}: {field} mismatch for {filename}")

    expected_packages = packages_path.read_bytes()
    try:
        with gzip.open(gz_path, "rb") as handle:
            compressed = handle.read()
    except (OSError, gzip.BadGzipFile) as exc:
        error(f"Packages.gz cannot be decompressed: {exc}")
    else:
        if compressed != expected_packages:
            error("Packages.gz does not match Packages")

    try:
        release_stanzas = parse_control(release_text)
    except ControlError as exc:
        print(f"  ✗ Release: {exc}", file=sys.stderr)
        return 1

    if len(release_stanzas) != 1:
        error(f"Release should contain one stanza, found {len(release_stanzas)}")
    release = release_stanzas[0] if release_stanzas else {}

    for field in REQUIRED_RELEASE_FIELDS:
        if not release.get(field):
            error(f"Release: missing {field}")

    declared_architectures = set(release.get("Architectures", "").split())
    missing_architectures = architectures - declared_architectures
    if missing_architectures:
        error(
            "Release Architectures is missing: "
            + ", ".join(sorted(missing_architectures))
        )

    metadata_paths = {
        "Packages": packages_path,
        "Packages.gz": gz_path,
    }

    for field, algorithm in (
        ("MD5Sum", "md5"),
        ("SHA1", "sha1"),
        ("SHA256", "sha256"),
    ):
        entries = checksum_section(release_text, field)
        if not entries:
            error(f"Release: missing or empty {field} section")
            continue

        for required in ("Packages", "Packages.gz"):
            if required not in entries:
                error(f"Release: {field} does not list {required}")

        for name, (declared_hash, declared_size) in entries.items():
            path = metadata_paths.get(name, root / name)
            if not path.is_file():
                error(f"Release: {field} references missing file {name}")
                continue
            actual_size = path.stat().st_size
            if actual_size != declared_size:
                error(
                    f"Release: {field} size mismatch for {name} "
                    f"(declared {declared_size}, file {actual_size})"
                )
            actual_hash = hash_file(path, algorithm)
            if actual_hash != declared_hash:
                error(f"Release: {field} mismatch for {name}")

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        error(f"packages.json is not valid JSON: {exc}")
        data = {}

    if data:
        repository = data.get("repository", {})
        packages = data.get("packages", [])
        package_names = {stanza.get("Package") for stanza in stanzas}
        json_names = {entry.get("package") for entry in packages}

        if not isinstance(packages, list):
            error("packages.json: 'packages' must be a list")
        else:
            if repository.get("packageCount") != len(packages):
                error("packages.json: packageCount does not match the package list")
            if json_names != package_names:
                missing = package_names - json_names
                extra = json_names - package_names
                if missing:
                    error("packages.json is missing: " + ", ".join(sorted(missing)))
                if extra:
                    error("packages.json has unknown packages: " + ", ".join(sorted(extra)))

            indexed_filenames = {
                stanza.get("Filename") for stanza in stanzas if stanza.get("Filename")
            }
            for entry in packages:
                filename = entry.get("filename")
                if filename and filename not in indexed_filenames:
                    error(
                        f"packages.json: {entry.get('package')} references "
                        f"{filename}, which is not in Packages"
                    )

    if errors:
        print("Repository index is INVALID:", file=sys.stderr)
        for message in errors:
            print(f"  ✗ {message}", file=sys.stderr)
        return 1

    unique_packages = len({stanza.get("Package") for stanza in stanzas})
    print(f"  ✓ Packages: {len(stanzas)} package file(s), {unique_packages} package name(s)")
    print("  ✓ Packages.gz matches Packages")
    print("  ✓ Release checksums are valid")
    if stanzas:
        print("  ✓ Every .deb exists and matches its size and hashes")
    else:
        print("  ✓ No .deb references to check yet")
    print(f"  ✓ packages.json: {len(data.get('packages', []))} package card(s)")
    print("Repository index is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
