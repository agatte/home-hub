"""Power policy tests use disposable files and mocked OS calls only."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DesktopPower(unittest.TestCase):
    def setUp(self):
        self.module = load("homehub-desktop-power")
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        path = Path(self.temporary.name) / "settings.json"
        self.path = path
        patcher = patch.object(self.module, "snapshot_path", return_value=path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.calls = []
        self.values = {pair: f"original-{index}" for index, pair in enumerate(self.module.TRAVEL)}

    def command(self, *args):
        self.calls.append(args)
        if args[:2] == ("gsettings", "get"):
            return self.values[(args[2], args[3])]
        return ""

    def test_travel_saves_baseline_before_desktop_changes_and_releases_system_last(self):
        with patch.object(self.module, "command", side_effect=self.command):
            self.module.apply("travel")
        self.assertTrue(self.path.exists())
        self.assertEqual(self.calls[-1], ("sudo", "-n", self.module.ROOT_HELPER, "travel"))
        self.assertEqual(sum(c[:2] == ("gsettings", "get") for c in self.calls), len(self.values))

    def test_return_blocks_system_sleep_before_restoring_exact_desktop_baseline(self):
        with patch.object(self.module, "command", side_effect=self.command):
            self.module.apply("travel")
            self.calls.clear()
            self.module.apply("home")
        self.assertEqual(self.calls[0], ("sudo", "-n", self.module.ROOT_HELPER, "home"))
        self.assertEqual({(c[2], c[3]): c[4] for c in self.calls[1:]}, self.values)
        self.assertTrue(self.path.exists(), "Retain baseline until Return Home commits")

    def test_repeated_travel_does_not_overwrite_home_snapshot(self):
        with patch.object(self.module, "command", side_effect=self.command):
            self.module.apply("travel")
            original = self.path.read_bytes()
            self.values = {pair: "travel-value" for pair in self.values}
            self.module.apply("travel")
        self.assertEqual(self.path.read_bytes(), original)

    def test_failed_travel_restores_desktop_baseline(self):
        def failed(*args):
            if args[0] == "sudo":
                raise RuntimeError("helper failed")
            return self.command(*args)
        with patch.object(self.module, "command", side_effect=failed):
            with self.assertRaisesRegex(RuntimeError, "helper failed"):
                self.module.apply("travel")
        restored = [c for c in self.calls if c[:2] == ("gsettings", "set")][-len(self.values):]
        self.assertEqual({(c[2], c[3]): c[4] for c in restored}, self.values)

    def test_finished_home_allows_a_fresh_baseline_on_next_trip(self):
        with patch.object(self.module, "command", side_effect=self.command):
            self.module.apply("travel")
            self.module.apply("home")
            self.module.apply("finish-home")
        self.assertFalse(self.path.exists())

    def test_malformed_snapshot_never_runs_unapproved_keys(self):
        self.path.write_text('[{"schema":"other","key":"other","value":"true"}]')
        with patch.object(self.module, "command", side_effect=self.command):
            with self.assertRaisesRegex(RuntimeError, "Invalid desktop power snapshot"):
                self.module.apply("home")
        self.assertEqual(len(self.calls), 1)

    def test_quiet_updates_and_restore_preserve_original_preferences(self):
        originals = {}
        def command(*args):
            self.calls.append(args)
            if args[:2] == ("gsettings", "list-keys"):
                return "auto-launch\n"
            if args[:2] == ("gsettings", "get"):
                value = "7" if args[3] == "regular-auto-launch-interval" else "false"
                originals[(args[2], args[3])] = value
                return value
            return ""
        with patch.object(self.module, "command", side_effect=command):
            self.module.update_prompts("quiet-updates")
            self.calls.clear()
            self.module.update_prompts("restore-updates")
        sets = [c for c in self.calls if c[:2] == ("gsettings", "set")]
        self.assertEqual({(c[2], c[3]): c[4] for c in sets}, originals)


class SystemPower(unittest.TestCase):
    def setUp(self):
        self.module = load("homehub-system-power")

    def test_only_fixed_modes_are_allowed(self):
        with self.assertRaises(ValueError):
            self.module.apply("arbitrary")

    def test_home_never_unmasks_sleep(self):
        calls = []
        with patch.object(self.module, "validate_mask_paths"), patch.object(self.module, "write_lid_config"), patch.object(self.module, "run", side_effect=lambda *a: calls.append(a)):
            self.module.apply("home")
        self.assertEqual(calls[0][1], "mask")
        self.assertFalse(any("unmask" in call for call in calls))

    def test_custom_target_override_is_rejected_before_system_changes(self):
        with patch.object(self.module, "Path") as path, patch.object(self.module, "run") as run:
            path.return_value.__truediv__.return_value.is_symlink.return_value = False
            path.return_value.__truediv__.return_value.exists.return_value = True
            with self.assertRaisesRegex(RuntimeError, "Custom target override"):
                self.module.apply("travel")
            run.assert_not_called()

    def test_travel_masks_before_logind_change_then_unmasks_and_verifies(self):
        calls = []
        with patch.object(self.module, "validate_mask_paths"), patch.object(self.module, "run", side_effect=lambda *a: calls.append(a)), patch.object(self.module, "write_lid_config", side_effect=lambda mode: calls.append(("lid", mode))), patch.object(self.module.subprocess, "run") as process:
            process.return_value.stdout = "loaded\n"
            self.module.apply("travel")
        self.assertEqual(calls[0][1], "mask")
        self.assertEqual(calls[1], ("lid", "travel"))
        self.assertEqual(calls[-1][1], "unmask")

    def test_failed_unmask_verification_reblocks_sleep(self):
        calls = []
        with patch.object(self.module, "validate_mask_paths"), patch.object(self.module, "write_lid_config"), patch.object(self.module, "run", side_effect=lambda *a: calls.append(a)), patch.object(self.module.subprocess, "run") as process:
            process.return_value.stdout = "masked\n"
            with self.assertRaises(RuntimeError):
                self.module.apply("travel")
        self.assertEqual(calls[-1][1], "mask")


@unittest.skipUnless(os.name == "posix", "Installer uses Linux account metadata")
class InstallerSafety(unittest.TestCase):
    def setUp(self):
        self.module = load("install-homehub-power-policy")
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_new_file_has_complete_content_and_requested_permissions(self):
        path = self.root / "helper"
        self.module.install_new(path, b"reviewed-content", 0o755)
        self.assertEqual(path.read_bytes(), b"reviewed-content")
        self.assertEqual(path.stat().st_mode & 0o777, 0o755)
        self.assertEqual(list(self.root.iterdir()), [path])

    def test_existing_file_is_never_replaced(self):
        path = self.root / "helper"
        path.write_bytes(b"preserve-me")
        with self.assertRaises(FileExistsError):
            self.module.install_new(path, b"new-content", 0o755)
        self.assertEqual(path.read_bytes(), b"preserve-me")
        self.assertEqual(list(self.root.iterdir()), [path])

    def test_publication_failure_leaves_no_partial_destination(self):
        path = self.root / "helper"
        with patch.object(self.module.os, "link", side_effect=OSError("publication failed")):
            with self.assertRaisesRegex(OSError, "publication failed"):
                self.module.install_new(path, b"reviewed-content", 0o755)
        self.assertEqual(list(self.root.iterdir()), [])


@unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "Disposable bash harness requires Linux")
class HostLifecycle(unittest.TestCase):
    def run_cycle(self, scenario):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            state = home / ".local/state/home-hub"
            state.mkdir(parents=True)
            (state / "travel-mode").write_text("travel-start\n")
            binaries = root / "bin"
            binaries.mkdir()
            repo = root / "repo"
            (repo / "scripts").mkdir(parents=True)
            events = root / "events"
            helper = root / "installed-helper"
            helper.write_text("placeholder")
            helper.chmod(0o755)
            fake_power = repo / "scripts/homehub-desktop-power.py"
            fake_power.write_text(
                "import os,sys\nfrom pathlib import Path\n"
                "mode=sys.argv[1]\n"
                "state=Path(os.environ['TEST_HOME'])/'.local/state/home-hub'\n"
                "with open(os.environ['EVENT_LOG'],'a') as f:\n"
                " f.write('power '+mode+' returning='+str((state/'returning-home').exists())+'\\n')\n"
                "if mode=='home' and os.environ['SCENARIO']=='power_fail': sys.exit(1)\n")
            stubs = {
                "systemctl": '#!/bin/bash\nprintf "systemctl %s\\n" "$*" >> "$EVENT_LOG"\nif [[ "$*" == *list-unit-files* ]]; then for arg in "$@"; do if [[ "$arg" == *.service || "$arg" == *.timer ]]; then printf "%s enabled\\n" "$arg"; break; fi; done; fi\n',
                "curl": '#!/bin/bash\nprintf "curl %s\\n" "$*" >> "$EVENT_LOG"\nif [[ "$*" == *"/health"* ]]; then [[ "$SCENARIO" == backend_fail ]] && exit 22; exit 0; fi\nprintf 200\n',
                "sleep": "#!/bin/bash\nexit 0\n",
                "notify-send": "#!/bin/bash\nexit 0\n",
                "pkill": "#!/bin/bash\nexit 0\n",
            }
            for name, content in stubs.items():
                path = binaries / name
                path.write_text(content)
                path.chmod(0o755)
            source = (SCRIPTS / "homehub-hostctl.sh").read_text()
            # All paths, service calls and termination commands are confined to
            # disposable fixtures; no real HOME or installed root helper is used.
            source = source.replace('$HOME', '$TEST_HOME').replace(
                'POWER_HELPER="/usr/local/libexec/homehub-system-power"',
                'POWER_HELPER=' + json.dumps(str(helper)))
            script = root / "hostctl.sh"
            script.write_text(source)
            env = dict(os.environ, TEST_HOME=str(home), HOME_HUB_ROOT=str(repo),
                       EVENT_LOG=str(events), SCENARIO=scenario, TMPDIR=str(root),
                       PATH=str(binaries) + ":/usr/bin:/bin", DISPLAY="", WAYLAND_DISPLAY="")
            result = subprocess.run(["bash", str(script), "home", "--force"],
                                    env=env, capture_output=True, text=True, timeout=10)
            return result, events.read_text(), (state / "travel-mode").exists(), (state / "returning-home").exists()

    def test_home_power_precedes_backend_and_cleanup_follows_activation(self):
        result, events, travel, returning = self.run_cycle("success")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(travel or returning)
        self.assertLess(events.index("power home returning=True"), events.index("enable --now home-hub.service"))
        self.assertLess(events.index("/activate"), events.index("power finish-home returning=False"))

    def test_power_failure_rolls_back_without_booting_backend(self):
        result, events, travel, returning = self.run_cycle("power_fail")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(travel)
        self.assertFalse(returning)
        self.assertNotIn("enable --now home-hub.service", events)
        self.assertIn("power travel returning=False", events)

    def test_backend_failure_restores_travel_power_after_stopping_core(self):
        result, events, travel, returning = self.run_cycle("backend_fail")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(travel)
        self.assertFalse(returning)
        self.assertLess(events.index("disable --now home-hub.service"), events.index("power travel returning=False"))


if __name__ == "__main__":
    unittest.main()
