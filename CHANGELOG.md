# Changelog

## 0.3.1 — 2026-11-10

- Relicensed current project sources and new release artifacts under the MIT License (Copyright 2026 Cody Mathis).
- Updated README, contribution terms, and installer examples to reflect MIT and the new release.
- Existing v0.3.0 and earlier release artifacts are unchanged and still include their original PolyForm Noncommercial license terms.

## 0.3.0 — 2026-11-10

- Added one-command Steam Deck installation and upgrades via official GitHub Release assets.
- Bootstrap downloads as unprivileged user, checks ZIP against a SHA-256 manifest, verifies hardware before using sudo, and cleans temporary files.
- Added automated release workflow that runs tests and publishes tagged, immutable ZIP and SHA256SUMS artifacts on a new version in Production.
- Added offline bootstrap tests and installation/security documentation.

## 0.2.0 — 2026-11-09

- Repository publication under the name SteamDeck-Controller-AutoSwitch, with PolyForm Noncommercial License 1.0.0 (replacing the initial draft MIT license).

- Event-oriented controller logging (connections, disconnections, real HID changes, errors, manual recovery) without unchanged-poll messages from Python; a dedicated journal identifier filters out systemd service-lifecycle chatter.
- Tiny atomic state snapshot in volatile `/run`, rather than writing history to the SSD.
- Recognized in-place upgrades with `install.sh` (no uninstall needed); preflight still runs first.
- New installations no longer opt into custom SteamOS update keep-lists by default; existing keep-list choice is preserved. Explicit `--persist-updates` and `--no-persist-updates` flags added.
- Added rollback-to-safe-state attempt if service activation fails, cleanup of runtime cache on uninstall, more tests, CI, and release packaging.
- Added architecture, troubleshooting, contribution, and safety documentation.

## 0.1.0 — 2026-11-08

- Initial USB HID handoff via Bluetooth gamepad detection, udev/systemd event hook, 30-second fallback timer, read-only preflight, manual restoration, and uninstaller.
