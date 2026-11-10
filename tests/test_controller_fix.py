import contextlib
import importlib.util
import io
import tempfile
import unittest
from unittest import mock
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "controller_fix.py"
spec = importlib.util.spec_from_file_location("controller_fix", SCRIPT)
module = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class FakeDeck(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.paths = module.Paths(
            input_class=root / "sys/class/input",
            udev_data=root / "run/udev/data",
            usb_devices=root / "sys/bus/usb/devices",
            usbhid_driver=root / "sys/bus/usb/drivers/usbhid",
            lock_file=root / "run/lock-file",
            state_file=root / "run/steamdeck-controller-fix/state.json",
        )
        for path in (self.paths.input_class, self.paths.udev_data,
                     self.paths.usb_devices, self.paths.usbhid_driver):
            path.mkdir(parents=True, exist_ok=True)
        self.write(self.paths.usb_devices / "3-3/idVendor", "28de\n")
        self.write(self.paths.usb_devices / "3-3/idProduct", "1205\n")
        for suffix in ("1.0", "1.1", "1.2"):
            self.write(self.paths.usb_devices / f"3-3:{suffix}/bInterfaceClass", "03\n")
            (self.paths.usbhid_driver / f"3-3:{suffix}").symlink_to(
                self.paths.usb_devices / f"3-3:{suffix}", target_is_directory=True
            )
            (self.paths.usb_devices / f"3-3:{suffix}/driver").symlink_to(
                self.paths.usbhid_driver, target_is_directory=True
            )
        self.write(self.paths.usbhid_driver / "bind", "")
        self.write(self.paths.usbhid_driver / "unbind", "")

    @staticmethod
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)

    def add_gamepad(self, name="Xbox Wireless Controller", bus="0005", input_id="input12",
                    joystick=True, udev=False):
        # This path name intentionally contains 'virtual/misc/uhid' to simulate
        # how a *real* Bluetooth gamepad is represented by BlueZ.
        real = self.paths.input_class.parent.parent.parent / "devices/virtual/misc/uhid/0005:045E:0B13.0001/input" / input_id
        self.write(real / "id/bustype", bus)
        self.write(real / "id/vendor", "045e")
        self.write(real / "id/product", "0b13")
        self.write(real / "name", name)
        if joystick:
            if udev:
                self.write(self.paths.udev_data / f"+input:{input_id}", "E:ID_INPUT_JOYSTICK=1\n")
            else:
                (real / "js0").mkdir()
        (self.paths.input_class / input_id).symlink_to(real, target_is_directory=True)
        return real

    def kernel_write(self, paths, action, iface):
        """Fake kernel sysfs bind/unbind side effects for end-to-end tests."""
        interface = paths.usb_devices / iface
        link = paths.usbhid_driver / iface
        driver = interface / "driver"
        if action == "unbind":
            link.unlink()
            driver.unlink()
        elif action == "bind":
            link.symlink_to(interface, target_is_directory=True)
            driver.symlink_to(paths.usbhid_driver, target_is_directory=True)
        else:
            raise AssertionError(action)

    def reconcile(self, action="reconcile"):
        with mock.patch.object(module.os, "geteuid", return_value=0), \
             mock.patch.object(module, "_write_hid_control", side_effect=self.kernel_write):
            module.run(action, self.paths)

    def test_quiet_polling_logs_only_initial_state(self):
        with self.assertLogs(module.LOG, level="INFO") as captured:
            self.reconcile()
        self.assertTrue(any("startup version=" in line for line in captured.output))
        initial_mtime = self.paths.state_file.stat().st_mtime_ns
        with self.assertNoLogs(module.LOG, level="INFO"):
            self.reconcile()
            self.reconcile()
        self.assertEqual(initial_mtime, self.paths.state_file.stat().st_mtime_ns)

    def test_connection_disconnection_log_once_and_toggle_all_interfaces(self):
        self.reconcile()
        self.add_gamepad()
        with self.assertLogs(module.LOG, level="INFO") as connected:
            self.reconcile()
        self.assertEqual(sum("controller_connected" in line for line in connected.output), 1)
        self.assertEqual(sum("hid_unbind" in line for line in connected.output), 3)
        for iface in module.internal_interfaces(self.paths):
            self.assertFalse(module.is_bound(iface, self.paths))
        with self.assertNoLogs(module.LOG, level="INFO"):
            self.reconcile()
        (self.paths.input_class / "input12").unlink()
        with self.assertLogs(module.LOG, level="INFO") as disconnected:
            self.reconcile()
        self.assertEqual(sum("controller_disconnected" in line for line in disconnected.output), 1)
        self.assertEqual(sum("hid_bind" in line for line in disconnected.output), 3)
        for iface in module.internal_interfaces(self.paths):
            self.assertTrue(module.is_bound(iface, self.paths))
        with self.assertNoLogs(module.LOG, level="INFO"):
            self.reconcile()

    def test_second_gamepad_connects_without_unnecessary_hid_changes(self):
        self.add_gamepad(input_id="input12")
        self.reconcile()
        self.add_gamepad(name="DualSense", input_id="input13")
        with self.assertLogs(module.LOG, level="INFO") as captured:
            self.reconcile()
        self.assertEqual(sum("controller_connected" in line for line in captured.output), 1)
        self.assertFalse(any("hid_unbind" in line for line in captured.output))
        (self.paths.input_class / "input12").unlink()
        with self.assertLogs(module.LOG, level="INFO") as captured:
            self.reconcile()
        self.assertEqual(sum("controller_disconnected" in line for line in captured.output), 1)
        self.assertFalse(any("hid_bind" in line for line in captured.output))

    def test_restore_is_logged_and_automatic_reconciliation_resumes(self):
        self.add_gamepad()
        self.reconcile()
        with self.assertLogs(module.LOG, level="INFO") as captured:
            self.reconcile("restore")
        self.assertTrue(any("manual_restore restored_interfaces=3" in x for x in captured.output))
        self.assertEqual(module._read_previous_gamepads(self.paths)[0].name, "Xbox Wireless Controller")
        with self.assertLogs(module.LOG, level="INFO") as captured:
            self.reconcile()
        self.assertEqual(sum("hid_unbind" in line for line in captured.output), 3)
        self.assertFalse(any("controller_connected" in line for line in captured.output))

    def test_dry_run_does_not_write_runtime_state(self):
        self.add_gamepad()
        with mock.patch.object(module.os, "geteuid", return_value=0):
            module.run("dry-run", self.paths)
        self.assertFalse(self.paths.state_file.exists())
        self.assertTrue(all(module.is_bound(i, self.paths) for i in module.internal_interfaces(self.paths)))

    def test_corrupt_state_cache_is_recovered(self):
        self.paths.state_file.parent.mkdir(parents=True)
        self.paths.state_file.write_text("{broken-json")
        with self.assertLogs(module.LOG, level="WARNING") as captured:
            self.reconcile()
        self.assertTrue(any("state_cache_invalid" in line for line in captured.output))
        self.assertEqual(module._read_previous_gamepads(self.paths), [])

    def test_failed_hardware_write_does_not_update_cache(self):
        self.add_gamepad()
        def fails_on_second(paths, action, iface):
            if iface.endswith("1.1"):
                raise OSError("simulated USB error")
            self.kernel_write(paths, action, iface)
        with mock.patch.object(module.os, "geteuid", return_value=0), \
             mock.patch.object(module, "_write_hid_control", side_effect=fails_on_second):
            with self.assertLogs(module.LOG, level="INFO") as captured:
                with self.assertRaisesRegex(OSError, "simulated USB error"):
                    module.run("reconcile", self.paths)
        self.assertFalse(self.paths.state_file.exists())
        self.assertTrue(any("hid_unbind interface=3-3:1.0" in x for x in captured.output))
        self.reconcile()
        self.assertEqual(len(module._read_previous_gamepads(self.paths)), 1)
        self.assertFalse(any(module.is_bound(i, self.paths) for i in module.internal_interfaces(self.paths)))

    def test_version_is_exposed(self):
        self.assertRegex(module.VERSION, r"^\d+\.\d+\.\d+$")

    def test_preflight_finds_three_verified_internal_hid_interfaces(self):
        self.assertEqual(module.internal_interfaces(self.paths), [
            "3-3:1.0", "3-3:1.1", "3-3:1.2"
        ])

    def test_bt_gamepad_in_uhid_virtual_path_is_detected(self):
        self.add_gamepad()
        self.assertEqual([x.name for x in module.bluetooth_gamepads(self.paths)],
                         ["Xbox Wireless Controller"])

    def test_usb_and_uinput_devices_not_counted(self):
        self.add_gamepad(bus="0003", input_id="input11")
        self.add_gamepad(bus="0006", input_id="input12")
        self.assertEqual(module.bluetooth_gamepads(self.paths), [])

    def test_bt_keyboard_not_counted(self):
        self.add_gamepad(name="Bluetooth Keyboard", joystick=False)
        self.assertEqual(module.bluetooth_gamepads(self.paths), [])

    def test_udev_database_gamepad_detected_without_js_node(self):
        self.add_gamepad(joystick=True, udev=True)
        self.assertEqual(len(module.bluetooth_gamepads(self.paths)), 1)

    def test_gamepad_detected_using_event_node_udev_record(self):
        real = self.add_gamepad(joystick=False)
        self.write(real / "event18/dev", "13:82\n")
        self.write(self.paths.udev_data / "c13:82", "E:ID_INPUT_JOYSTICK=1\n")
        self.assertEqual(len(module.bluetooth_gamepads(self.paths)), 1)

    def test_disconnecting_last_bluetooth_gamepad_restores_desired_state(self):
        self.add_gamepad(input_id="input12")
        self.add_gamepad(name="DualSense Wireless Controller", input_id="input13")
        self.assertEqual(len(module.bluetooth_gamepads(self.paths)), 2)
        (self.paths.input_class / "input12").unlink()
        self.assertEqual(len(module.bluetooth_gamepads(self.paths)), 1)
        (self.paths.input_class / "input13").unlink()
        self.assertEqual(len(module.bluetooth_gamepads(self.paths)), 0)

    def test_refuses_missing_driver_endpoint(self):
        (self.paths.usbhid_driver / "unbind").unlink()
        with self.assertRaisesRegex(RuntimeError, "endpoint missing"):
            module.internal_interfaces(self.paths)

    def test_refuses_to_touch_wrong_usb_product(self):
        self.write(self.paths.usb_devices / "3-3/idProduct", "9999\n")
        with self.assertRaisesRegex(RuntimeError, "28de:1205"):
            module.internal_interfaces(self.paths)

    def test_refuses_mismatched_interface_class(self):
        self.write(self.paths.usb_devices / "3-3:1.1/bInterfaceClass", "08\n")
        with self.assertRaisesRegex(RuntimeError, "Unexpected interface class"):
            module.internal_interfaces(self.paths)

    def test_refuses_unexpected_driver(self):
        driver = self.paths.usb_devices / "3-3:1.0/driver"
        driver.unlink()
        other = self.paths.usbhid_driver.parent / "some-other-driver"
        other.mkdir()
        driver.symlink_to(other, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "Unexpected driver"):
            module.internal_interfaces(self.paths)

    def test_dry_run_is_readonly(self):
        interfaces = module.internal_interfaces(self.paths)
        self.add_gamepad()
        module.change_state(interfaces, enable=False, paths=self.paths, dry_run=True)
        self.assertEqual((self.paths.usbhid_driver / "unbind").read_text(), "")

    def test_unbind_when_external_bluetooth_connected(self):
        interfaces = module.internal_interfaces(self.paths)
        self.add_gamepad()
        module.change_state(interfaces, enable=False, paths=self.paths, dry_run=False)
        self.assertEqual((self.paths.usbhid_driver / "unbind").read_text(), "3-3:1.2")

    def test_restore_rebinds_missing_interfaces(self):
        interfaces = module.internal_interfaces(self.paths)
        (self.paths.usbhid_driver / "3-3:1.1").unlink()
        (self.paths.usb_devices / "3-3:1.1/driver").unlink()
        module.change_state(interfaces, enable=True, paths=self.paths, dry_run=False)
        self.assertEqual((self.paths.usbhid_driver / "bind").read_text(), "3-3:1.1")

    def test_status_reports_recommendation(self):
        self.add_gamepad()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            module.report(self.paths)
        self.assertIn("Bluetooth gamepads connected: 1", out.getvalue())
        self.assertIn("Desired built-in controller state: disabled", out.getvalue())


if __name__ == "__main__":
    unittest.main()
