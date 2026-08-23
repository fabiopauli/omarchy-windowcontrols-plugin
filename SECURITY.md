# Security policy

## Supported versions

Security fixes are applied to the latest commit on `main` and included in the next tagged release.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting for this repository. Do not include secrets, credentials, or private desktop captures in a public issue.

Include the affected plugin version, Omarchy version, reproduction steps, and security impact. Reports will be acknowledged as soon as practical.

## Process and file surface

The widget executes `omarchy-minimize`, `omarchy-restore-minimized`, and `omarchy-minimized-list`, plus the documented `hyprctl eval` Lua close dispatchers. It does not make network requests or elevate privileges. Window titles and classes are rendered as plain text, and targeted actions reject addresses outside Hyprland's hexadecimal `0x...` form.

The installer writes three executables under `~/.local/bin` and an explicitly marked block under `~/.config/hypr/bindings.lua`. It backs up an existing bindings file before replacement. Runtime commands write only `~/.cache/hypr-minimized-stack`; the list command derives membership from Hyprland's actual `special:minimized` workspace and atomically prunes stale ordering records. Its `--dry-run` mode does not modify that file.
