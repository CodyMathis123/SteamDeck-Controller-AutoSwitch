#!/usr/bin/env python3
"""Steam Deck Bluetooth gamepad -> built-in controller handoff.

No third-party Python packages. Run as root only for reconcile/restore.
Deliberately only considers Bluetooth (input BUS_BLUETOOTH=0x0005) joysticks.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

LOG = logging.getLogger("steamdeck-controller-fix")
VERSION = "0.3.0"
DECK_VENDOR, DECK_PRODUCT = "28de", "1205"
# Known Steam Deck internal controller HID interfaces. We check the *USB parent*
# VID/PID and each interface class before touching the driver's bind/unbind API.
EXPECTED_SUFFIXES = ("1.0", "1.1", "1.2")


@dataclass(frozen=True)
class Paths:
    input_class: Path = Path("/sys/class/input")
    udev_data: Path = Path("/run/udev/data")
    usb_devices: Path = Path("/sys/bus/usb/devices")
    usbhid_driver: Path = Path("/sys/bus/usb/drivers/usbhid")
    lock_file: Path = Path("/run/steamdeck-controller-fix.lock")
    # Volatile runtime state: no controller history is written to SSD.
    state_file: Path = Path("/run/steamdeck-controller-fix/state.json")


@dataclass(frozen=True)
class Gamepad:
    name: str
    vendor: str
    product: str
    sysname: str


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace").strip()


def _read_if_exists(path: Path) -> str:
    try:
        return _read(path)
    except (OSError, ValueError):
        return ""


def _hex_id(path: Path) -> str:
    raw = _read_if_exists(path)
    try:
        return f"{int(raw, 16):04x}"
    except ValueError:
        return ""


def _udev_is_joystick(record: Path) -> bool:
    data = _read_if_exists(record)
    return "E:ID_INPUT_JOYSTICK=1" in data.splitlines()


def _is_joystick(input_dir: Path, paths: Paths) -> bool:
    # /dev/input/jsN can be absent on some SteamOS configurations. Check the
    # udev database on the input parent and child event devices as well.
    if any(input_dir.glob("js*")):
        return True
    if _udev_is_joystick(paths.udev_data / f"+input:{input_dir.name}"):
        return True
    for event_dir in input_dir.glob("event*"):
        dev = _read_if_exists(event_dir / "dev")  # e.g. 13:68
        if dev and _udev_is_joystick(paths.udev_data / f"c{dev}"):
            return True
    return False


def bluetooth_gamepads(paths: Paths = Paths()) -> list[Gamepad]:
    """Enumerate live Bluetooth HID gamepads, including UHID-backed devices.

    Do not exclude all /devices/virtual paths: BlueZ creates legitimate Bluetooth
    HID input devices under /devices/virtual/misc/uhid/ on many Linux builds.
    """
    gamepads: list[Gamepad] = []
    for input_dir in sorted(paths.input_class.glob("input*")):
        if not input_dir.is_dir():
            continue
        # 0005 is Linux BUS_BLUETOOTH. Steam's uinput-created virtual pad is
        # typically BUS_VIRTUAL=0006 and won't be counted.
        if _hex_id(input_dir / "id/bustype") != "0005":
            continue
        vendor = _hex_id(input_dir / "id/vendor")
        product = _hex_id(input_dir / "id/product")
        if not vendor or not product:
            continue
        if (vendor, product) == (DECK_VENDOR, DECK_PRODUCT):
            continue
        if not _is_joystick(input_dir, paths):
            continue
        gamepads.append(Gamepad(
            name=_read_if_exists(input_dir / "name") or "Unknown gamepad",
            vendor=vendor,
            product=product,
            sysname=input_dir.name,
        ))
    return gamepads


def internal_interfaces(paths: Paths = Paths()) -> list[str]:
    """Locate the known internal controller by verified Valve USB VID/PID.

    Fail closed if the USB topology/USB interface classes differ from the known
    Deck layout. Do NOT unbind an arbitrary interface named 3-3:1.N.
    """
    candidates = []
    for device in sorted(paths.usb_devices.iterdir()):
        if not device.is_dir() or not (device / "idVendor").exists():
            continue
        if (_hex_id(device / "idVendor"), _hex_id(device / "idProduct")) == (
            DECK_VENDOR, DECK_PRODUCT
        ):
            candidates.append(device.name)
    if len(candidates) != 1:
        raise RuntimeError(
            "Expected exactly one internal Steam Deck USB device 28de:1205; "
            f"found {len(candidates)} ({', '.join(candidates) or 'none'}). "
            "No controls were changed."
        )
    parent = candidates[0]
    interfaces = [f"{parent}:{suffix}" for suffix in EXPECTED_SUFFIXES]
    for iface in interfaces:
        path = paths.usb_devices / iface
        if not path.is_dir():
            raise RuntimeError(f"Missing expected internal HID interface {iface}; no changes made")
        if _hex_id(path / "bInterfaceClass") != "0003":
            raise RuntimeError(f"Unexpected interface class at {iface}; no changes made")
        driver = path / "driver"
        if driver.is_symlink() and driver.resolve() != paths.usbhid_driver.resolve():
            raise RuntimeError(f"Unexpected driver on {iface}; no changes made")
    if not paths.usbhid_driver.is_dir():
        raise RuntimeError("usbhid driver directory not found; no changes made")
    for control in ("bind", "unbind"):
        if not (paths.usbhid_driver / control).exists():
            raise RuntimeError(f"usbhid {control} endpoint missing; no changes made")
    return interfaces


def is_bound(iface: str, paths: Paths) -> bool:
    return (paths.usbhid_driver / iface).exists()


def _write_hid_control(paths: Paths, action: str, iface: str) -> None:
    (paths.usbhid_driver / action).write_text(iface, encoding="ascii")


def change_state(interfaces: list[str], enable: bool, paths: Paths, dry_run: bool) -> list[str]:
    """Apply only necessary HID changes, returning successfully processed IDs.

    Log only successful sysfs requests. If a later interface fails, previous
    successful changes remain visible in the journal and the service fails;
    the next run will retry the remaining work.
    """
    action = "bind" if enable else "unbind"
    changed: list[str] = []
    for iface in interfaces:
        if is_bound(iface, paths) == enable:
            continue
        if dry_run:
            LOG.info("dry_run hid_%s interface=%s", action, iface)
            changed.append(iface)
            continue
        _write_hid_control(paths, action, iface)
        changed.append(iface)
        LOG.info("hid_%s interface=%s", action, iface)
    return changed


def _pad_key(pad: Gamepad) -> tuple[str, str, str, str]:
    return (pad.vendor, pad.product, pad.name, pad.sysname)


def _read_previous_gamepads(paths: Paths) -> list[Gamepad] | None:
    """Return None on first execution or damaged/incompatible runtime cache."""
    try:
        data = json.loads(paths.state_file.read_text(encoding="utf-8"))
        if data["schema"] != 1 or not isinstance(data["gamepads"], list):
            raise ValueError("unknown runtime state schema")
        return [Gamepad(**record) for record in data["gamepads"]]
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError, KeyError) as err:
        LOG.warning("state_cache_invalid reason=%s (will refresh)", err)
        return None


def _write_gamepads(paths: Paths, gamepads: list[Gamepad]) -> None:
    """Replace a root-owned JSON snapshot atomically in volatile /run."""
    parent = paths.state_file.parent
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = {
        "schema": 1,
        "gamepads": [vars(pad) for pad in sorted(gamepads, key=_pad_key)],
    }
    # Use a temporary file in the same directory for atomic replacement.
    fd, name = tempfile.mkstemp(prefix=".state-", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(payload, stream, sort_keys=True)
            stream.write("\n")
        os.replace(name, paths.state_file)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _log_gamepad_events(previous: list[Gamepad] | None, current: list[Gamepad]) -> None:
    if previous is None:
        LOG.info("startup version=%s gamepads=%d", VERSION, len(current))
        return
    old_counts = Counter(_pad_key(pad) for pad in previous)
    new_counts = Counter(_pad_key(pad) for pad in current)
    for (vendor, product, name, sysname), count in sorted((old_counts - new_counts).items()):
        for _ in range(count):
            LOG.info("controller_disconnected name=%r id=%s:%s input=%s", name, vendor, product, sysname)
    for (vendor, product, name, sysname), count in sorted((new_counts - old_counts).items()):
        for _ in range(count):
            LOG.info("controller_connected name=%r id=%s:%s input=%s", name, vendor, product, sysname)


def report(paths: Paths, verbose: bool = True) -> tuple[list[str], list[Gamepad]]:
    interfaces = internal_interfaces(paths)
    gamepads = bluetooth_gamepads(paths)
    if verbose:
        print(f"Internal Steam Deck HID interfaces: {', '.join(interfaces)}")
        for iface in interfaces:
            print(f"  {iface}: {'bound (enabled)' if is_bound(iface, paths) else 'unbound (disabled)'}")
        print(f"Bluetooth gamepads connected: {len(gamepads)}")
        for pad in gamepads:
            print(f"  {pad.name} [{pad.vendor}:{pad.product}] ({pad.sysname})")
        print("Desired built-in controller state:", "disabled" if gamepads else "enabled")
    return interfaces, gamepads


def run(action: str, paths: Paths = Paths()) -> None:
    if action == "doctor":
        if not paths.input_class.is_dir() or not paths.udev_data.is_dir():
            raise RuntimeError("Input/udev directories missing; is this a running Linux Steam Deck?")
        # Check hardware before reporting success.
        internal_interfaces(paths)
        print("Hardware preflight: safe-to-target internal controller detected.")
        report(paths)
        return
    if action == "status":
        report(paths)
        return
    if os.geteuid() != 0:
        raise RuntimeError("Changing hardware state requires root (sudo)")
    if action not in {"reconcile", "dry-run", "restore"}:
        raise ValueError(f"Unrecognized action: {action}")

    # Protect against racing one-shot calls triggered by multiple input events.
    paths.lock_file.parent.mkdir(parents=True, exist_ok=True)
    with paths.lock_file.open("w", encoding="ascii") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        interfaces, gamepads = report(paths, verbose=False)
        target_enabled = (not gamepads) if action != "restore" else True
        LOG.debug("reconcile action=%s gamepads=%d builtin_target=%s", action,
                  len(gamepads), "enabled" if target_enabled else "disabled")
        if action == "dry-run":
            change_state(interfaces, enable=target_enabled, paths=paths, dry_run=True)
            return

        # Apply hardware changes before snapshotting, so errors retry on the
        # next invocation without pretending the observation was completed.
        changed = change_state(interfaces, enable=target_enabled, paths=paths, dry_run=False)
        if action == "restore":
            if not changed:
                LOG.info("manual_restore already_enabled")
            else:
                LOG.info("manual_restore restored_interfaces=%d", len(changed))
            return

        previous = _read_previous_gamepads(paths)
        if previous is None or Counter(map(_pad_key, previous)) != Counter(map(_pad_key, gamepads)):
            _log_gamepad_events(previous, gamepads)
            _write_gamepads(paths, gamepads)
        if changed:
            LOG.info("builtin_state_changed target=%s interfaces=%d gamepads=%d",
                     "enabled" if target_enabled else "disabled", len(changed), len(gamepads))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("doctor", "status", "dry-run", "reconcile", "restore", "version"))
    parser.add_argument("--verbose", action="store_true", help="also log unchanged reconciliation checks")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s: %(message)s")
    if args.action == "version":
        print(VERSION)
        return 0
    try:
        run(args.action)
    except (OSError, RuntimeError, ValueError) as err:
        LOG.error("%s", err)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
