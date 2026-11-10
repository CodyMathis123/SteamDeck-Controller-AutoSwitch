"""Offline tests for the remote release bootstrap (no sudo/network/Deck)."""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "scripts/install-remote.sh"


class RemoteInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.release = self.base / "release"
        self.release.mkdir()
        self.fakebin = self.base / "bin"
        self.fakebin.mkdir()
        self.sudo_log = self.base / "sudo.log"
        self.doctor_log = self.base / "doctor.log"
        self.curl_log = self.base / "curl.log"

        with zipfile.ZipFile(self.release / "steamdeck-controller-fix.zip", "w") as z:
            z.writestr("steamdeck-controller-fix/controller_fix.py", "# fixture\n")
            z.writestr("steamdeck-controller-fix/install.sh", "#!/bin/bash\nexit 0\n")
        self.update_sha()

        self.write_executable("curl", """#!/usr/bin/env bash
set -euo pipefail
out=''
url=''
while [[ $# -gt 0 ]]; do
  case "$1" in
    --output) out="$2"; shift 2 ;;
    *) url="$1"; shift ;;
  esac
done
printf '%s\\n' "$url" >> "$MOCK_CURL_LOG"
[[ "${MOCK_FAIL_CURL:-}" != yes ]] || exit 22
cp -- "$MOCK_RELEASE_DIR/${url##*/}" "$out"
""")
        self.write_executable("sudo", """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$MOCK_SUDO_LOG"
""")
        self.write_executable("python3", """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$MOCK_DOCTOR_LOG"
[[ "${MOCK_FAIL_DOCTOR:-}" != yes ]]
""")

    def update_sha(self):
        zip_file = self.release / "steamdeck-controller-fix.zip"
        sha = hashlib.sha256(zip_file.read_bytes()).hexdigest()
        (self.release / "SHA256SUMS").write_text(
            f"{sha}  steamdeck-controller-fix.zip\n", encoding="utf-8"
        )

    def write_executable(self, name, source):
        path = self.fakebin / name
        path.write_text(source, encoding="utf-8")
        path.chmod(0o755)

    def run_script(self, *args, **overrides):
        env = os.environ.copy()
        env.update({
            "PATH": f"{self.fakebin}{os.pathsep}{env['PATH']}",
            "TMPDIR": str(self.base),
            "MOCK_RELEASE_DIR": str(self.release),
            "MOCK_SUDO_LOG": str(self.sudo_log),
            "MOCK_DOCTOR_LOG": str(self.doctor_log),
            "MOCK_CURL_LOG": str(self.curl_log),
        })
        env.update(overrides)
        return subprocess.run(
            ["bash", str(BOOTSTRAP), *args], env=env,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False,
        )

    def test_success_verifies_then_runs_preflight_before_sudo(self):
        result = self.run_script("--no-persist-updates")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SHA-256 verification passed", result.stdout)
        self.assertIn(" doctor", self.doctor_log.read_text())
        self.assertIn("bash ", self.sudo_log.read_text())
        self.assertIn("--no-persist-updates", self.sudo_log.read_text())
        self.assertIn("releases/latest/download", self.curl_log.read_text())
        self.assertFalse(list(self.base.glob("steamdeck-autoswitch.*")))

    def test_pinned_version_uses_tag_asset_url(self):
        result = self.run_script(STEAMDECK_AUTOSWITCH_VERSION="v0.3.0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("releases/download/v0.3.0", self.curl_log.read_text())

    def test_mismatched_archive_fails_before_privileges(self):
        (self.release / "SHA256SUMS").write_text(
            "0" * 64 + "  steamdeck-controller-fix.zip\n", encoding="utf-8"
        )
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checksum mismatch", result.stderr)
        self.assertFalse(self.sudo_log.exists())
        self.assertFalse(self.doctor_log.exists())

    def test_bad_manifest_fails_before_privileges(self):
        (self.release / "SHA256SUMS").write_text("invalid\n", encoding="utf-8")
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid checksum manifest", result.stderr)
        self.assertFalse(self.sudo_log.exists())

    def test_preflight_failure_prevents_privileges(self):
        result = self.run_script(MOCK_FAIL_DOCTOR="yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.sudo_log.exists())

    def test_download_failure_prevents_install(self):
        result = self.run_script(MOCK_FAIL_CURL="yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Could not download", result.stderr)
        self.assertFalse(self.sudo_log.exists())

    def test_rejects_version_path_injection(self):
        result = self.run_script(STEAMDECK_AUTOSWITCH_VERSION="../../other")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Invalid version", result.stderr)
        self.assertFalse(self.curl_log.exists())

    def test_invalid_install_option_rejected_without_network(self):
        result = self.run_script("--delete-everything")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Unknown option", result.stderr)
        self.assertFalse(self.curl_log.exists())


if __name__ == "__main__":
    unittest.main()
