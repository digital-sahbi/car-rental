"""Compile ``.po`` catalogues into ``.mo`` without GNU gettext.

Django reads compiled ``.mo`` files at runtime, but ``compilemessages`` shells
out to ``msgfmt``, which is not installed here. The ``.mo`` format is small and
stable, so this script builds it directly — no extra dependency.

It also cross-checks the catalogue against :mod:`tools.extract_messages`, so an
incomplete translation is reported rather than silently shipped.

Usage::

    python tools/compile_messages.py            # compile every locale
    python tools/compile_messages.py --check    # report only, write nothing
"""
from __future__ import annotations

import argparse
import re
import struct
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from extract_messages import collect  # noqa: E402  (path set up above)

LOCALE_DIR = PROJECT_ROOT / "locale"
QUOTED = re.compile(r'^"(?P<body>.*)"$')

UNESCAPE = {"\\n": "\n", "\\t": "\t", "\\r": "\r", '\\"': '"', "\\\\": "\\"}


def unescape(text: str) -> str:
    """Turn a .po quoted body into the real string."""
    result = []
    index = 0
    while index < len(text):
        pair = text[index : index + 2]
        if pair in UNESCAPE:
            result.append(UNESCAPE[pair])
            index += 2
        else:
            result.append(text[index])
            index += 1
    return "".join(result)


def parse_po(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Return ``(entries, metadata)`` from a .po file.

    ``entries`` maps msgid → msgstr (the header, whose msgid is empty, is
    returned separately as ``metadata``).
    """
    entries: dict[str, str] = {}
    metadata: dict[str, str] = {}

    msgid: str | None = None
    msgstr: str | None = None
    target: list[str] | None = None

    def flush() -> None:
        nonlocal msgid, msgstr
        if msgid is None or msgstr is None:
            return
        if msgid == "":
            for line in msgstr.splitlines():
                if ": " in line:
                    key, _, value = line.partition(": ")
                    metadata[key.strip()] = value.strip()
        elif msgstr:
            entries[msgid] = msgstr
        msgid = msgstr = None

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()

        if not line or line.startswith("#"):
            if not line:
                flush()
            continue

        if line.startswith("msgid "):
            flush()
            msgid = unescape(QUOTED.match(line[6:].strip()).group("body"))
            target = None
        elif line.startswith("msgstr "):
            msgstr = unescape(QUOTED.match(line[7:].strip()).group("body"))
            target = None
        elif (match := QUOTED.match(line)) and target is not None:
            target.append(unescape(match.group("body")))
        elif match := QUOTED.match(line):
            # Continuation of whichever field came last.
            if msgstr is not None and msgid is not None:
                msgstr += unescape(match.group("body"))
            elif msgid is not None:
                msgid += unescape(match.group("body"))

    flush()
    return entries, metadata


def build_mo(entries: dict[str, str], metadata: dict[str, str]) -> bytes:
    """Serialise a catalogue to the binary ``.mo`` format.

    Layout: 28-byte header, msgid table, msgstr table, then the string blobs.
    The metadata block is stored under the empty msgid, which must sort first.
    """
    header = "\n".join(f"{key}: {value}" for key, value in metadata.items()) + "\n"
    catalogue = {"": header, **entries}
    keys = sorted(catalogue, key=lambda key: key.encode("utf-8"))

    id_table: list[tuple[int, int]] = []
    str_table: list[tuple[int, int]] = []
    ids = bytearray()
    strings = bytearray()

    for key in keys:
        key_bytes = key.encode("utf-8")
        value_bytes = catalogue[key].encode("utf-8")

        id_table.append((len(key_bytes), len(ids)))
        ids += key_bytes + b"\0"

        str_table.append((len(value_bytes), len(strings)))
        strings += value_bytes + b"\0"

    count = len(keys)
    id_table_offset = 28
    str_table_offset = id_table_offset + count * 8
    blob_offset = str_table_offset + count * 8

    output = bytearray()
    output += struct.pack("<7I", 0x950412DE, 0, count, id_table_offset, str_table_offset, 0, 0)
    for length, offset in id_table:
        output += struct.pack("<2I", length, blob_offset + offset)
    for length, offset in str_table:
        output += struct.pack("<2I", length, blob_offset + len(ids) + offset)
    output += ids
    output += strings
    return bytes(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report without writing")
    args = parser.parse_args()

    expected = set(collect())
    status = 0

    for po_path in sorted(LOCALE_DIR.glob("*/LC_MESSAGES/django.po")):
        language = po_path.parent.parent.name
        entries, metadata = parse_po(po_path)

        missing = sorted(expected - set(entries))
        empty = sorted(msgid for msgid, msgstr in entries.items() if not msgstr)

        print(f"[{language}] {len(entries)}/{len(expected)} strings translated")
        if missing:
            status = 1
            print(f"  ! {len(missing)} msgid(s) missing, e.g. {missing[:3]}")
        if empty:
            status = 1
            print(f"  ! {len(empty)} untranslated msgstr, e.g. {empty[:3]}")

        if not args.check and not missing:
            mo_path = po_path.with_suffix(".mo")
            mo_path.write_bytes(build_mo(entries, metadata))
            print(f"  -> {mo_path.relative_to(PROJECT_ROOT)} ({mo_path.stat().st_size} bytes)")
        elif not args.check:
            print("  ! not compiled: the catalogue is incomplete")

    return status


if __name__ == "__main__":
    raise SystemExit(main())
