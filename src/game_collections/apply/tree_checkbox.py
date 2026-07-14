"""Checkbox-style glyph rendering and click detection for Tree labels."""

from __future__ import annotations

from typing import Literal

from rich.style import Style
from rich.text import Text

CheckState = Literal["checked", "unchecked", "mixed"]

_META_KEY = "checkbox"

_GLYPHS: dict[CheckState, str] = {
    "unchecked": "[ ]",
    "checked": "[x]",
    "mixed": "[-]",
}


def render_checkbox_prefix(state: CheckState, base_style: Style) -> Text:
    """Build the checkbox glyph as its own ``Text`` span, styled/metaed independently of the label.

    Using ``base_style`` (never a cursor/hover-highlighted style) keeps the glyph out of the
    row's selection highlight. The attached meta is what `is_checkbox_click` looks for.
    """
    return Text(f"{_GLYPHS[state]} ", style=base_style + Style.from_meta({_META_KEY: True}))
# end def render_checkbox_prefix


def is_checkbox_click(meta: dict[str, object]) -> bool:
    """Whether a Tree click's ``event.style.meta`` landed on a checkbox glyph."""
    return bool(meta.get(_META_KEY, False))
# end def is_checkbox_click
