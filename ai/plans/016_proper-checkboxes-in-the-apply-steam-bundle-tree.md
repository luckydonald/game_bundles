# Proper checkboxes in the `apply steam` bundle tree

## Context

`_BundleTree` (`src/game_collections/apply/tui.py`) renders `[x]`/`[ ]`/`[-]` glyphs as plain text
prefixed onto source/bundle node labels (`_source_label`, `_bundle_label`). Checking/unchecking
only happens through the `enter` key, which is bound to a custom `action_toggle_selection` that
calls `self._on_toggle(node.data)`.

Mouse clicks on a tree row do **not** go through that binding. Textual's `Tree._on_click` instead
calls `run_action("select_cursor")`, which posts a `Tree.NodeSelected` message — and because
`Tree.auto_expand` defaults to `True`, the only visible effect of clicking a bundle/source row
today is that it expands/collapses (via `_expand_node_on_select`). There is no handler for
`Tree.NodeSelected` in `ApplyPickerApp`, so the checkbox itself is unreachable by mouse. Clicking
directly on the twisty arrow is unaffected (handled via a separate `meta["toggle"]` click path in
Textual) and must keep working for expand/collapse.

Goal: clicking a source or bundle row toggles its checkbox (same effect as pressing Enter on it),
clicking a link row opens it (same as Enter), and all existing keyboard bindings/behavior are
unchanged. Visually, swap the ASCII `[x]/[ ]/[-]` for real checkbox-style glyphs; it's fine if the
glyph stays inside the same highlighted label text (not worth the complexity of separating it out).

## Changes (`src/game_collections/apply/tui.py`)

1. **Stop `Tree.NodeSelected` from silently expanding rows.** Set `self.auto_expand = False` in
   `_BundleTree.__init__` (right next to the existing `self.show_root = False` /
   `self.guide_depth = 2` lines). Expand/collapse remains fully available via the twisty-arrow
   click (untouched Textual behavior) and the existing `left`/`right`/`+`/`-` bindings.

2. **Wire mouse clicks to the same toggle/open logic as Enter.** Add a handler in `_BundleTree`
   for `Tree.NodeSelected` that mirrors `action_toggle_selection`'s body exactly (same
   `kind in ("source", "bundle")` → `self._on_toggle(...)`, `kind == "link"` → `self._on_open(...)`
   dispatch). Simplest approach: extract the existing body of `action_toggle_selection` into a
   shared `_activate(self, data: _NodeData)` method, call it from `action_toggle_selection`, and
   add:
   ```python
   def on_tree_node_selected(self, event: Tree.NodeSelected[_NodeData]) -> None:
       if event.node.data is not None:
           self._activate(event.node.data)
       # end if
   # end def on_tree_node_selected
   ```
   This keeps the `enter` binding's behavior byte-for-byte identical while making mouse clicks
   (which Textual routes through `NodeSelected`) do the same thing.

3. **Prettier checkbox glyphs.** In `_source_label` and `_bundle_label`, replace the ASCII glyphs:
   - unchecked: `☐`
   - checked: `☑`
   - mixed (source, partially checked): `◪` (or similar half-filled box glyph — pick one that
     renders cleanly in a terminal; verify visually per the terminal used during manual testing)
   Keep the surrounding `escape(...)` calls and label formatting (`f"{glyph} {source} (...)"`,
   etc.) as-is — only the glyph characters change.

## Verification

- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest` — no existing tests should break (there's no
  dedicated TUI test suite currently exercising click behavior; this is a manual/behavioral
  change).
- Manually run `game-collections apply steam` (needs the `tui` extra) in a real terminal:
  - Click directly on a bundle row (not the arrow) → checkbox flips, tree re-renders with new
    glyph and updated source count; row does NOT expand/collapse.
  - Click directly on a source row → all its bundles toggle together, same as Enter.
  - Click the twisty arrow on a bundle/source row → still expands/collapses, checkbox unaffected.
  - Click a "Store: steam" / "Launch on Steam" link leaf → opens the URL, same as Enter.
  - Keyboard nav unchanged: arrows, `+`/`-`, `enter` on source/bundle/link all behave exactly as
    before.
