# Contributing

This tool intentionally operates at the Linux kernel driver level. Changes to device identification or bind/unbind logic require particular care.

1. Keep the script Python-standard-library-only and compatible with Python 3.10+.
2. Add a synthetic sysfs/udev unit test for each behavioral change. Include negative tests for mistaken HID targets.
3. Run `python3 -m unittest discover -s tests -v`, `bash -n install.sh uninstall.sh scripts/install-remote.sh`, and `python3 scripts/package.py --output /tmp/steamdeck-controller-fix.zip` before opening a pull request.
4. Do not add support for new VID/PID combinations or USB layouts based solely on guesswork. Gather read-only `doctor` and `status` output from the device first.
5. Avoid periodic INFO logging and persistent controller state writes; transitions are logged, but unchanged polls stay quiet.
6. Never introduce automatic privileged network downloads or commands that disable the immutable SteamOS root filesystem.
7. When changing installation behavior, keep upgrades from previously released installs reversible and update the README and CHANGELOG.
8. For releases, bump `VERSION` in `controller_fix.py` (X.Y.Z) when committing to `Production`. CI publishes an immutable GitHub Release on a new version; never replace an existing release artifact.

Hardware validation should include: initial boot with and without Bluetooth controller, connect, disconnect, two controllers connected, manual restore, SteamOS sleep/wake, and uninstall. A successful simulated test does not imply physical hardware validation.

Contributions are welcome for noncommercial use under the project's [PolyForm Noncommercial License 1.0.0](LICENSE). By submitting a contribution, you agree to license that contribution under the same terms. Do not submit code you do not have rights to license.
