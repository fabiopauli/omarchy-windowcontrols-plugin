# Window Controls for Omarchy

A Quattro bar widget that supplies the controls Hyprland deliberately leaves to clients: a minimized-window list, minimize, and close. It works on horizontal and vertical bars and uses the bar's MDI icon glyphs throughout.

The controls appear in this order:

1. A three-line menu button with the minimized-window count. Its dropdown lists every window currently parked on `special:minimized`; click a row to restore it, or use the row's close button to close it without restoring.
2. Minimize the focused window.
3. Close the focused window.

The dropdown supports Up/Down or `J`/`K`, Enter/Space to restore, `X` to close without restoring, and Escape to close the panel. Minimize and close automatically disappear when the focused workspace has no windows.

## Requirements

- Omarchy Quattro with its Lua-based Hyprland configuration
- `hyprctl`
- `jq`
- the standard `awk`, `cut`, `sort`, and `tac` command-line tools

## Install

```bash
omarchy plugin add https://github.com/fabiopauli/omarchy-windowcontrols-plugin.git --enable
```

## Optional keyboard shortcuts

The bar controls work fully without keyboard shortcuts. To add `SUPER + M` for minimize and `SUPER + CTRL + M` for restoring the most recently minimized window, paste this block into `~/.config/hypr/bindings.lua`:

```lua
-- BEGIN io.github.fabiopauli.windowcontrols optional keybindings
local windowcontrols_bin = os.getenv("HOME") .. "/.config/omarchy/plugins/io.github.fabiopauli.windowcontrols/bin"
hl.unbind("SUPER + M")
hl.unbind("SUPER + CTRL + M")
o.bind("SUPER + M", "Minimize window", windowcontrols_bin .. "/omarchy-minimize")
o.bind("SUPER + CTRL + M", "Restore last minimized window", windowcontrols_bin .. "/omarchy-restore-minimized")
-- END io.github.fabiopauli.windowcontrols optional keybindings
```

The `hl.unbind` lines deliberately replace existing assignments for those shortcuts. Choose different keys instead if you want to preserve existing bindings. Reload and validate Hyprland after editing:

```bash
hyprctl reload
hyprctl configerrors
```

## shell.json

`omarchy plugin add --enable` writes the bar entry for you. The equivalent entry, shown with every setting at its default, is:

```json
{
  "bar": {
    "layout": {
      "center": [
        {
          "id": "io.github.fabiopauli.windowcontrols",
          "showList": true,
          "showMinimize": true,
          "showClose": true,
          "hideListWhenEmpty": false,
          "showCount": true
        }
      ]
    }
  }
}
```

Merge the entry into your existing layout rather than replacing the rest of `shell.json`. A third-party plugin is loaded only while its ID is referenced there.

## Settings

All settings are boolean values on the widget's bar-layout entry.

| Setting | Default | Effect |
| --- | --- | --- |
| `showList` | `true` | Show the minimized-window list button when it has a useful target. |
| `showMinimize` | `true` | Show minimize while the focused workspace has a window. |
| `showClose` | `true` | Show close while the focused workspace has a window. |
| `hideListWhenEmpty` | `false` | Hide the list button when no windows are minimized; an empty focused workspace always hides an empty list. |
| `showCount` | `true` | Show a small minimized-window count next to the menu glyph. |

### Empty workspaces

With the default settings, visibility follows the useful actions available:

| Focused workspace | Minimized count | Bar shows |
| --- | --- | --- |
| Has a window | 0 | List, minimize, close |
| Empty | Greater than 0 | List and count only |
| Empty | 0 | Nothing |

The list deliberately remains reachable from an empty workspace while windows are stashed. `showList`, `showMinimize`, `showClose`, and `showCount` can still hide their respective controls. `hideListWhenEmpty` hides an empty list on an occupied workspace; on an empty workspace the empty list is omitted regardless, because it has no action to offer. The widget host stays alive while its dropdown is open so closing the last minimized window cannot orphan the panel.

## How minimize works

Hyprland has no native minimized state. This plugin uses one explicit convention:

- `omarchy-minimize` appends `<address> <workspace-id>` to `~/.cache/hypr-minimized-stack`, then moves the focused window to `special:minimized` without following it.
- `omarchy-minimized-list` asks Hyprland which windows are actually on `special:minimized`. The stack contributes only newest-first ordering and each window's origin workspace. Stale stack entries are pruned, so a closed or manually moved window cannot linger in the dropdown.
- `omarchy-restore-minimized [address]` checks that authoritative list, returns the selected window to its recorded workspace (or the active workspace when no origin is known), and focuses it. With no address it restores the newest minimized window.

The bar buttons and optional keyboard bindings execute the scripts bundled in the plugin's `bin/` directory. `omarchy-minimized-list --dry-run` prints the real list without pruning the stack file.

The close controls use Omarchy's Lua dispatchers. The focused close action evaluates `hl.dispatch(hl.dsp.window.close())`; a dropdown row targets `hl.dsp.window.close({ window = "address:0x..." })` directly.

## Update

```bash
omarchy plugin update io.github.fabiopauli.windowcontrols --yes
```

## Remove

Remove the bar plugin with Omarchy:

```bash
omarchy plugin remove io.github.fabiopauli.windowcontrols --yes
```

Omarchy removes the plugin checkout and its `shell.json` entry. If you added the optional keyboard shortcuts, also delete the block between the `BEGIN` and `END` comments above from `~/.config/hypr/bindings.lua`, then run `hyprctl reload`. The optional runtime history file can be removed with `rm -f ~/.cache/hypr-minimized-stack`.

## Security and privacy

Omarchy plugins run unsandboxed. This plugin executes its three bundled scripts plus `hyprctl eval` for close actions. It does not use the network, elevate privileges, or inspect window contents. Window titles and classes returned by Hyprland are rendered as plain text. Window addresses are accepted only in Hyprland's hexadecimal `0x...` form before they are used in commands.

Installation writes nothing outside the plugin directory. At runtime, the scripts write only the state file `~/.cache/hypr-minimized-stack`.

Review [`BarWidget.qml`](BarWidget.qml), [`MinimizedPanel.qml`](MinimizedPanel.qml), and [`bin/`](bin/) before installation.

## Development

```bash
python -m json.tool manifest.json >/dev/null
shellcheck bin/*
python -m unittest discover -s tests -v
omarchy plugin validate .
bin/omarchy-minimized-list --dry-run
```

The final command queries the running compositor but does not alter the minimized stack.

### Troubleshooting plugin reloads

Saving a plugin file can produce `Local plugin changed, reloading` without replacing the existing widget instance. If behavior remains stale after a file change, run:

```bash
omarchy restart shell
```

IPC handlers added during a hot reload may also fail to re-register and report `Function not found`. Restart the shell before testing a new IPC method. For reload diagnostics, add temporary `console.log` calls and inspect the active Quickshell log under `$XDG_RUNTIME_DIR/quickshell/by-pid/<pid>/log.log`.

## License

[MIT](LICENSE)
