#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$(realpath -- "$0")")"

usage() {
  cat <<'HELP'
Usage: sudo bash install.sh [--persist-updates | --no-persist-updates]

Install or upgrade the Steam Deck Bluetooth controller handoff in place.
By default, leave any existing SteamOS update-persistence setting unchanged.
New installations do not create an update keep-list unless requested.

  --persist-updates     Opt into a SteamOS update keep-list (see README warning).
  --no-persist-updates  Remove this project's existing update keep-list.
HELP
}

persistence=unchanged
for arg in "$@"; do
  case "$arg" in
    --persist-updates) persistence=yes ;;
    --no-persist-updates) persistence=no ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown argument: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ $(id -u) != 0 ]]; then echo 'Run: sudo bash ./install.sh' >&2; exit 1; fi
if [[ ! -r /etc/steamos-release ]]; then
  echo 'SteamOS not detected (/etc/steamos-release missing); refusing to install.' >&2
  exit 1
fi
for tool in python3 systemctl udevadm install; do
  command -v "$tool" >/dev/null || { echo "Missing required tool: $tool" >&2; exit 1; }
done

# Never silently overwrite another controller-disabling implementation.
for other in /etc/udev/rules.d/99-disable-steam-input.rules; do
  if [[ -e "$other" ]]; then
    echo "Conflicting controller-disabler rule detected: $other" >&2
    echo 'Remove the old disabler first; do not run two of them together.' >&2
    exit 1
  fi
done

installed_script=/etc/steamdeck-controller-fix/controller_fix.py
installed_rule=/etc/udev/rules.d/92-steamdeck-controller-fix.rules
installed_service=/etc/systemd/system/steamdeck-controller-fix.service
keep_list=/etc/atomic-update.conf.d/steamdeck-controller-fix.conf

# Only upgrade files that can be positively identified as belonging to us.
if [[ -e "$installed_script" || -e "$installed_rule" || -e "$installed_service" ]]; then
  if [[ ! -f "$installed_script" ]] || \
     ! grep -Fq 'Steam Deck Bluetooth gamepad -> built-in controller handoff.' "$installed_script" || \
     [[ ! -f "$installed_rule" ]] || \
     ! grep -Fq 'steamdeck-controller-fix.service' "$installed_rule" || \
     [[ ! -f "$installed_service" ]] || \
     ! grep -Fq '/etc/steamdeck-controller-fix/controller_fix.py reconcile' "$installed_service"; then
    echo 'Existing installation files do not match this project; refusing to overwrite.' >&2
    exit 1
  fi
  echo 'Recognized existing installation; upgrading in place.'
fi

# Inspection happens *before* writing config or touching hardware.
python3 ./controller_fix.py doctor || {
  echo 'Preflight failed. Nothing installed and no controller state was changed.' >&2
  exit 1
}

# A running timer may restart the service while its files are being replaced.
systemctl stop steamdeck-controller-fix.timer 2>/dev/null || true
systemctl stop steamdeck-controller-fix.service 2>/dev/null || true

mkdir -p /etc/steamdeck-controller-fix /etc/udev/rules.d /etc/systemd/system
install -m 0644 controller_fix.py "$installed_script"
install -m 0755 uninstall.sh /etc/steamdeck-controller-fix/uninstall.sh
install -m 0644 92-steamdeck-controller-fix.rules "$installed_rule"
install -m 0644 steamdeck-controller-fix.service "$installed_service"
install -m 0644 steamdeck-controller-fix.timer /etc/systemd/system/steamdeck-controller-fix.timer

case "$persistence" in
  yes)
    mkdir -p /etc/atomic-update.conf.d
    cat > "$keep_list" <<'KEEP'
/etc/steamdeck-controller-fix/controller_fix.py
/etc/steamdeck-controller-fix/uninstall.sh
/etc/udev/rules.d/92-steamdeck-controller-fix.rules
/etc/systemd/system/steamdeck-controller-fix.service
/etc/systemd/system/steamdeck-controller-fix.timer
KEEP
    chmod 0644 "$keep_list"
    ;;
  no) rm -f "$keep_list" ;;
esac

systemctl daemon-reload
udevadm control --reload
systemctl enable --now steamdeck-controller-fix.timer
if ! systemctl restart steamdeck-controller-fix.service; then
  echo 'Failed to activate controller switching. Stopping automation and restoring Deck controls.' >&2
  systemctl disable --now steamdeck-controller-fix.timer || true
  python3 "$installed_script" restore || true
  exit 1
fi
cat <<'SUCCESS'

Installed/updated and activated. Bluetooth gamepad events trigger a one-shot
check; a 30-second timer provides a backup if an event is missed.

STATUS:    python3 /etc/steamdeck-controller-fix/controller_fix.py status
LOGS:      sudo journalctl -u steamdeck-controller-fix.service -n 40 --no-pager
RECOVERY:  sudo python3 /etc/steamdeck-controller-fix/controller_fix.py restore
UNINSTALL: sudo /etc/steamdeck-controller-fix/uninstall.sh

This disables internal HID controls (NOT Steam Input globally).
SUCCESS
if [[ -e "$keep_list" ]]; then
  echo 'NOTICE: SteamOS update keep-list is enabled. Read README: SteamOS 3.9.x update caveat.'
else
  echo 'NOTICE: No update keep-list; after a SteamOS update you may need to reinstall.'
fi
