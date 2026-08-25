# Security policy

## Supported versions

Security fixes are applied to the latest commit on `main` and included in the next tagged release.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting for this repository. Do not include secrets, credentials, or private desktop captures in a public issue.

Include the affected plugin version, Omarchy version, reproduction steps, and security impact. Reports will be acknowledged as soon as practical.

## Process and file surface

The widget executes the bundled `bin/omarchy-minimize`, `bin/omarchy-restore-minimized`, and `bin/omarchy-minimized-list` scripts, their bundled Python state helper, plus the documented `hyprctl eval` Lua close dispatchers. It does not make network requests or elevate privileges. Window titles and classes are rendered as plain text, and targeted actions reject addresses outside Hyprland's hexadecimal `0x...` form.

Installation writes nothing outside the plugin directory. At runtime, the scripts write only `~/.cache/hypr-minimized-stack` and add a namespaced origin-workspace tag to each minimized window. A bundled helper owns all access to the file through a no-follow, nonblocking, locked descriptor; it verifies the file is regular, singly linked, owned by the current user, and no larger than 64 KiB before reading or writing. Every file record and origin tag is restricted to a hexadecimal window address and signed 32-bit workspace ID. Origin tagging and the workspace move occur in one compositor evaluation, while compositor snapshots and state pruning occur under the same state lock. The list command derives membership from Hyprland's actual `special:minimized` workspace. Its `--dry-run` mode does not modify the state file.

Compositor JSON is collected with byte and time limits. The list rejects more than 256 clients, truncates each emitted metadata field to 512 characters, and refuses to emit more than 1 MiB of JSON to the long-lived shell process.
