#!/usr/bin/env bash
# Install the shared window-control commands and idempotently add their
# Hyprland Lua bindings. This deliberately does not edit shell.json; Omarchy's
# plugin enable command owns bar placement and per-widget settings.
set -euo pipefail

PLUGIN_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
BIN_DIR="$HOME/.local/bin"
BINDINGS_FILE="$HOME/.config/hypr/bindings.lua"
BEGIN_MARKER="-- BEGIN io.github.fabiopauli.windowcontrols (managed by install.sh)"
END_MARKER="-- END io.github.fabiopauli.windowcontrols"
dry_run=0

usage() {
  printf 'Usage: %s [--dry-run]\n' "${0##*/}"
}

bindings_block() {
  cat <<'LUA'
-- BEGIN io.github.fabiopauli.windowcontrols (managed by install.sh)
-- These explicit unbinds make the plugin's documented shortcuts authoritative.
hl.unbind("SUPER + M")
hl.unbind("SUPER + CTRL + M")
local windowcontrols_bin = os.getenv("HOME") .. "/.local/bin"
o.bind("SUPER + M", "Minimize window", windowcontrols_bin .. "/omarchy-minimize")
o.bind("SUPER + CTRL + M", "Restore last minimized window", windowcontrols_bin .. "/omarchy-restore-minimized")
-- END io.github.fabiopauli.windowcontrols
LUA
}

while (( $# > 0 )); do
  case "$1" in
    --dry-run) dry_run=1 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
  shift
done

for required in awk cmp cut hyprctl install jq mktemp sort tac; do
  if ! command -v "$required" >/dev/null 2>&1; then
    printf '%s: required command not found: %s\n' "${0##*/}" "$required" >&2
    exit 1
  fi
done

for program in omarchy-minimize omarchy-restore-minimized omarchy-minimized-list; do
  if [[ ! -f $PLUGIN_DIR/bin/$program ]]; then
    printf '%s: missing packaged command: bin/%s\n' "${0##*/}" "$program" >&2
    exit 1
  fi
done

if (( dry_run )); then
  printf 'Would install commands into %s\n' "$BIN_DIR"
  printf 'Would update bindings in %s with:\n\n' "$BINDINGS_FILE"
  bindings_block
  exit 0
fi

mkdir -p -- "$BIN_DIR" "$(dirname -- "$BINDINGS_FILE")"
for program in omarchy-minimize omarchy-restore-minimized omarchy-minimized-list; do
  install -m 0755 -- "$PLUGIN_DIR/bin/$program" "$BIN_DIR/$program"
done

bindings_tmp=$(mktemp "$(dirname -- "$BINDINGS_FILE")/.bindings.lua.windowcontrols.XXXXXX")
trap 'rm -f -- "${bindings_tmp:-}"' EXIT
had_managed_block=0

if [[ -f $BINDINGS_FILE ]]; then
  if grep -Fxq -- "$BEGIN_MARKER" "$BINDINGS_FILE"; then
    had_managed_block=1
  fi
  awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" '
    $0 == begin { managed = 1; next }
    $0 == end { managed = 0; next }
    !managed { print }
  ' "$BINDINGS_FILE" >"$bindings_tmp"
else
  : >"$bindings_tmp"
fi

if grep -Eq 'o\.bind\("SUPER \+ (CTRL \+ )?M"|hl\.bind\("SUPER \+ (CTRL \+ )?M"' "$bindings_tmp"; then
  printf 'Note: an existing SUPER+M or SUPER+CTRL+M binding was found; the managed block unbinds it before installing Window Controls.\n' >&2
fi

if (( ! had_managed_block )) && [[ -s $bindings_tmp ]]; then
  printf '\n' >>"$bindings_tmp"
fi
bindings_block >>"$bindings_tmp"

if [[ ! -f $BINDINGS_FILE ]] || ! cmp -s -- "$bindings_tmp" "$BINDINGS_FILE"; then
  if [[ -f $BINDINGS_FILE ]]; then
    backup_file=$(mktemp "${BINDINGS_FILE}.bak.XXXXXX")
    cp -p -- "$BINDINGS_FILE" "$backup_file"
    printf 'Backed up bindings to %s\n' "$backup_file"
  fi
  mv -f -- "$bindings_tmp" "$BINDINGS_FILE"
  trap - EXIT
else
  rm -f -- "$bindings_tmp"
  trap - EXIT
fi

printf 'Installed Window Controls commands and keybindings.\n'

if [[ -n ${HYPRLAND_INSTANCE_SIGNATURE:-} ]]; then
  hyprctl reload >/dev/null
  hyprctl configerrors
else
  printf 'Hyprland is not available in this shell; reload it after login to activate the bindings.\n'
fi
