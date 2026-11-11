"""Read the React Server Component "flight" data which Next.js pages embed in their HTML.

A Next.js app router page carries its data as `<script>self.__next_f.push([1,"<fragment>"])</script>` calls.
Concatenating the string fragments yields text which contains plain JSON objects, so a source can find a payload by the
key in front of it. Used by every source whose site is a Next.js app (Digiphile, Humble Bundle).
"""

from __future__ import annotations

import json
import re
from typing import Any


FLIGHT_PUSH_MARKER = "self.__next_f.push("


class FlightParseError(ValueError):
    """The embedded flight data was malformed."""

# end class FlightParseError


def flight_text(html: str) -> str:
    """Concatenate the string fragments of every `self.__next_f.push([<n>, "<fragment>"])` call."""
    decoder = json.JSONDecoder()
    fragments: list[str] = []
    position = html.find(FLIGHT_PUSH_MARKER)
    while position != -1:
        start = position + len(FLIGHT_PUSH_MARKER)
        try:
            chunk, end = decoder.raw_decode(html, start)
        except json.JSONDecodeError as error:
            raise FlightParseError(f"malformed flight chunk at offset {start}: {error}") from error
        # end try
        if isinstance(chunk, list) and len(chunk) > 1 and isinstance(chunk[1], str):
            fragments.append(chunk[1])
        # end if
        position = html.find(FLIGHT_PUSH_MARKER, end)
    # end while
    return "".join(fragments)
# end def flight_text


def decode_after_key(text: str, key: str, expected: type) -> list[Any]:
    """Every JSON value of type `expected` which directly follows a `"<key>":` in the flight text."""
    decoder = json.JSONDecoder()
    marker = f'"{key}":'
    values: list[Any] = []
    position = text.find(marker)
    while position != -1:
        start = position + len(marker)
        position = text.find(marker, start)
        if start >= len(text) or text[start] != ("{" if expected is dict else "["):
            continue
        # end if
        try:
            value, _end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            continue
        # end try
        if isinstance(value, expected):
            values.append(value)
        # end if
    # end while
    return values
# end def decode_after_key


# A flight row is `<hex id>:<payload>\n`. The payload is JSON, or `T<hex byte length>,<text>` for a long text row, whose
# text may itself contain newlines and is cut by its UTF-8 byte length rather than by the line break.
ROW_ID_PATTERN = re.compile(r"([0-9a-fA-F]+):")
TEXT_HEADER_PATTERN = re.compile(r"T([0-9a-fA-F]+),")
# A back-reference to another row, optionally into it: `$7a` is the whole row 7a, `$e:0:props:children` walks into row e.
REFERENCE_PATTERN = re.compile(r"\$([0-9a-fA-F]+)((?::[A-Za-z0-9_-]+)*)")


def parse_rows(text: str) -> dict[str, Any]:
    """Split flight text into its rows, keyed by row id: JSON rows decoded, `T` rows as plain strings.

    Rows which are neither JSON nor text (`I[...]` module imports are JSON arrays and fine) are skipped.
    """
    data = text.encode("utf-8")
    decoder = json.JSONDecoder()
    rows: dict[str, Any] = {}
    position = 0
    while position < len(data):
        match = ROW_ID_PATTERN.match(text_at(data, position, 16))
        if match is None:
            # Unknown junk: resynchronise at the next line.
            newline = data.find(b"\n", position)
            position = len(data) if newline == -1 else newline + 1
            continue
        # end if
        row_id = match.group(1)
        position += len(match.group(0))
        header = TEXT_HEADER_PATTERN.match(text_at(data, position, 16))
        if header is not None:
            start = position + len(header.group(0))
            end = start + int(header.group(1), 16)
            rows[row_id] = data[start:end].decode("utf-8")
            position = end + 1 if data[end : end + 1] == b"\n" else end
            continue
        # end if
        newline = data.find(b"\n", position)
        line_end = len(data) if newline == -1 else newline
        try:
            rows[row_id], _end = decoder.raw_decode(data[position:line_end].decode("utf-8"))
        except json.JSONDecodeError:
            pass
        # end try
        position = line_end + 1
    # end while
    return rows
# end def parse_rows


def text_at(data: bytes, position: int, length: int) -> str:
    """A short ASCII-safe window of `data`, for matching row headers without decoding the whole remainder."""
    return data[position : position + length].decode("ascii", errors="ignore")
# end def text_at


def resolve(value: Any, rows: dict[str, Any], depth: int = 0) -> Any:
    """Replace every back-reference string inside `value` by what it points to (recursively).

    `$<id>` gives the row, `$<id>:a:b:0` walks into it. A reference which does not resolve, or `$undefined`, is kept as
    given (`$undefined` becomes `None`), so a changed page shows up as an odd value rather than as a crash here.
    """
    if depth > 8:
        return value
    # end if
    if isinstance(value, str):
        if value == "$undefined":
            return None
        # end if
        match = REFERENCE_PATTERN.fullmatch(value)
        if match is None or match.group(1) not in rows:
            return value
        # end if
        target: Any = rows[match.group(1)]
        for step in [part for part in match.group(2).split(":") if part]:
            if isinstance(target, list) and step.isdigit() and int(step) < len(target):
                target = target[int(step)]
            elif isinstance(target, list) and step == "props" and len(target) > 3 and target[0] == "$":
                # A React element is serialised as `["$", type, key, props]`, but references name its props as `props`.
                target = target[3]
            elif isinstance(target, dict) and step in target:
                target = target[step]
            else:
                return value
            # end if
        # end for
        return resolve(target, rows, depth + 1)
    # end if
    if isinstance(value, list):
        return [resolve(item, rows, depth) for item in value]
    # end if
    if isinstance(value, dict):
        return {key: resolve(item, rows, depth) for key, item in value.items()}
    # end if
    return value
# end def resolve


def find_key(value: Any, key: str) -> Any:
    """The first value stored under `key` anywhere inside nested dicts/lists, depth first, or None."""
    if isinstance(value, dict):
        if key in value:
            return value[key]
        # end if
        for child in value.values():
            found = find_key(child, key)
            if found is not None:
                return found
            # end if
        # end for
    # end if
    if isinstance(value, list):
        for child in value:
            found = find_key(child, key)
            if found is not None:
                return found
            # end if
        # end for
    # end if
    return None
# end def find_key
