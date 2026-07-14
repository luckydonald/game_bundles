# Extend arrow-key navigation between the filter row and the tree

## Context

`apply/tui.py`'s picker has a filter row (`#filters`: 4 `Input`s, 2 `Select`s, 1
`Checkbox`, all on one row) above the `_BundleTree`. Today the filter widgets and
the tree are two separate keyboard islands — you can only move between them with
Tab/Shift+Tab or the mouse. The user wants natural arrow-key flow between the two:

- **Up** from the topmost tree row jumps focus into the filter row (first widget).
- **Left/Right** inside a filter widget behaves normally (`Input` moves the text
  cursor, `Select`/`Checkbox` have no native meaning) until you're at a field's
  edge (start/end of text, or always for `Select`/`Checkbox`), at which point it
  moves focus to the previous/next widget in the filter row instead.
- **Down** from any `Input` or `Checkbox` in the filter row moves focus back into
  the tree. `Select`'s Up/Down keep their native meaning (open the dropdown) and
  are untouched; while its dropdown overlay is open, focus is on the overlay
  itself so this doesn't apply anyway.

Confirmed with user: Up-from-tree always focuses the *first* filter widget (no
last-focused tracking), and `Select` Up/Down are left alone.

## Approach

Add a small mixin plus three thin widget subclasses in `tui.py`, and swap the
plain `Input`/`Select`/`Checkbox` constructions in `_mount_picker` for them. Wire
one new binding into the existing `_BundleTree`.

### 1. `_FilterFieldBehavior` mixin (new, in `tui.py`)

```python
class _FilterFieldBehavior:
    """Shared left/right/down navigation for widgets living in the `#filters` row."""

    def _focus_adjacent_filter(self, delta: int) -> None:
        siblings = list(self.screen.query_one("#filters").children)
        index = siblings.index(self)
        target = index + delta
        if 0 <= target < len(siblings):
            siblings[target].focus()
        # end if
    # end def _focus_adjacent_filter

    def action_focus_prev_filter(self) -> None:
        self._focus_adjacent_filter(-1)
    # end def action_focus_prev_filter

    def action_focus_next_filter(self) -> None:
        self._focus_adjacent_filter(1)
    # end def action_focus_next_filter

    def action_focus_tree(self) -> None:
        self.screen.query_one("#rows-tree", Tree).focus()
    # end def action_focus_tree

# end class _FilterFieldBehavior
```

### 2. Three subclasses, each combining the mixin with the stock widget

- `_FilterInput(_FilterFieldBehavior, Input)`: override `action_cursor_left`/
  `action_cursor_right` (the exact action names `Input`'s own bindings already
  point at) to check `self.cursor_position` against `0` / `len(self.value)`; at
  the boundary call `action_focus_prev_filter()`/`action_focus_next_filter()`
  instead of `super().action_cursor_left()`/`super().action_cursor_right()`.
  Add `BINDINGS = [Binding("down", "focus_tree", show=False)]` (Textual merges
  a subclass's `BINDINGS` with the inherited ones, so `Input`'s own left/right/
  home/end/etc. bindings keep working).

- `_FilterSelect(_FilterFieldBehavior, Select)`: `Select` has no native
  left/right meaning, so just bind them directly:
  `BINDINGS = [Binding("left", "focus_prev_filter", show=False), Binding("right", "focus_next_filter", show=False)]`.
  Leave Up/Down alone — they're already bound by `Select` itself to open the
  dropdown (`show_overlay`), and while the overlay is open focus lives on the
  internal `SelectOverlay`, not on this widget, so these bindings simply don't
  fire in that state.

- `_FilterCheckbox(_FilterFieldBehavior, Checkbox)`: `Checkbox`/`ToggleButton`
  has no native left/right/down meaning, so bind all three:
  `BINDINGS = [Binding("left", "focus_prev_filter", show=False), Binding("right", "focus_next_filter", show=False), Binding("down", "focus_tree", show=False)]`.

### 3. Wire into `_mount_picker`

Swap the four `Input(...)` calls for `_FilterInput(...)`, the two `Select(...)`
calls for `_FilterSelect(...)`, and the `Checkbox(...)` call for
`_FilterCheckbox(...)` — same ids/args, just the class changes.

### 4. Tree: Up at the top row escapes to the filters

In `_BundleTree` (`tui.py:88`), add:

```python
def action_cursor_up(self) -> None:
    if self.cursor_line <= 0:
        first_filter = self.screen.query_one("#filters").children[0]
        first_filter.focus()
    else:
        Tree.action_cursor_up(self)
    # end if
# end def action_cursor_up
```

This overrides the inherited `Tree.action_cursor_up` (bound to `"up"` by
`Tree.BINDINGS`); no new binding entry needed since the key is already mapped
to this action name.

## Files touched

- `src/game_collections/apply/tui.py` — add the mixin + 3 subclasses, tree
  override, and swap widget classes in `_mount_picker`.

## Verification

- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest` (no existing tests target the
  TUI directly, but this confirms nothing else broke).
- Manual check with `/run` or `env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections apply steam`:
  - From the tree's topmost row, press Up → focus lands on the "min items" input.
  - In an `Input`, type text, press Left/Right mid-string → cursor moves; at
    start/end → focus hops to the previous/next filter widget.
  - On a `Select` (closed) or the `Checkbox`, press Left/Right → focus hops to
    the neighboring filter widget; press Up/Down on a `Select` → dropdown still
    opens as before.
  - From any `Input` or the `Checkbox`, press Down → focus returns to the tree.
