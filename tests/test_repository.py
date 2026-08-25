import json
import os
import re
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import fcntl


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ID = "io.github.fabiopauli.windowcontrols"
PROGRAMS = (
    "omarchy-minimize",
    "omarchy-restore-minimized",
    "omarchy-minimized-list",
)


class RepositoryContractTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / "manifest.json").read_text())
        self.bar_widget = (ROOT / "BarWidget.qml").read_text()
        self.panel = (ROOT / "MinimizedPanel.qml").read_text()
        self.readme = (ROOT / "README.md").read_text()

    def test_manifest_identity_is_reverse_dns(self):
        self.assertEqual(self.manifest["id"], PLUGIN_ID)
        self.assertRegex(self.manifest["id"], r"^[a-z0-9]+(?:\.[a-z0-9]+)+$")
        self.assertFalse(self.manifest["id"].startswith("omarchy."))

    def test_manifest_declares_existing_bar_widget(self):
        self.assertEqual(self.manifest["schemaVersion"], 1)
        self.assertEqual(self.manifest["kinds"], ["bar-widget"])
        entry_point = self.manifest["entryPoints"]["barWidget"]
        self.assertTrue((ROOT / entry_point).is_file())

    def test_manifest_boolean_schema_matches_defaults(self):
        expected = {
            "showList": True,
            "showMinimize": True,
            "showClose": True,
            "hideListWhenEmpty": False,
            "showCount": True,
        }
        metadata = self.manifest["barWidget"]
        self.assertEqual(metadata["defaults"], expected)
        schema = {item["key"]: item for item in metadata["schema"]}
        self.assertEqual(set(schema), set(expected))
        for key, default in expected.items():
            with self.subTest(key=key):
                self.assertEqual(schema[key]["type"], "boolean")
                self.assertEqual(schema[key]["defaultValue"], default)

    def test_publication_files_exist(self):
        for filename in (
            "README.md",
            "LICENSE",
            "SECURITY.md",
            "manifest.json",
            "BarWidget.qml",
            "MinimizedPanel.qml",
        ):
            with self.subTest(filename=filename):
                self.assertTrue((ROOT / filename).is_file())

    def test_repository_contains_no_symlinks(self):
        symlinks = [path for path in ROOT.rglob("*") if path.is_symlink()]
        self.assertEqual(symlinks, [])

    def test_scripts_are_packaged_and_executable(self):
        for program in (*PROGRAMS, "windowcontrols_state.py"):
            path = ROOT / "bin" / program
            with self.subTest(program=program):
                self.assertTrue(path.is_file())
                self.assertTrue(path.stat().st_mode & stat.S_IXUSR)

    def test_widget_uses_mdi_glyphs_in_required_order(self):
        glyphs = ["󰍜", "󰖰", "󰖭"]
        positions = [self.bar_widget.index(f'text: "{glyph}"') for glyph in glyphs]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn('text: "_"', self.bar_widget)
        self.assertNotIn('text: "X"', self.bar_widget)
        self.assertIn("root.vertical ? Grid.TopToBottom : Grid.LeftToRight", self.bar_widget)

    def test_count_uses_its_own_body_font_button(self):
        count_button = re.search(
            r"WidgetButton \{.*?text: String\(root\.count\).*?fontSize: Style\.font\.body",
            self.bar_widget,
            re.DOTALL,
        )
        self.assertIsNotNone(count_button)

    def test_panel_host_contract_is_present(self):
        self.assertIn("readonly property bool opened:", self.bar_widget)
        self.assertIn("function open()", self.bar_widget)
        self.assertIn("function close()", self.bar_widget)
        self.assertIn("readonly property var barIdentity: hostWidget || root", self.panel)
        self.assertIn("owner: root.barIdentity", self.panel)
        self.assertIn("switchPanelFrom(root.barIdentity, direction)", self.panel)

    def test_list_parsing_and_refresh_contract(self):
        self.assertIn("JSON.parse", self.bar_widget)
        self.assertNotIn("Util.parseModuleJson(", self.bar_widget)
        self.assertIn("interval: 120", self.bar_widget)
        for event in ("movewindow", "openwindow", "closewindow", "windowtitle"):
            self.assertIn(event, self.bar_widget)
        self.assertIn("interval: 30000", self.bar_widget)

    def test_empty_workspace_visibility_uses_workspace_toplevels(self):
        self.assertIn("readonly property bool workspaceEmpty:", self.bar_widget)
        self.assertIn("Hyprland.focusedWorkspace", self.bar_widget)
        self.assertIn("ws.toplevels.values.length === 0", self.bar_widget)
        self.assertNotIn("ToplevelManager.activeToplevel", self.bar_widget)
        self.assertIn(
            "showList && (count > 0 || (!hideListWhenEmpty && !workspaceEmpty))",
            self.bar_widget,
        )
        self.assertIn(
            "visible: opened || listVisible || ((showMinimize || showClose) && !workspaceEmpty)",
            self.bar_widget,
        )
        self.assertIn(
            "visible: root.showMinimize && !root.workspaceEmpty",
            self.bar_widget,
        )
        self.assertIn(
            "visible: root.showClose && !root.workspaceEmpty",
            self.bar_widget,
        )

    def test_lua_close_dispatchers_are_used(self):
        self.assertNotIn("killactive", self.bar_widget)
        self.assertIn("hl.dispatch(hl.dsp.window.close())", self.bar_widget)
        self.assertIn('hl.dsp.window.close({ window = \\"address:', self.bar_widget)
        self.assertIn("function validAddress(address)", self.bar_widget)

    def test_untrusted_window_metadata_is_plain_text(self):
        for match in re.finditer(r"Text \{", self.panel):
            closing_region = self.panel[match.start() : match.start() + 700]
            self.assertIn("textFormat: Text.PlainText", closing_region)

    def test_widget_invokes_only_bundled_scripts(self):
        expected_paths = {
            "minimizeScript": "bin/omarchy-minimize",
            "listScript": "bin/omarchy-minimized-list",
            "restoreScript": "bin/omarchy-restore-minimized",
        }
        for property_name, relative_path in expected_paths.items():
            with self.subTest(program=relative_path):
                self.assertIn(
                    f'{property_name}: localPath(Qt.resolvedUrl("{relative_path}"))',
                    self.bar_widget,
                )

        self.assertIn("command: [root.listScript]", self.bar_widget)
        self.assertIn("Util.shellQuote(root.restoreScript)", self.bar_widget)
        self.assertIn("Util.shellQuote(root.minimizeScript)", self.bar_widget)
        self.assertNotIn('command: ["omarchy-minimized-list"]', self.bar_widget)
        self.assertNotIn('root.bar.run("omarchy-restore-minimized ', self.bar_widget)
        self.assertNotIn('root.bar.run("omarchy-minimize")', self.bar_widget)

    def test_readme_documents_install_settings_and_convention(self):
        for key in self.manifest["barWidget"]["defaults"]:
            self.assertIn(f"`{key}`", self.readme)
        self.assertIn(PLUGIN_ID, self.readme)
        self.assertIn("special:minimized", self.readme)
        self.assertIn("~/.cache/hypr-minimized-stack", self.readme)
        self.assertIn("SUPER + M", self.readme)
        self.assertIn("SUPER + CTRL + M", self.readme)
        self.assertIn("### Empty workspaces", self.readme)
        self.assertIn("omarchy restart shell", self.readme)
        self.assertIn("Function not found", self.readme)


class MinimizedListTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.fake_bin = self.home / "fake-bin"
        self.fake_bin.mkdir()
        self.clients_file = self.home / "clients.json"
        self.clients_file.write_text(
            json.dumps(
                [
                    {
                        "address": "0xaaa",
                        "class": "Editor",
                        "title": "Notes",
                        "pid": 101,
                        "initialClass": "editor",
                        "initialTitle": "Notes",
                        "workspace": {"id": -99, "name": "special:minimized"},
                    },
                    {
                        "address": "0xbbb",
                        "class": "Browser",
                        "title": "Docs",
                        "pid": 202,
                        "initialClass": "browser",
                        "initialTitle": "Docs",
                        "workspace": {"id": -99, "name": "special:minimized"},
                    },
                    {
                        "address": "0xccc",
                        "class": "Terminal",
                        "title": "Shell",
                        "pid": 303,
                        "initialClass": "terminal",
                        "initialTitle": "Shell",
                        "workspace": {"id": 2, "name": "2"},
                    },
                ]
            )
        )
        fake_hyprctl = self.fake_bin / "hyprctl"
        fake_hyprctl.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' \"$*\" >>\"$WINDOWCONTROLS_TEST_LOG\"\n"
            "if [ \"$1 $2\" = \"clients -j\" ]; then\n"
            "  if [ -n \"${WINDOWCONTROLS_TEST_BLOCK_CLIENTS:-}\" ]; then\n"
            "    : >\"$WINDOWCONTROLS_TEST_CLIENTS_READY\"\n"
            "    while [ ! -e \"$WINDOWCONTROLS_TEST_CLIENTS_RELEASE\" ]; do sleep 0.01; done\n"
            "  fi\n"
            "  exec /bin/cat \"$WINDOWCONTROLS_TEST_CLIENTS\"\n"
            "fi\n"
            "if [ \"$1 $2\" = \"activeworkspace -j\" ]; then\n"
            "  printf '%s\\n' '{\"id\":7}'\n"
            "  exit 0\n"
            "fi\n"
            "if [ \"$1\" = \"eval\" ]; then\n"
            "  if [ -n \"${WINDOWCONTROLS_TEST_MINIMIZE_RESULT:-}\" ]; then\n"
            "    /bin/cp \"$WINDOWCONTROLS_TEST_MINIMIZE_RESULT\" \"$WINDOWCONTROLS_TEST_CLIENTS\"\n"
            "  fi\n"
            "  exit 0\n"
            "fi\n"
            "exit 64\n"
        )
        fake_hyprctl.chmod(0o755)

        cache = self.home / ".cache"
        cache.mkdir()
        self.stack = cache / "hypr-minimized-stack"
        self.original_stack = "0xdead 9\n0xaaa 1\n0xbbb 2\n0xaaa 4\n"
        self.stack.write_text(self.original_stack)

        self.environment = os.environ.copy()
        self.environment["HOME"] = str(self.home)
        self.environment["PATH"] = f"{self.fake_bin}:{self.environment['PATH']}"
        self.environment["WINDOWCONTROLS_TEST_CLIENTS"] = str(self.clients_file)
        self.hyprctl_log = self.home / "hyprctl.log"
        self.environment["WINDOWCONTROLS_TEST_LOG"] = str(self.hyprctl_log)
        self.command = ROOT / "bin" / "omarchy-minimized-list"
        self.restore_command = ROOT / "bin" / "omarchy-restore-minimized"
        self.minimize_command = ROOT / "bin" / "omarchy-minimize"
        self.state_helper = ROOT / "bin" / "windowcontrols_state.py"

    def run_list(self, *arguments):
        return subprocess.run(
            [self.command, *arguments],
            env=self.environment,
            text=True,
            capture_output=True,
            check=True,
        )

    def test_dry_run_uses_real_workspace_membership_without_writing(self):
        result = self.run_list("--dry-run")
        payload = json.loads(result.stdout)
        self.assertEqual([item["address"] for item in payload], ["0xaaa", "0xbbb"])
        self.assertEqual(self.stack.read_text(), self.original_stack)
        self.assertNotIn("0xdead", result.stdout)
        self.assertNotIn("0xccc", result.stdout)
        self.assertEqual(result.stdout.count("\n"), 1)

    def test_normal_run_prunes_stale_and_duplicate_entries_under_lock(self):
        result = self.run_list()
        payload = json.loads(result.stdout)
        self.assertEqual([item["address"] for item in payload], ["0xaaa", "0xbbb"])
        self.assertEqual(self.stack.read_text(), "0xbbb 2\n0xaaa 4\n")

    def test_symlinked_state_is_rejected_without_touching_its_target(self):
        victim = self.home / "victim"
        victim.write_text("do not change\n")
        self.stack.unlink()
        self.stack.symlink_to(victim)

        result = subprocess.run(
            [self.command],
            env=self.environment,
            text=True,
            capture_output=True,
            timeout=2,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("safely open state file", result.stderr)
        self.assertEqual(victim.read_text(), "do not change\n")

    def test_oversized_state_is_rejected_before_it_is_read(self):
        self.stack.write_bytes(b"x" * (64 * 1024 + 1))

        result = subprocess.run(
            [self.command],
            env=self.environment,
            text=True,
            capture_output=True,
            timeout=2,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exceeds the 65536-byte safety limit", result.stderr)

    def test_fifo_state_is_rejected_without_blocking(self):
        self.stack.unlink()
        os.mkfifo(self.stack)

        result = subprocess.run(
            [self.command],
            env=self.environment,
            text=True,
            capture_output=True,
            timeout=2,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not a regular file", result.stderr)

    def test_locked_state_fails_fast(self):
        with self.stack.open("r+") as state:
            fcntl.flock(state, fcntl.LOCK_EX | fcntl.LOCK_NB)
            started = time.monotonic()
            result = subprocess.run(
                [self.state_helper, "take", "0xaaa"],
                env=self.environment,
                text=True,
                capture_output=True,
                timeout=2,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("state file is busy", result.stderr)
        self.assertLess(time.monotonic() - started, 1)

    def test_list_holds_state_lock_while_capturing_compositor_snapshot(self):
        ready = self.home / "clients-ready"
        release = self.home / "clients-release"
        environment = self.environment.copy()
        environment["WINDOWCONTROLS_TEST_BLOCK_CLIENTS"] = "1"
        environment["WINDOWCONTROLS_TEST_CLIENTS_READY"] = str(ready)
        environment["WINDOWCONTROLS_TEST_CLIENTS_RELEASE"] = str(release)
        listing = subprocess.Popen(
            [self.command],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            deadline = time.monotonic() + 2
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(ready.exists())
            competing = subprocess.run(
                [self.state_helper, "take", "0xaaa"],
                env=self.environment,
                text=True,
                capture_output=True,
                timeout=2,
            )
            self.assertNotEqual(competing.returncode, 0)
            self.assertIn("state file is busy", competing.stderr)
        finally:
            release.touch()
            listing.communicate(timeout=2)

        self.assertEqual(listing.returncode, 0)

    def test_compositor_cardinality_limit_fails_closed(self):
        clients = [
            {
                "address": f"0x{index + 1:x}",
                "workspace": {"id": index + 1, "name": str(index + 1)},
            }
            for index in range(257)
        ]
        self.clients_file.write_text(json.dumps(clients))

        result = subprocess.run(
            [self.command],
            env=self.environment,
            text=True,
            capture_output=True,
            timeout=2,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("256-window limit", result.stderr)

    def test_compositor_byte_limit_fails_closed(self):
        self.clients_file.write_bytes(b" " * (1024 * 1024 + 2))

        result = subprocess.run(
            [self.command],
            env=self.environment,
            text=True,
            capture_output=True,
            timeout=2,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("response exceeds the 1048576-byte safety limit", result.stderr)

    def test_window_metadata_is_bounded_at_the_json_producer(self):
        clients = json.loads(self.clients_file.read_text())
        clients[0]["title"] = "x" * 4096
        self.clients_file.write_text(json.dumps(clients))

        result = self.run_list("--dry-run")
        payload = json.loads(result.stdout)

        self.assertEqual(len(payload[0]["title"]), 512)
        self.assertLessEqual(len(result.stdout.encode()), 1024 * 1024)

    def test_list_recovers_origin_from_compositor_tag(self):
        clients = json.loads(self.clients_file.read_text())
        clients[0]["tags"] = ["omarchy_windowcontrols_origin_-23"]
        self.clients_file.write_text(json.dumps([clients[0]]))
        self.stack.write_text("")

        result = self.run_list()

        self.assertEqual(json.loads(result.stdout)[0]["address"], "0xaaa")
        self.assertEqual(self.stack.read_text(), "0xaaa -23\n")

    def test_invalid_stored_workspace_never_reaches_hyprctl_eval(self):
        self.stack.write_text('0xaaa 1\";os.execute(\"touch /tmp/pwned\")\n')

        result = subprocess.run(
            [self.restore_command, "0xaaa"],
            env=self.environment,
            text=True,
            capture_output=True,
            timeout=2,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid record", result.stderr)
        self.assertNotIn("eval", self.hyprctl_log.read_text())

    def test_valid_stored_workspace_is_restored_and_removed(self):
        result = subprocess.run(
            [self.restore_command, "0xaaa"],
            env=self.environment,
            text=True,
            capture_output=True,
            check=True,
            timeout=2,
        )

        self.assertEqual(result.stdout, "")
        self.assertEqual(self.stack.read_text(), "0xbbb 2\n")
        hyprctl_calls = self.hyprctl_log.read_text()
        self.assertIn("eval", hyprctl_calls)
        self.assertIn("-omarchy_windowcontrols_origin_4", hyprctl_calls)
        self.assertIn('workspace = "4"', hyprctl_calls)

    def test_minimize_records_a_negative_workspace_before_moving(self):
        minimized_result = self.home / "minimized-result.json"
        clients = json.loads(self.clients_file.read_text())
        clients.append(
            {
                "address": "0xddd",
                "class": "Test",
                "title": "Test",
                "pid": 404,
                "initialClass": "test",
                "initialTitle": "Test",
                "tags": ["omarchy_windowcontrols_origin_-123"],
                "workspace": {"id": -99, "name": "special:minimized"},
            }
        )
        minimized_result.write_text(json.dumps(clients))
        environment = self.environment.copy()
        environment["WINDOWCONTROLS_TEST_MINIMIZE_RESULT"] = str(minimized_result)
        result = subprocess.run(
            [self.minimize_command],
            env=environment,
            text=True,
            capture_output=True,
            check=True,
            timeout=2,
        )

        self.assertEqual(result.stdout, "")
        self.assertEqual(
            self.stack.read_text(),
            "0xdead 9\n0xaaa 1\n0xbbb 2\n0xaaa 4\n0xddd -123\n",
        )
        hyprctl_calls = self.hyprctl_log.read_text()
        self.assertLess(
            hyprctl_calls.index("omarchy_windowcontrols_origin_"),
            hyprctl_calls.index("special:minimized"),
        )

    def test_dry_run_lists_manually_parked_window_without_cache_directory(self):
        fresh_home = self.home / "fresh-home"
        fresh_home.mkdir()
        clients = json.loads(self.clients_file.read_text())
        self.clients_file.write_text(json.dumps([clients[0]]))
        environment = self.environment.copy()
        environment["HOME"] = str(fresh_home)

        result = subprocess.run(
            [self.command, "--dry-run"],
            env=environment,
            text=True,
            capture_output=True,
            check=True,
            timeout=2,
        )

        self.assertEqual(json.loads(result.stdout)[0]["address"], "0xaaa")
        self.assertFalse((fresh_home / ".cache").exists())

    def test_duplicate_minimized_addresses_fail_before_output_amplification(self):
        duplicate = json.loads(self.clients_file.read_text())[0]
        self.clients_file.write_text(json.dumps([duplicate] * 256))

        result = subprocess.run(
            [self.command, "--dry-run"],
            env=self.environment,
            text=True,
            capture_output=True,
            timeout=2,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("duplicate minimized address", result.stderr)

    def test_minimize_rejects_symlink_state_without_moving(self):
        victim = self.home / "minimize-victim"
        victim.write_text("do not append\n")
        self.stack.unlink()
        self.stack.symlink_to(victim)

        result = subprocess.run(
            [self.minimize_command],
            env=self.environment,
            text=True,
            capture_output=True,
            timeout=2,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(victim.read_text(), "do not append\n")
        self.assertFalse(self.hyprctl_log.exists())

if __name__ == "__main__":
    unittest.main()
