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
managed_block_present=0
take_over_super_m=0
take_over_super_ctrl_m=0
super_m_bindings=""
super_ctrl_m_bindings=""

usage() {
  printf 'Usage: %s [--dry-run]\n' "${0##*/}"
}

bindings_block() {
  printf '%s\n' "$BEGIN_MARKER"
  if (( take_over_super_m || take_over_super_ctrl_m )); then
    printf '%s\n' '-- The installer reported the bindings overridden below before adding this block.'
  fi
  if (( take_over_super_m )); then
    printf '%s\n' 'hl.unbind("SUPER + M")'
  fi
  if (( take_over_super_ctrl_m )); then
    printf '%s\n' 'hl.unbind("SUPER + CTRL + M")'
  fi
  cat <<'LUA'
local windowcontrols_bin = os.getenv("HOME") .. "/.local/bin"
o.bind("SUPER + M", "Minimize window", windowcontrols_bin .. "/omarchy-minimize")
o.bind("SUPER + CTRL + M", "Restore last minimized window", windowcontrols_bin .. "/omarchy-restore-minimized")
-- END io.github.fabiopauli.windowcontrols
LUA
}

binding_lines() {
  local shortcut="$1"
  awk -v shortcut="$shortcut" '
    /^[[:space:]]*--/ { next }
    $0 ~ /(^|[^[:alnum:]_])(o|hl)\.bind[[:space:]]*\(/ && index($0, "\"" shortcut "\"") {
      print NR ": " $0
    }
  ' "$BINDINGS_FILE"
}

warn_takeover() {
  local shortcut="$1"
  local matches="$2"
  local verb="will"
  (( dry_run )) && verb="would"
  printf 'WARNING: Window Controls %s take over %s from the existing binding(s):\n' \
    "$verb" "$shortcut" >&2
  while IFS= read -r binding; do
    printf '  %s\n' "$binding" >&2
  done <<<"$matches"
}

while (( $# > 0 )); do
  case "$1" in
    --dry-run) dry_run=1 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
  shift
done

for required in awk cut grep hyprctl install jq mktemp sort tac; do
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

if [[ -f $BINDINGS_FILE ]]; then
  begin_count=$(grep -Fxc -- "$BEGIN_MARKER" "$BINDINGS_FILE" || true)
  end_count=$(grep -Fxc -- "$END_MARKER" "$BINDINGS_FILE" || true)
  if [[ $begin_count != "$end_count" || $begin_count -gt 1 ]]; then
    printf '%s: malformed or duplicate Window Controls managed block in %s\n' \
      "${0##*/}" "$BINDINGS_FILE" >&2
    exit 1
  fi
  if (( begin_count == 1 )); then
    managed_block_present=1
  else
    super_m_bindings=$(binding_lines "SUPER + M")
    super_ctrl_m_bindings=$(binding_lines "SUPER + CTRL + M")
    [[ -z $super_m_bindings ]] || take_over_super_m=1
    [[ -z $super_ctrl_m_bindings ]] || take_over_super_ctrl_m=1
  fi
fi

if (( take_over_super_m )); then
  warn_takeover "SUPER + M" "$super_m_bindings"
fi
if (( take_over_super_ctrl_m )); then
  warn_takeover "SUPER + CTRL + M" "$super_ctrl_m_bindings"
fi

if (( dry_run )); then
  printf 'Would install commands into %s\n' "$BIN_DIR"
  if (( managed_block_present )); then
    printf 'Would leave the existing managed keybinding block in %s unchanged.\n' "$BINDINGS_FILE"
  else
    printf 'Would update bindings in %s with:\n\n' "$BINDINGS_FILE"
    bindings_block
  fi
  exit 0
fi

mkdir -p -- "$BIN_DIR" "$(dirname -- "$BINDINGS_FILE")"
for program in omarchy-minimize omarchy-restore-minimized omarchy-minimized-list; do
  install -m 0755 -- "$PLUGIN_DIR/bin/$program" "$BIN_DIR/$program"
done

if (( managed_block_present )); then
  printf 'Installed Window Controls commands; existing managed keybindings left unchanged.\n'
  exit 0
fi

bindings_tmp=$(mktemp "$(dirname -- "$BINDINGS_FILE")/.bindings.lua.windowcontrols.XXXXXX")
trap 'rm -f -- "${bindings_tmp:-}"' EXIT
if [[ -s $BINDINGS_FILE ]]; then
  awk '{ print }' "$BINDINGS_FILE" >"$bindings_tmp"
  printf '\n' >>"$bindings_tmp"
else
  : >"$bindings_tmp"
fi
bindings_block >>"$bindings_tmp"

if [[ -f $BINDINGS_FILE ]]; then
  backup_file=$(mktemp "${BINDINGS_FILE}.bak.XXXXXX")
  cp -p -- "$BINDINGS_FILE" "$backup_file"
  printf 'Backed up bindings to %s\n' "$backup_file"
fi
mv -f -- "$bindings_tmp" "$BINDINGS_FILE"
trap - EXIT

printf 'Installed Window Controls commands and keybindings.\n'

if [[ -n ${HYPRLAND_INSTANCE_SIGNATURE:-} ]]; then
  hyprctl reload >/dev/null
  hyprctl configerrors
else
  printf 'Hyprland is not available in this shell; reload it after login to activate the bindings.\n'
fi
