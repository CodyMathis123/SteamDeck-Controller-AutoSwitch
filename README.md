# SteamDeck-Controller-AutoSwitch

**Automatically disable the Steam Deck's built-in controls while a Bluetooth gamepad is connected, and restore them when the last gamepad disconnects.** This addresses games that assign the Deck itself to Player 1 instead of an external controller. It does **not** disable Steam Input globally.

Works without a Python background daemon, third-party Python packages, or changes to SteamOS's read-only `/usr` filesystem. The service runs briefly when `udev` sees an input-device change; a systemd timer performs a fallback reconciliation every 30 seconds.

> **Hardware-specific software:** This currently supports the Steam Deck controller USB device `28de:1205` with its three expected HID interfaces. Other device layouts intentionally fail the preflight check. Keep SSH or a keyboard available for the first installation and any upgrade.

## One-line install / upgrade (Steam Deck Konsole)

Copy/paste this command **on the Steam Deck** (Desktop Mode, Konsole):

```bash
curl -fsSL https://raw.githubusercontent.com/CodyMathis123/SteamDeck-Controller-AutoSwitch/Production/scripts/install-remote.sh | bash
```

The bootstrap downloads the **latest published GitHub Release** ZIP and `SHA256SUMS`, verifies the ZIP with SHA-256, runs a **read-only hardware preflight**, then uses `sudo` to install or upgrade. It performs network downloads **before** privilege escalation, temporarily extracts under `/tmp`, and cleans up afterward. It does not replace unrelated controller-disabling tools or disable Steam Input globally.

- Install a particular released version: `curl -fsSL https://raw.githubusercontent.com/CodyMathis123/SteamDeck-Controller-AutoSwitch/Production/scripts/install-remote.sh | STEAMDECK_AUTOSWITCH_VERSION=v0.3.1 bash`
- For an older install with a SteamOS update keep-list, remove it using: `curl -fsSL https://raw.githubusercontent.com/CodyMathis123/SteamDeck-Controller-AutoSwitch/Production/scripts/install-remote.sh | bash -s -- --no-persist-updates`
- For those who prefer to inspect downloaded scripts before execution, open [the bootstrap source](scripts/install-remote.sh) or download it first and run it after inspection.

**Security note:** SHA-256 detects corruption or mismatches between the downloaded files; it is **not** independent cryptographic proof of publisher identity because the ZIP and checksum are hosted together. Running any remote shell script requires trusting the repository and HTTPS delivery. The installer will require a `sudo` password, and SSH/keyboard recovery is recommended for the first run.

**Release process:** GitHub Actions runs tests and creates a versioned GitHub Release on a new `VERSION` in `controller_fix.py` pushed to `Production`. Release files are `steamdeck-controller-fix.zip` and `SHA256SUMS`. Already tagged versions are not overwritten. [View releases](https://github.com/CodyMathis123/SteamDeck-Controller-AutoSwitch/releases).

## Manual install or upgrade

Copy/extract the project to the Deck (for example `/home/deck/steamdeck-controller-fix`), switch to Desktop Mode, and run:

```bash
cd ~/steamdeck-controller-fix
python3 controller_fix.py doctor          # Read-only hardware preflight
sudo bash install.sh                      # Installs or upgrades in place
python3 /etc/steamdeck-controller-fix/controller_fix.py status
```

A configured `sudo` password is required (`passwd` sets one if needed). An existing installation of **this project** is recognized and updated in place; you **do not** need to uninstall first. Unrelated controller-disabler files are not overwritten.

The installer copies the project under `/etc`, installs a udev rule and systemd units, and immediately runs one reconciliation. It refuses to touch unsupported HID hardware. It does not modify games or Steam configuration.

**SteamOS update persistence:** New installations do not create a custom atomic-update keep-list by default. You may need to reinstall after a SteamOS upgrade. Use `sudo bash install.sh --persist-updates` to opt into a keep-list, or `sudo bash install.sh --no-persist-updates` to remove this project's keep-list. **Upgrades preserve the existing choice**, including the keep-list created by version 0.1.x. See [SteamOS 3.9.x caveat](#steamos-39x-update-caveat) before opting in.

## Expected behavior

1. With no Bluetooth gamepad, the Steam Deck's three built-in HID interfaces are bound and its own controls work.
2. When a Bluetooth joystick-class input device appears, the built-in HID interfaces are unbound. Steam/game controller ordering can then favor the external controller.
3. When the **last** Bluetooth joystick disappears, the built-in interfaces are bound again.
4. If the udev event is missed, the 30-second systemd timer corrects the state.

Only Bluetooth gamepads (`BUS_BLUETOOTH=0005`) count. Wired gamepads, keyboards and virtual Steam Input devices don't trigger the switch. Actual in-game player assignment is ultimately controlled by Steam/the game.

## Commands

```bash
# Human-readable current USB and Bluetooth state (unprivileged)
python3 /etc/steamdeck-controller-fix/controller_fix.py status

# Show version
python3 /etc/steamdeck-controller-fix/controller_fix.py version

# Hardware preflight
python3 /etc/steamdeck-controller-fix/controller_fix.py doctor

# What would change (does not touch sysfs; needs root for the lock)
sudo python3 /etc/steamdeck-controller-fix/controller_fix.py dry-run

# Reconcile immediately, even without an input-device event
sudo python3 /etc/steamdeck-controller-fix/controller_fix.py reconcile

# Manually re-enable Deck controls. Automation may disable them again at next check.
sudo python3 /etc/steamdeck-controller-fix/controller_fix.py restore

# Disable switching and fully remove this project (restores internal controls)
sudo /etc/steamdeck-controller-fix/uninstall.sh
```

If Deck controls become unavailable, use SSH or a keyboard to run `restore` or `uninstall.sh`. A reboot restores the USB drivers' initial bindings, but active automation can disable them again if a Bluetooth gamepad is still connected.

## Event-oriented logging

```bash
# Recent activity, only lines emitted by this service
sudo journalctl -t steamdeck-controller-fix -n 60 --no-pager

# Watch live while switching the Xbox controller on/off
sudo journalctl -t steamdeck-controller-fix -f

# Include systemd service lifecycle and error messages too
sudo journalctl -u steamdeck-controller-fix.service --since today -n 100 --no-pager
```

Version 0.2+ logs **controller connections/disconnections, successful HID bind/unbind requests, manual restores, first-run state, warnings and errors**. The script does **not** emit an INFO line on each unchanged 30-second poll. `journalctl -t steamdeck-controller-fix` shows only script messages, filtering out periodic systemd service-lifecycle chatter. Run `sudo python3 .../controller_fix.py reconcile --verbose` if you want DEBUG output for an unchanged check.

Example (illustrative, not captured from hardware):

```text
INFO: startup version=0.2.0 gamepads=1
INFO: hid_unbind interface=3-3:1.0
INFO: hid_unbind interface=3-3:1.1
INFO: hid_unbind interface=3-3:1.2
INFO: builtin_state_changed target=disabled interfaces=3 gamepads=1
INFO: controller_disconnected name='Xbox Wireless Controller' id=045e:0b22 input=input32
INFO: hid_bind interface=3-3:1.0
INFO: hid_bind interface=3-3:1.1
INFO: hid_bind interface=3-3:1.2
INFO: builtin_state_changed target=enabled interfaces=3 gamepads=0
INFO: controller_connected name='Xbox Wireless Controller' id=045e:0b22 input=input32
INFO: builtin_state_changed target=disabled interfaces=3 gamepads=1
```

To detect transitions between short-lived service invocations, the script saves a tiny JSON snapshot at `/run/steamdeck-controller-fix/state.json`. `/run` is volatile (normally tmpfs) so the snapshot does **not** generate SSD writes. It is erased at reboot and uninstallation. `journald` may store journal records on disk depending on SteamOS configuration; those records are small and limited to meaningful events. See [architecture](docs/architecture.md).

**Service status:**

```bash
systemctl status steamdeck-controller-fix.timer --no-pager
sudo systemctl status steamdeck-controller-fix.service --no-pager
```

The `.service` is `Type=oneshot` and normally becomes *inactive (dead)* after each successful execution. **That is expected.** The `.timer` should remain *active (waiting)*.

## Safety and limitations

- Before changing anything, the script requires exactly one USB parent `28de:1205`, three expected HID-class interfaces, and the expected driver. The observed interface names are discovered from the USB parent, **not hard-coded** to `3-3`.
- HID changes are serialized using an exclusive `flock`, and each already-correct interface is skipped.
- Failed sysfs writes cause the service to fail; the next event/timer run can retry. State cache is only updated after successful reconciliation.
- Disabling internal USB HID interfaces is not the same as disabling all Steam Input functionality; the Steam client and games may need a moment to recognize device changes.
- The udev rule receives input add/remove events; reconciliation rescans all current Bluetooth input devices rather than relying on stale event metadata.
- This project does not modify your Bluetooth pairing or controller firmware.
- The original switching behavior was reported working in **Starfield and Cyberpunk 2077** on a physical Steam Deck. The v0.2 logging/upgrade implementation has automated fixture coverage but still needs a physical Deck upgrade test.

## SteamOS 3.9.x update caveat

Custom `/etc/atomic-update.conf.d` keep-list fragments are supported by SteamOS, but an [October 2026 SteamOS 3.9.3 issue](https://github.com/ValveSoftware/SteamOS/issues/2957) reports some OS updates hanging when custom fragments interact with the `/etc` overlay. This is an upstream SteamOS concern, not a controller-switching issue. The original v0.1 installer created a custom keep-list; v0.2 **does not delete that existing setting without your permission**, so an upgrade from v0.1 still has it enabled. To opt out:

```bash
cd ~/steamdeck-controller-fix
sudo bash install.sh --no-persist-updates
```

Then keep the ZIP/source on the Deck for reinstallation after major SteamOS updates. There is no guarantee any custom systemd or udev integration will survive an OS update unchanged even with a keep-list.

## Development

Requires Python **3.10+** and standard Linux tools (`systemd`, `udev`). There are no pip requirements.

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q controller_fix.py tests
bash -n install.sh uninstall.sh
python3 scripts/package.py --output /tmp/steamdeck-controller-fix.zip
unzip -t /tmp/steamdeck-controller-fix.zip
```

The test suite simulates Linux sysfs/udev and requires neither root nor a Steam Deck. It covers controller detection, recovery, cache/lifecycle logging, and partial write failures. CI runs on GitHub Actions; it does **not** prove physical Steam Deck compatibility. See [contributing](CONTRIBUTING.md) and [architecture](docs/architecture.md).

## Acknowledgments

Inspired by [scawp/Steam-Deck.Auto-Disable-Steam-Controller](https://github.com/scawp/Steam-Deck.Auto-Disable-Steam-Controller) and [nateify/SteamDeck-Builtin-Disabler](https://github.com/nateify/SteamDeck-Builtin-Disabler). This implementation is independent and limited to Bluetooth joystick-class input devices.

## License

Licensed under the **[MIT License](LICENSE)** (starting with **v0.3.1**).

You may use, copy, modify, redistribute, and sell the software, including for commercial purposes, provided you include the copyright and license notice in copies or substantial portions. You do **not** have to publish modifications or distribute source code.

Earlier published releases (including v0.3.0) retain the PolyForm Noncommercial license text included in those release archives. Those existing artifacts are not changed by this relicensing. See [releases](https://github.com/CodyMathis123/SteamDeck-Controller-AutoSwitch/releases).
