"""Read the React Server Component "flight" data which Next.js pages embed in their HTML.

A Next.js app router page carries its data as `<script>self.__next_f.push([1,"<fragment>"])</script>` calls.
Concatenating the string fragments yields text which contains plain JSON objects, so a source can find a payload by the
key in front of it. Used by every source whose site is a Next.js app (Digiphile, Humble Bundle).
"""

from __future__ import annotations

import json
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
