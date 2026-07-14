# Proper checkboxes in the `apply steam` bundle tree

## Context

`_BundleTree` (`src/game_collections/apply/tui.py`) renders `[x]`/`[ ]`/`[-]` glyphs as plain text
*prefixed onto* source/bundle node labels (`_source_label`, `_bundle_label`). The glyph is just
part of the label string, so it's rendered with whatever style the rest of the label gets
(including cursor/selection highlight), and there's no way to click *just* the checkbox — Textual's
`Tree._on_click` only distinguishes "clicked the expand arrow" (`meta["toggle"]`) from "clicked
anywhere else on the row" (selects the cursor line, and because `Tree.auto_expand` defaults to
`True`, also silently expands/collapses). Checking/unchecking today only happens via the `enter`
key (`_BundleTree.action_toggle_selection` → `self._on_toggle(node.data)`).

### How Textual resolves per-cell clicks (relevant prior art)

Textual's own expand arrow already proves per-glyph click targeting works: `Tree.render_label`
prepends the icon (`▶ `/`▼ `) with a style carrying `Style.from_meta({"toggle": True})`
(`TOGGLE_STYLE`, in `_tree.py`). `Tree._on_click` reads `event.style.meta` — the meta of the exact
cell clicked, not just "which line" — and branches on `meta.get("toggle")`. We can do the same
thing for a checkbox glyph: give it its own `{"checkbox": True}` meta in `render_label`, and check
for it first in an overridden `_on_click`, falling back to `super()._on_click(event)` for
everything else. That leaves the rest of the row's click behavior (cursor move, arrow-click
expand/collapse, auto-expand-on-click) completely untouched, exactly as it works today.

This also solves the "not part of the highlighted text" ask for free: `render_label` receives both
`base_style` (no highlight) and `style` (includes cursor/hover highlight). Textual's own toggle arrow
is built with `base_style`, not `style` — we do the same for the checkbox glyph, so it never gets
the cursor/selection background.

### What Textual's own `Checkbox`/`ToggleButton` widgets look like (answering "what checkbox
stylings exist in the UI lib")

They aren't usable directly inside `Tree` (a `Tree` only renders `rich.text.Text` labels, not
mounted widgets), but for reference: `ToggleButton` (`textual/widgets/_toggle_button.py`) renders
`▐X▌` — `BUTTON_LEFT`/`BUTTON_RIGHT` are the block characters `▐`/`▌`, `BUTTON_INNER` is always the
literal `"X"`, and checked-vs-unchecked is conveyed purely through CSS background color
(`toggle--button` component style + `-on`/`-off` pseudo-classes), not a different glyph.
`RadioButton` subclasses it with the same mechanism. None of that is meaningful outside a real
widget's own CSS-styled render, so for a `Tree` label we render our own Unicode glyphs instead:
- unchecked: `☐` (U+2610 BALLOT BOX)
- checked: `☑` (U+2611 BALLOT BOX WITH CHECK)
- mixed (source row, some but not all bundles checked): `⊟` (U+229F SQUARED MINUS)

## New module: `src/game_collections/apply/tree_checkbox.py`

Textual dispatches `render_label`/`_on_click` by name on the `Tree` subclass itself, so those two
method *overrides* have to live on `_BundleTree` in `tui.py` — there's no way around that. But the
checkbox-specific logic itself (glyph-per-state mapping, the click meta-key contract) is a distinct,
reusable concern, so it gets its own module with plain public names rather than being tucked in as
private constants on `_BundleTree`:

```python
"""Checkbox-style glyph rendering and click detection for Tree labels."""

from typing import Literal

from rich.style import Style
from rich.text import Text

CheckState = Literal["checked", "unchecked", "mixed"]

_META_KEY = "checkbox"

_GLYPHS: dict[CheckState, str] = {
    "unchecked": "☐",
    "checked": "☑",
    "mixed": "⊟",
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
```

## Changes (`src/game_collections/apply/tui.py`)

1. **Add `check_state` to `_NodeData`**: `check_state: Literal["checked", "unchecked", "mixed"] | None = None`.
   `None` means "no checkbox for this row" (game/link nodes keep exactly their current behavior).

2. **Compute `check_state` where the tree is built**, replacing the glyph-embedding logic currently
   in `_source_label`/`_bundle_label`. In `_rebuild_tree`:
   - source node: `"unchecked"` if `checked_count == 0`, `"checked"` if `checked_count == total`,
     else `"mixed"` (same thresholds as today's glyph choice) — pass as
     `_NodeData(kind="source", source=source, check_state=source_state)`.
   - bundle node: `"checked"` if `bundle.list_id in self._checked` else `"unchecked"`.
   Rename `_source_label`/`_bundle_label` to just build the plain text (source name + counts /
   `_row_label(bundle)`), with no glyph prefix — the glyph moves entirely into rendering (next
   step).

3. **Render the checkbox using the new module**, not as part of the label text. Override in
   `_BundleTree`:
   ```python
   def render_label(self, node: TreeNode[_NodeData], base_style: Style, style: Style) -> Text:
       label = super().render_label(node, base_style, style)
       data = node.data
       if data is None or data.check_state is None:
           return label
       # end if
       return Text.assemble(render_checkbox_prefix(data.check_state, base_style), label)
   # end def render_label
   ```
   (needs `from rich.style import Style` and
   `from game_collections.apply.tree_checkbox import render_checkbox_prefix, is_checkbox_click`
   added to imports). Using `base_style` (not `style`) is what keeps the glyph out of the
   cursor/selection highlight.

4. **Make the checkbox glyph its own click target**, independent of the rest of the row. Override:
   ```python
   async def _on_click(self, event: events.Click) -> None:
       meta = event.style.meta
       if is_checkbox_click(meta) and "line" in meta:
           node = self.get_node_at_line(meta["line"])
           if node is not None and node.data is not None:
               self._on_toggle(node.data)
           # end if
           return
       # end if
       await super()._on_click(event)
   # end def _on_click
   ```
   (needs `from textual import events` added to imports). Everything that isn't a checkbox click —
   clicking elsewhere on a source/bundle/game/link row, clicking the expand arrow — falls through to
   `Tree`'s own `_on_click` unchanged, so navigation (expand/collapse on row click, arrow-click
   expand/collapse) stays exactly "as is". Keyboard bindings (`enter`, `left`/`right`, `+`/`-`) are
   untouched — this only intercepts mouse clicks on the new checkbox glyph.

No changes needed to `action_toggle_selection`, `_toggle`, `_open`, or any keyboard binding.

## Verification

- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest` — should still pass (no dedicated TUI click tests
  exist today; this is a manual/behavioral change).
- Manually run `game-collections apply steam` (needs the `tui` extra) in a real terminal:
  - Click directly on the `☐`/`☑`/`⊟` glyph of a bundle row → toggles just that bundle; row does
    not expand/collapse.
  - Click directly on the glyph of a source row → toggles all its bundles together, same as
    pressing `enter` on it.
  - Click anywhere else on a source/bundle row (not the glyph, not the arrow) → same as today
    (moves cursor, auto-expands/collapses via Textual's default `auto_expand` behavior) — no
    checkbox change.
  - Click the expand arrow → still expands/collapses only, no checkbox change.
  - Confirm the checkbox glyph does not switch to the cursor-highlight background when the row is
    selected, while the rest of the label still does.
  - Keyboard nav unchanged: arrows, `+`/`-`, `enter` on source/bundle/link all behave exactly as
    before.
