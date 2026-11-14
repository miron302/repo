# Miron302's Repository

An APT repository for iOS jailbreak tweaks, hosted on GitHub Pages and compatible with **Sileo** and **Zebra**.

**Repository URL:** https://miron302.github.io/repo/

```text
https://miron302.github.io/repo/
```

## Adding a package

The only step is adding a valid `.deb` to `debs/` and pushing it:

```bash
cp /path/to/com.example.tweak_1.0.0_iphoneos-arm64.deb debs/
git add debs/com.example.tweak_1.0.0_iphoneos-arm64.deb
git commit -m "Add com.example.tweak 1.0.0"
git push
```

The **Build and deploy APT repository** workflow then:

1. detects the changed file under `debs/`;
2. reads its control file with `dpkg-deb`;
3. regenerates `Packages`, `Packages.gz`, `Release`, and `packages.json`;
4. validates every hash, size, architecture, and package reference;
5. deploys the validated site to GitHub Pages.

No package metadata is invented: names, versions, descriptions, dependencies, and authors come from each `.deb` control file. Existing `.deb` files stay in `debs/` and remain indexed.

### Updating a tweak

Build the new version with a higher `Version` in its control file, replace or add the `.deb` in `debs/`, then commit and push. Old versions are preserved unless you deliberately remove their `.deb` files. Removing a file is the only way a package disappears from the index.

### Putting a package in a separate section (for example, Legacy Tweaks)

Package managers such as Sileo and Zebra group packages using the `Section` value in the generated APT index, which normally comes from the `.deb` control file.

To place a package in a separate group without modifying the `.deb` itself, add an override to `sections.conf`:

```text
com.miron302.xenhtmlreborn: Legacy Tweaks
```

Currently applied overrides are used when the generated `Packages` index is rebuilt; `packages.json` picks them up automatically, so the landing page also shows the overridden section.

For the current tweak:

```bash
cp '/home/miron/Projects/XenHTMLReborn(v0.3-beta1).deb' 'debs/com.miron302.xenhtmlreborn_0.3-native1-1+debug_iphoneos-arm64.deb'
./update.sh
```

The resulting index contains:

```text
Section: Legacy Tweaks
```

### Naming

Use the normal Debian package filename convention:

```text
<package-id>_<version>_<architecture>.deb
```

Examples:

```text
com.miron302.standby16_1.0.0_iphoneos-arm64.deb
com.miron302.example_1.2.0_iphoneos-arm.deb
```

Filenames may only contain letters, digits, `.`, `_`, `+`, `~`, and `-`. A package must have `Package`, `Version`, `Architecture`, and `Description` fields. The script refuses to index a malformed package rather than guessing missing metadata.

## Local regeneration

`update.sh` performs the same build locally:

```bash
./update.sh
python3 scripts/verify.py   # update.sh already does this automatically
python3 -m http.server 8000 # preview the landing page
```

Requirements: Bash, `dpkg-deb`, `dpkg`, `gzip`, `md5sum`, `sha1sum`, `sha256sum`, and Python 3. GitHub's Ubuntu runner provides all of them.

The script validates the generated metadata **before** replacing the published `Packages`, `Packages.gz`, `Release`, and `packages.json` files, so a broken package cannot overwrite a working index.

## Repository layout

```text
.
├── debs/                     # .deb files (the only files you normally add)
├── Packages                  # generated APT package index
├── Packages.gz               # compressed package index
├── Release                   # generated repository metadata + checksums
├── packages.json             # generated data for the landing page
├── index.html                # landing page
├── sections.conf             # optional Sileo/Zebra section overrides
├── update.sh                 # local/CI index builder
├── scripts/
│   ├── aptlib.py             # control-file parser and version comparison
│   ├── make-json.py          # Packages -> packages.json
│   └── verify.py             # repository validation
└── .github/workflows/pages.yml
```

`index.html` is static; it fetches `packages.json` at runtime to render the tweak list.

## GitHub Pages

Pages is configured to deploy from **GitHub Actions** (not from a branch). The workflow uploads a `_site` artifact containing only the public repository files and deploys it with `actions/deploy-pages`.

Generated changes are never committed back to `main`, so a build cannot enqueue another build and create an infinite workflow loop.

If Pages is ever disabled, re-enable it under **Settings → Pages → Build and deployment → Source: GitHub Actions**.

## Notes

- The repository is **unsigned**. Sileo and Zebra accept unsigned APT sources; signing with `InRelease`/`Release.gpg` would require a GPG key and an additional workflow secret.
- `Packages.gz` is written with `gzip -n`, making its bytes deterministic.
- `Release` includes MD5, SHA-1, and SHA-256 checksums for `Packages` and `Packages.gz`.
- The landing page and `Packages` index are served from `https://miron302.github.io/repo/`.
