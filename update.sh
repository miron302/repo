#!/usr/bin/env bash
#
# Regenerate the static APT repository metadata from debs/*.deb.
#
# Usage:
#   ./update.sh
#
# Run this after adding or replacing a .deb. The GitHub Actions workflow runs
# the same script automatically on every push, so manual use is optional.
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Repository identity (override with environment variables if you fork this).
# ---------------------------------------------------------------------------
REPO_ORIGIN="${REPO_ORIGIN:-Miron302}"
REPO_LABEL_DEFAULT="Miron302's Repository"
REPO_LABEL="${REPO_LABEL:-$REPO_LABEL_DEFAULT}"
REPO_URL="${REPO_URL:-https://miron302.github.io/repo}"
REPO_SUITE="${REPO_SUITE:-stable}"
REPO_CODENAME="${REPO_CODENAME:-ios}"
REPO_COMPONENTS="${REPO_COMPONENTS:-main}"
REPO_ARCHITECTURES="${REPO_ARCHITECTURES:-iphoneos-arm iphoneos-arm64 all}"
REPO_DESCRIPTION="${REPO_DESCRIPTION:-iOS jailbreak tweaks by Miron302}"
REPO_VERSION="${REPO_VERSION:-1.0}"

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEBS_DIR="${DEBS_DIR:-$ROOT/debs}"

if [[ -t 1 ]]; then
  ACCENT=$'\033[38;5;141m'
  BOLD=$'\033[1m'
  RESET=$'\033[0m'
else
  ACCENT=""
  BOLD=""
  RESET=""
fi

info() { printf '%s==>%s %s\n' "$ACCENT" "$RESET" "$*"; }
die() { printf '%serror:%s %s\n' "$BOLD" "$RESET" "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------
for command in dpkg-deb dpkg gzip md5sum sha1sum sha256sum python3; do
  command -v "$command" >/dev/null 2>&1 || die "required command not found: $command"
done

mkdir -p "$DEBS_DIR"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Read filenames as NUL-separated so spaces are safe. Sort for deterministic
# output; dpkg's own .deb naming convention also sorts by package/version.
deb_files=()
while IFS= read -r -d '' file; do
  deb_files+=("$file")
done < <(find "$DEBS_DIR" -maxdepth 1 -type f -name '*.deb' -print0 | sort -z)

info "Reading ${#deb_files[@]} package file(s) from $DEBS_DIR"

: > "$TMP/Packages"

declare -A seen_packages=()
architectures="$REPO_ARCHITECTURES"

control_field() {
  # $1 is the field name; $control is the current control paragraph.
  awk -v key="$1:" '
    index($0, key) == 1 {
      sub(/^[^:]*:[ \t]*/, "")
      print
      exit
    }
  ' <<<"$control"
}

for deb in "${deb_files[@]}"; do
  filename="${deb##*/}"

  case "$filename" in
    *[!A-Za-z0-9._+~-]*)
      die "unsupported character in filename: $filename (use A-Z a-z 0-9 . _ + ~ -)"
      ;;
  esac

  control="$(dpkg-deb -f "$deb" 2>/dev/null)" \
    || die "cannot read control data from $filename (is it a valid .deb?)"
  control="${control//$'\r'/}"
  while [[ "$control" == *$'\n' ]]; do control="${control%$'\n'}"; done

  package="$(control_field Package)"
  version="$(control_field Version)"
  architecture="$(control_field Architecture)"

  [[ -n "$package" ]] || die "$filename: missing Package field"
  [[ -n "$version" ]] || die "$filename: missing Version field"
  [[ -n "$architecture" ]] || die "$filename: missing Architecture field"

  [[ "$package" =~ ^[a-z0-9][a-z0-9+.-]+$ ]] \
    || die "$filename: invalid Package name '$package'"
  [[ "$version" != *[[:space:]]* ]] \
    || die "$filename: Version must not contain whitespace"

  grep -q '^Description:' <<<"$control" \
    || die "$filename: missing Description field (refusing to invent one)"

  for generated_field in Filename Size MD5sum SHA1 SHA256; do
    if grep -q "^${generated_field}:" <<<"$control"; then
      die "$filename: control file already contains '$generated_field'"
    fi
  done

  key="$package|$version|$architecture"
  if [[ -n "${seen_packages[$key]:-}" ]]; then
    die "duplicate package $package $version ($architecture) in ${seen_packages[$key]} and $filename"
  fi
  seen_packages["$key"]="$filename"

  case " $architectures " in
    *" $architecture "*) ;;
    *) architectures="$architectures $architecture" ;;
  esac

  size="$(wc -c < "$deb" | tr -d '[:space:]')"
  md5="$(md5sum "$deb" | awk '{print $1}')"
  sha1="$(sha1sum "$deb" | awk '{print $1}')"
  sha256="$(sha256sum "$deb" | awk '{print $1}')"

  {
    printf '%s\n' "$control"
    printf 'Filename: debs/%s\n' "$filename"
    printf 'Size: %s\n' "$size"
    printf 'MD5sum: %s\n' "$md5"
    printf 'SHA1: %s\n' "$sha1"
    printf 'SHA256: %s\n' "$sha256"
    printf '\n'
  } >> "$TMP/Packages"

  printf '    + %s %s (%s)\n' "$package" "$version" "$architecture"
done

# Normalise and de-duplicate the architecture list.
architectures="$(printf '%s\n' $architectures | awk 'NF && !seen[$0]++' | paste -sd' ' -)"

# Deterministic gzip output (-n omits the timestamp and original filename).
gzip -9n -c "$TMP/Packages" > "$TMP/Packages.gz"

checksum_line() {
  local algorithm="$1" file="$2" name="$3" hash size
  hash="$("${algorithm}sum" "$file" | awk '{print $1}')"
  size="$(wc -c < "$file" | tr -d '[:space:]')"
  printf ' %s %s %s\n' "$hash" "$size" "$name"
}

info "Writing Release metadata"
{
  printf 'Origin: %s\n' "$REPO_ORIGIN"
  printf 'Label: %s\n' "$REPO_LABEL"
  printf 'Suite: %s\n' "$REPO_SUITE"
  printf 'Version: %s\n' "$REPO_VERSION"
  printf 'Codename: %s\n' "$REPO_CODENAME"
  printf 'Architectures: %s\n' "$architectures"
  printf 'Components: %s\n' "$REPO_COMPONENTS"
  printf 'Description: %s\n' "$REPO_DESCRIPTION"
  printf 'Date: %s\n' "$(LC_ALL=C date -Ru)"
  printf 'MD5Sum:\n'
  checksum_line md5 "$TMP/Packages" Packages
  checksum_line md5 "$TMP/Packages.gz" Packages.gz
  printf 'SHA1:\n'
  checksum_line sha1 "$TMP/Packages" Packages
  checksum_line sha1 "$TMP/Packages.gz" Packages.gz
  printf 'SHA256:\n'
  checksum_line sha256 "$TMP/Packages" Packages
  checksum_line sha256 "$TMP/Packages.gz" Packages.gz
} > "$TMP/Release"

info "Generating packages.json for the landing page"
python3 "$ROOT/scripts/make-json.py" \
  "$TMP/Packages" "$TMP/packages.json" \
  --name "$REPO_LABEL" \
  --url "$REPO_URL" \
  --generated-at "$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Validate before overwriting the published files, so a broken package cannot
# replace a working index.
info "Validating generated metadata"
python3 "$ROOT/scripts/verify.py" \
  --root "$ROOT" \
  --packages-file "$TMP/Packages" \
  --gz-file "$TMP/Packages.gz" \
  --release-file "$TMP/Release" \
  --json-file "$TMP/packages.json"

install -m 0644 "$TMP/Packages" "$ROOT/Packages"
install -m 0644 "$TMP/Packages.gz" "$ROOT/Packages.gz"
install -m 0644 "$TMP/Release" "$ROOT/Release"
install -m 0644 "$TMP/packages.json" "$ROOT/packages.json"

unique_packages="$(awk -F': ' '/^Package:/{print $2}' "$TMP/Packages" | sort -u | wc -l | tr -d '[:space:]')"

printf '\n%sRepository metadata updated%s\n' "$BOLD" "$RESET"
printf '  packages:     %s .deb file(s), %s package name(s)\n' "${#deb_files[@]}" "$unique_packages"
printf '  architectures: %s\n' "$architectures"
printf '  repository:   %s/\n' "${REPO_URL%/}"
