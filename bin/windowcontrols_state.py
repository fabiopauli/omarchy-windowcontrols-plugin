#!/usr/bin/env python3
"""Safely maintain the bounded window-origin state used by this plugin."""

from __future__ import annotations

import fcntl
import json
import os
import re
import selectors
import stat
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator


STATE_NAME = "hypr-minimized-stack"
MAX_STATE_BYTES = 64 * 1024
MAX_RECORDS = 512
MAX_CLIENTS = 256
MAX_CLIENT_BYTES = 1024 * 1024
MAX_EVAL_BYTES = 4096
MAX_OUTPUT_BYTES = 1024 * 1024
MAX_METADATA_CHARS = 512
ADDRESS_RE = re.compile(r"0x[0-9A-Fa-f]{1,16}")
WORKSPACE_RE = re.compile(r"-?(?:0|[1-9][0-9]{0,9})")
ORIGIN_TAG_PREFIX = "omarchy_windowcontrols_origin_"
ORIGIN_TAG_RE = re.compile(
    rf"{re.escape(ORIGIN_TAG_PREFIX)}(-?(?:0|[1-9][0-9]{{0,9}}))"
)
WORKSPACE_MIN = -(2**31)
WORKSPACE_MAX = 2**31 - 1


class StateError(Exception):
    """The state path or its contents do not satisfy the safety contract."""


@dataclass(frozen=True)
class Record:
    address: str
    workspace: str


def valid_address(value: str) -> bool:
    return ADDRESS_RE.fullmatch(value) is not None


def valid_workspace(value: str) -> bool:
    if WORKSPACE_RE.fullmatch(value) is None:
        return False
    number = int(value, 10)
    return WORKSPACE_MIN <= number <= WORKSPACE_MAX


def validate_directory(fd: int, label: str) -> None:
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode):
        raise StateError(f"{label} is not a directory")
    if info.st_uid != os.geteuid():
        raise StateError(f"{label} is not owned by the current user")
    if info.st_mode & 0o022:
        raise StateError(f"{label} is writable by another user")


def cache_directory(create: bool) -> int | None:
    home = os.environ.get("HOME")
    if not home or not os.path.isabs(home):
        raise StateError("HOME must be an absolute path")

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    home_fd = os.open(home, directory_flags)
    try:
        validate_directory(home_fd, "HOME")
        if create:
            try:
                os.mkdir(".cache", 0o700, dir_fd=home_fd)
            except FileExistsError:
                pass

        try:
            cache_fd = os.open(
                ".cache", directory_flags | os.O_NOFOLLOW, dir_fd=home_fd
            )
        except FileNotFoundError:
            if not create:
                return None
            raise StateError("HOME/.cache does not exist") from None
    finally:
        os.close(home_fd)

    try:
        validate_directory(cache_fd, "HOME/.cache")
    except Exception:
        os.close(cache_fd)
        raise
    return cache_fd


def validate_state_fd(fd: int) -> os.stat_result:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
        raise StateError("state path is not a regular file")
    if info.st_uid != os.geteuid():
        raise StateError("state file is not owned by the current user")
    if info.st_nlink != 1:
        raise StateError("state file must have exactly one link")
    if info.st_size > MAX_STATE_BYTES:
        raise StateError(
            f"state file exceeds the {MAX_STATE_BYTES}-byte safety limit"
        )
    return info


@contextmanager
def open_state(*, write: bool, create: bool) -> Iterator[int | None]:
    cache_fd = cache_directory(create=create)
    if cache_fd is None:
        yield None
        return
    state_fd: int | None = None
    try:
        flags = (os.O_RDWR if write else os.O_RDONLY) | os.O_CLOEXEC
        flags |= os.O_NOFOLLOW | os.O_NONBLOCK
        if create:
            flags |= os.O_CREAT
        try:
            state_fd = os.open(STATE_NAME, flags, 0o600, dir_fd=cache_fd)
        except FileNotFoundError:
            if create:
                raise
            yield None
            return
        except OSError as error:
            raise StateError(f"could not safely open state file: {error.strerror}") from None

        lock = fcntl.LOCK_EX if write else fcntl.LOCK_SH
        try:
            fcntl.flock(state_fd, lock | fcntl.LOCK_NB)
        except BlockingIOError:
            raise StateError("state file is busy") from None

        validate_state_fd(state_fd)
        if write:
            os.fchmod(state_fd, 0o600)
        yield state_fd
    finally:
        if state_fd is not None:
            os.close(state_fd)
        os.close(cache_fd)


def run_hyprctl(arguments: list[str], *, limit: int, timeout: float) -> bytes:
    process = subprocess.Popen(
        ["hyprctl", *arguments],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert process.stdout is not None
    output = bytearray()
    deadline = time.monotonic() + timeout
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise StateError("hyprctl timed out")
            events = selector.select(remaining)
            if not events:
                if process.poll() is not None:
                    break
                continue
            chunk = os.read(process.stdout.fileno(), min(65536, limit + 1 - len(output)))
            if not chunk:
                break
            output.extend(chunk)
            if len(output) > limit:
                raise StateError(f"hyprctl response exceeds the {limit}-byte safety limit")

        remaining = max(0.0, deadline - time.monotonic())
        if process.wait(timeout=remaining) != 0:
            raise StateError("hyprctl command failed")
    except (OSError, subprocess.TimeoutExpired, StateError):
        process.kill()
        process.wait()
        raise
    finally:
        selector.close()
        process.stdout.close()
    return bytes(output)


def client_snapshot() -> list[dict[str, object]]:
    raw = run_hyprctl(["clients", "-j"], limit=MAX_CLIENT_BYTES, timeout=3)
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise StateError("compositor client response is not valid JSON") from None
    if not isinstance(payload, list) or len(payload) > MAX_CLIENTS:
        raise StateError(
            f"compositor client data exceeds the {MAX_CLIENTS}-window limit"
        )

    clients: list[dict[str, object]] = []
    minimized_addresses: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            raise StateError("compositor client response contains a non-object")
        workspace = item.get("workspace")
        minimized = (
            isinstance(workspace, dict)
            and workspace.get("name") == "special:minimized"
        )
        if minimized:
            address = item.get("address")
            if not isinstance(address, str) or not valid_address(address):
                raise StateError("minimized client has an invalid address")
            if address in minimized_addresses:
                raise StateError("compositor returned a duplicate minimized address")
            minimized_addresses.add(address)
        clients.append(item)
    return clients


def origin_from_tags(client: dict[str, object]) -> str | None:
    tags = client.get("tags", [])
    if not isinstance(tags, list):
        raise StateError("compositor client tags are invalid")
    origins: set[str] = set()
    for tag in tags:
        if not isinstance(tag, str):
            raise StateError("compositor client tag is not a string")
        match = ORIGIN_TAG_RE.fullmatch(tag)
        if match:
            workspace = match.group(1)
            if not valid_workspace(workspace):
                raise StateError("origin tag has an invalid workspace id")
            origins.add(workspace)
    if len(origins) > 1:
        raise StateError("minimized client has conflicting origin tags")
    return next(iter(origins), None)


def merge_tagged_origins(
    records: list[Record], clients: list[dict[str, object]]
) -> list[Record]:
    positions = {record.address: index for index, record in enumerate(records)}
    merged = list(records)
    for client in clients:
        workspace = client.get("workspace")
        if not (
            isinstance(workspace, dict)
            and workspace.get("name") == "special:minimized"
        ):
            continue
        address = client["address"]
        assert isinstance(address, str)
        origin = origin_from_tags(client)
        if origin is None:
            continue
        if address in positions:
            merged[positions[address]] = Record(address, origin)
        else:
            positions[address] = len(merged)
            merged.append(Record(address, origin))
    return merged


def metadata(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:MAX_METADATA_CHARS]
    if isinstance(value, bool):
        return ("true" if value else "false")[:MAX_METADATA_CHARS]
    if isinstance(value, (int, float)):
        return str(value)[:MAX_METADATA_CHARS]
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))[
        :MAX_METADATA_CHARS
    ]


def list_windows(*, dry_run: bool) -> None:
    with open_state(write=not dry_run, create=not dry_run) as fd:
        clients = client_snapshot()
        records = merge_tagged_origins(read_records(fd), clients)
        live = {
            client["address"]
            for client in clients
            if isinstance(client.get("workspace"), dict)
            and client["workspace"].get("name") == "special:minimized"
        }
        newest: dict[str, tuple[int, Record]] = {}
        for index, record in enumerate(records):
            if record.address in live:
                newest[record.address] = (index, record)
        kept = [item[1] for item in sorted(newest.values())]
        if not dry_run:
            assert fd is not None
            write_records(fd, kept)

        by_address = {
            client["address"]: client
            for client in clients
            if client.get("address") in live
        }
        ordered = [record.address for record in reversed(kept)]
        ordered.extend(address for address in by_address if address not in ordered)
        result = []
        for address in ordered:
            client = by_address[address]
            pid = client.get("pid")
            if isinstance(pid, bool) or not isinstance(pid, (int, float)):
                pid = None
            result.append(
                {
                    "address": address,
                    "class": metadata(client.get("class")),
                    "title": metadata(client.get("title")),
                    "pid": pid,
                    "initialClass": metadata(client.get("initialClass")),
                    "initialTitle": metadata(client.get("initialTitle")),
                }
            )

        output = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()
        if len(output) > MAX_OUTPUT_BYTES:
            raise StateError(
                f"minimized-window JSON exceeds the {MAX_OUTPUT_BYTES}-byte safety limit"
            )
        sys.stdout.buffer.write(output + b"\n")


def minimize() -> None:
    lua = f'''
local w = hl.get_active_window()
if w then
  local prefix = "{ORIGIN_TAG_PREFIX}"
  local old_origins = {{}}
  for _, tag in ipairs(w.tags) do
    if string.sub(tag, 1, #prefix) == prefix then
      table.insert(old_origins, tag)
    end
  end
  for _, tag in ipairs(old_origins) do
    hl.dispatch(hl.dsp.window.tag({{ tag = "-" .. tag, window = w }}))
  end
  local origin = prefix .. tostring(w.workspace.id)
  hl.dispatch(hl.dsp.window.tag({{ tag = "+" .. origin, window = w }}))
  hl.dispatch(hl.dsp.window.move({{ window = w, workspace = "special:minimized", follow = false }}))
end
'''
    with open_state(write=True, create=True) as fd:
        assert fd is not None
        records = read_records(fd)
        run_hyprctl(["eval", lua], limit=MAX_EVAL_BYTES, timeout=2)
        clients = client_snapshot()
        merged = merge_tagged_origins(records, clients)
        write_records(fd, merged)


def read_records(fd: int | None) -> list[Record]:
    if fd is None:
        return []

    info = validate_state_fd(fd)
    os.lseek(fd, 0, os.SEEK_SET)
    remaining = info.st_size
    chunks: list[bytes] = []
    while remaining:
        chunk = os.read(fd, min(remaining, 8192))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    if remaining or os.fstat(fd).st_size != info.st_size:
        raise StateError("state file changed while it was being read")

    try:
        text = b"".join(chunks).decode("ascii")
    except UnicodeDecodeError:
        raise StateError("state file contains non-ASCII data") from None

    records: list[Record] = []
    for line in text.splitlines():
        fields = line.split(" ")
        if (
            len(fields) != 2
            or not valid_address(fields[0])
            or not valid_workspace(fields[1])
        ):
            raise StateError("state file contains an invalid record")
        records.append(Record(*fields))
        if len(records) > MAX_RECORDS:
            raise StateError(
                f"state file exceeds the {MAX_RECORDS}-record safety limit"
            )
    return records


def write_records(fd: int, records: list[Record]) -> None:
    validate_state_fd(fd)
    if len(records) > MAX_RECORDS:
        raise StateError(f"state would exceed the {MAX_RECORDS}-record safety limit")
    payload = "".join(
        f"{record.address} {record.workspace}\n" for record in records
    ).encode("ascii")
    if len(payload) > MAX_STATE_BYTES:
        raise StateError(f"state would exceed the {MAX_STATE_BYTES}-byte safety limit")

    os.lseek(fd, 0, os.SEEK_SET)
    written = 0
    while written < len(payload):
        written += os.write(fd, payload[written:])
    os.ftruncate(fd, len(payload))
    os.fsync(fd)


def take(address: str) -> None:
    if not valid_address(address):
        raise StateError("invalid window address")
    with open_state(write=True, create=True) as fd:
        assert fd is not None
        records = read_records(fd)
        workspace = ""
        kept: list[Record] = []
        for record in records:
            if record.address == address:
                workspace = record.workspace
            else:
                kept.append(record)
        write_records(fd, kept)
        if workspace:
            print(workspace)


def usage() -> None:
    print(
        "Usage: windowcontrols_state.py minimize\n"
        "       windowcontrols_state.py list [--dry-run]\n"
        "       windowcontrols_state.py take 0xADDRESS",
        file=sys.stderr,
    )


def main(arguments: list[str]) -> int:
    try:
        if arguments == ["minimize"]:
            minimize()
        elif arguments in (["list"], ["list", "--dry-run"]):
            list_windows(dry_run=len(arguments) == 2)
        elif len(arguments) == 2 and arguments[0] == "take":
            take(arguments[1])
        else:
            usage()
            return 2
    except (OSError, StateError) as error:
        print(f"windowcontrols state: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
