#!/usr/bin/env python3
"""Create a distributable ZIP with a stable steamdeck-controller-fix/ root."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INCLUDE = (
    "controller_fix.py",
    "install.sh",
    "uninstall.sh",
    "92-steamdeck-controller-fix.rules",
    "steamdeck-controller-fix.service",
    "steamdeck-controller-fix.timer",
    "README.md",
    "LICENSE",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    ".gitignore",
    ".github/workflows/ci.yml",
    "docs/architecture.md",
    "tests/test_controller_fix.py",
    "scripts/package.py",
)


def create(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in INCLUDE:
            source = ROOT / name
            if not source.is_file():
                raise FileNotFoundError(f"Expected release file missing: {name}")
            archive.write(source, f"steamdeck-controller-fix/{name}")
    print(f"Created {output} with {len(INCLUDE)} project files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/steamdeck-controller-fix.zip")
    create(parser.parse_args().output)
