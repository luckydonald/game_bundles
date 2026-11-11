from __future__ import annotations

import json

import pytest

from game_collections.sources.flight import FlightParseError, flight_text, parse_rows, resolve


def page(*fragments: str) -> str:
    return "".join(f"<script>self.__next_f.push({json.dumps([1, fragment])})</script>" for fragment in fragments)
# end def page


def test_flight_text_joins_the_fragments() -> None:
    assert flight_text(page("a:1\n", "b:2\n")) == "a:1\nb:2\n"
# end def test_flight_text_joins_the_fragments


def test_flight_text_rejects_a_malformed_chunk() -> None:
    with pytest.raises(FlightParseError, match="malformed flight chunk"):
        flight_text("<script>self.__next_f.push(</script>")
    # end with
# end def test_flight_text_rejects_a_malformed_chunk


def test_parse_rows_reads_json_and_byte_counted_text_rows() -> None:
    text = 'e:["$","div",null,{"x":1}]\n6e:T7,ä\nb\nc\n1f:{"y":"$6e"}\n'

    rows = parse_rows(text)

    assert rows["e"] == ["$", "div", None, {"x": 1}]
    # `T7` counts UTF-8 bytes: "ä" is two, plus a newline and "b", a newline and "c" is seven, and contains line breaks.
    assert rows["6e"] == "ä\nb\nc\n"[:7]
    assert rows["1f"] == {"y": "$6e"}
# end def test_parse_rows_reads_json_and_byte_counted_text_rows


def test_resolve_follows_row_and_element_prop_references() -> None:
    rows = parse_rows('e:[["$","div",null,{"children":["$","p",null,{"items":[{"n":1},"$e:0:props:children:props:items:0"]}]}]]\n7:T3,abc\n')

    resolved = resolve({"text": "$7", "again": rows["e"][0][3]["children"][3]["items"], "gone": "$undefined"}, rows)

    assert resolved["text"] == "abc"
    assert resolved["again"] == [{"n": 1}, {"n": 1}]
    assert resolved["gone"] is None
# end def test_resolve_follows_row_and_element_prop_references
