import json
import os
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


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
        self.installer = (ROOT / "install.sh").read_text()
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
            "install.sh",
        ):
            with self.subTest(filename=filename):
                self.assertTrue((ROOT / filename).is_file())

    def test_repository_contains_no_symlinks(self):
        symlinks = [path for path in ROOT.rglob("*") if path.is_symlink()]
        self.assertEqual(symlinks, [])

    def test_scripts_are_packaged_and_executable(self):
        for program in PROGRAMS:
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

    def test_lua_close_dispatchers_are_used(self):
        self.assertNotIn("killactive", self.bar_widget)
        self.assertIn("hl.dispatch(hl.dsp.window.close())", self.bar_widget)
        self.assertIn('hl.dsp.window.close({ window = \\"address:', self.bar_widget)
        self.assertIn("function validAddress(address)", self.bar_widget)

    def test_untrusted_window_metadata_is_plain_text(self):
        for match in re.finditer(r"Text \{", self.panel):
            closing_region = self.panel[match.start() : match.start() + 700]
            self.assertIn("textFormat: Text.PlainText", closing_region)

    def test_installer_owns_scripts_and_bindings_but_not_shell_json(self):
        for program in PROGRAMS:
            self.assertIn(program, self.installer)
        self.assertIn('hl.unbind("SUPER + M")', self.installer)
        self.assertIn('hl.unbind("SUPER + CTRL + M")', self.installer)
        self.assertIn('o.bind("SUPER + M"', self.installer)
        self.assertIn('o.bind("SUPER + CTRL + M"', self.installer)
        self.assertNotIn("$HOME/.config/omarchy/shell.json", self.installer)

    def test_readme_documents_install_settings_and_convention(self):
        for key in self.manifest["barWidget"]["defaults"]:
            self.assertIn(f"`{key}`", self.readme)
        self.assertIn(PLUGIN_ID, self.readme)
        self.assertIn("special:minimized", self.readme)
        self.assertIn("~/.cache/hypr-minimized-stack", self.readme)
        self.assertIn("SUPER + M", self.readme)
        self.assertIn("SUPER + CTRL + M", self.readme)


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
            "if [ \"$1 $2\" = \"clients -j\" ]; then\n"
            "  exec /bin/cat \"$WINDOWCONTROLS_TEST_CLIENTS\"\n"
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
        self.command = ROOT / "bin" / "omarchy-minimized-list"

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

    def test_normal_run_atomically_prunes_stale_and_duplicate_entries(self):
        result = self.run_list()
        payload = json.loads(result.stdout)
        self.assertEqual([item["address"] for item in payload], ["0xaaa", "0xbbb"])
        self.assertEqual(self.stack.read_text(), "0xbbb 2\n0xaaa 4\n")


class InstallerTests(unittest.TestCase):
    def test_install_is_idempotent_in_an_isolated_home(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            fake_bin = home / "fake-bin"
            fake_bin.mkdir()
            fake_hyprctl = fake_bin / "hyprctl"
            fake_hyprctl.write_text("#!/bin/sh\nexit 64\n")
            fake_hyprctl.chmod(0o755)

            bindings = home / ".config" / "hypr" / "bindings.lua"
            bindings.parent.mkdir(parents=True)
            bindings.write_text(
                'o.bind("SUPER + M", "Old action", "old-command")\n'
            )

            environment = os.environ.copy()
            environment["HOME"] = str(home)
            environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
            environment.pop("HYPRLAND_INSTANCE_SIGNATURE", None)

            first = subprocess.run(
                [ROOT / "install.sh"],
                env=environment,
                text=True,
                capture_output=True,
                check=True,
            )
            first_content = bindings.read_text()
            first_backups = list(bindings.parent.glob("bindings.lua.bak.*"))

            second = subprocess.run(
                [ROOT / "install.sh"],
                env=environment,
                text=True,
                capture_output=True,
                check=True,
            )

            self.assertIn("existing SUPER+M", first.stderr)
            self.assertIn('hl.unbind("SUPER + M")', first_content)
            self.assertEqual(first_content, bindings.read_text())
            self.assertEqual(len(first_backups), 1)
            self.assertEqual(
                first_backups,
                list(bindings.parent.glob("bindings.lua.bak.*")),
            )
            self.assertNotIn("Backed up bindings", second.stdout)
            for program in PROGRAMS:
                installed = home / ".local" / "bin" / program
                self.assertTrue(installed.is_file())
                self.assertTrue(installed.stat().st_mode & stat.S_IXUSR)


if __name__ == "__main__":
    unittest.main()
