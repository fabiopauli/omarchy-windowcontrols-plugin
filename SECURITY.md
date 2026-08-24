# Security policy

## Supported versions

Security fixes are applied to the latest commit on `main` and included in the next tagged release.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting for this repository. Do not include secrets, credentials, or private desktop captures in a public issue.

Include the affected plugin version, Omarchy version, reproduction steps, and security impact. Reports will be acknowledged as soon as practical.

## Process and file surface

The widget executes the bundled `bin/omarchy-minimize`, `bin/omarchy-restore-minimized`, and `bin/omarchy-minimized-list` scripts, plus the documented `hyprctl eval` Lua close dispatchers. It does not make network requests or elevate privileges. Window titles and classes are rendered as plain text, and targeted actions reject addresses outside Hyprland's hexadecimal `0x...` form.

Installation writes nothing outside the plugin directory. At runtime, the scripts write only `~/.cache/hypr-minimized-stack`; the list command derives membership from Hyprland's actual `special:minimized` workspace and atomically prunes stale ordering records. Its `--dry-run` mode does not modify that file.
