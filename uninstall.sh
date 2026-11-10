#!/usr/bin/env bash
set -euo pipefail
if [[ $(id -u) != 0 ]]; then echo 'Run: sudo bash ./uninstall.sh' >&2; exit 1; fi
# Stop automatic re-disabling before restoring Deck's controls.
systemctl disable --now steamdeck-controller-fix.timer 2>/dev/null || true
systemctl stop steamdeck-controller-fix.service 2>/dev/null || true
rm -f /etc/udev/rules.d/92-steamdeck-controller-fix.rules
udevadm control --reload
# If the script is missing/mismatched, reboot is the safe fallback.
if [[ -f /etc/steamdeck-controller-fix/controller_fix.py ]]; then
  if ! /usr/bin/python3 /etc/steamdeck-controller-fix/controller_fix.py restore; then
    echo 'Automatic controller restore failed. Reboot to restore normal USB bindings.' >&2
  fi
fi
rm -f /etc/systemd/system/steamdeck-controller-fix.service \
      /etc/systemd/system/steamdeck-controller-fix.timer \
      /etc/atomic-update.conf.d/steamdeck-controller-fix.conf
rm -f /etc/steamdeck-controller-fix/controller_fix.py \
      /etc/steamdeck-controller-fix/uninstall.sh
rmdir /etc/steamdeck-controller-fix 2>/dev/null || true
rm -f /run/steamdeck-controller-fix/state.json
rmdir /run/steamdeck-controller-fix 2>/dev/null || true
systemctl daemon-reload
printf '%s\n' 'Uninstalled. If built-in controls are still disabled, reboot your Steam Deck.'
