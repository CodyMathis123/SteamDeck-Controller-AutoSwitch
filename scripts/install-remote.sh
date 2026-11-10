#!/usr/bin/env bash
# Install from an official GitHub Release. Downloads happen as the current
# unprivileged user; only the local, verified archive's installer uses sudo.
set -euo pipefail

REPO='CodyMathis123/SteamDeck-Controller-AutoSwitch'
ARCHIVE='steamdeck-controller-fix.zip'
CHECKSUMS='SHA256SUMS'
VERSION="${STEAMDECK_AUTOSWITCH_VERSION:-latest}"

usage() {
  cat <<'HELP'
SteamDeck-Controller-AutoSwitch remote installer

Usage: curl -fsSL https://raw.githubusercontent.com/CodyMathis123/SteamDeck-Controller-AutoSwitch/Production/scripts/install-remote.sh | bash

Optional:
  STEAMDECK_AUTOSWITCH_VERSION=v0.3.1  Pin to one released version
  bash install-remote.sh --no-persist-updates  Remove this project's SteamOS keep-list
  bash install-remote.sh --persist-updates     Opt into SteamOS update keep-list (see README caveat)

This script downloads a GitHub Release ZIP and SHA256SUMS as a regular user,
verifies the ZIP, runs the hardware preflight, and asks sudo to install the
verified code. No privileged network downloads are performed.
HELP
}

for arg in "$@"; do
  case "$arg" in
    --no-persist-updates|--persist-updates) ;;
    --help|-h) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$arg" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$VERSION" != latest && ! "$VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  printf 'Invalid version: %s (expected latest or vX.Y.Z)\n' "$VERSION" >&2
  exit 2
fi

for tool in curl sha256sum unzip python3 mktemp sudo grep; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    printf 'Missing required tool: %s\n' "$tool" >&2
    exit 1
  fi
done

# Never create persistent files in the current directory or the Deck home.
workdir="$(mktemp -d "${TMPDIR:-/tmp}/steamdeck-autoswitch.XXXXXXXX")"
trap 'rm -rf -- "$workdir"' EXIT

if [[ "$VERSION" == latest ]]; then
  base="https://github.com/$REPO/releases/latest/download"
else
  base="https://github.com/$REPO/releases/download/$VERSION"
fi

printf 'Downloading Steam Deck Controller AutoSwitch (%s)...\n' "$VERSION"
for file in "$ARCHIVE" "$CHECKSUMS"; do
  if ! curl --fail --silent --show-error --location --retry 2 --connect-timeout 15 \
      --proto '=https' --tlsv1.2 --output "$workdir/$file" "$base/$file"; then
    printf 'Could not download %s. Check that a GitHub Release has been published.\n' "$file" >&2
    exit 1
  fi
done

# Accept a single, canonical checksum entry only; no unexpected filenames.
if [[ "$(wc -l < "$workdir/$CHECKSUMS")" -ne 1 ]] || \
   ! grep -Eq '^[0-9a-fA-F]{64}  steamdeck-controller-fix\.zip$' "$workdir/$CHECKSUMS"; then
  echo 'Invalid checksum manifest; installation aborted.' >&2
  exit 1
fi
(
  cd -- "$workdir"
  if ! sha256sum --check --status --strict "$CHECKSUMS"; then
    echo 'Release archive checksum mismatch; installation aborted.' >&2
    exit 1
  fi
)
printf 'SHA-256 verification passed.\n'

unzip -q "$workdir/$ARCHIVE" -d "$workdir/extracted"
source_dir="$workdir/extracted/steamdeck-controller-fix"
if [[ ! -f "$source_dir/controller_fix.py" || ! -f "$source_dir/install.sh" ]]; then
  echo 'Release archive did not contain expected installer files.' >&2
  exit 1
fi

# Fail closed before obtaining root privileges on unsupported hardware.
python3 "$source_dir/controller_fix.py" doctor
printf 'Installing verified release (sudo may request your password)...\n'
sudo bash "$source_dir/install.sh" "$@"
python3 /etc/steamdeck-controller-fix/controller_fix.py status
printf 'Done. Logs: sudo journalctl -t steamdeck-controller-fix -n 40 --no-pager\n'
