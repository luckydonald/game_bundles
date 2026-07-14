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

User feedback: no `_`-prefixed "private" classes/functions for this new code —
put it in its own module instead of piling more names into `tui.py`.

## Approach

New module `src/game_collections/apply/filter_widgets.py` holding a mixin plus
three thin widget subclasses (all public names). `tui.py` imports them and
swaps the plain `Input`/`Select`/`Checkbox` constructions in `_mount_picker`
for them. One new binding is wired into the existing `_BundleTree`.

### 1. `filter_widgets.py` — new module

```python
"""Filter-row widgets that hand off Left/Right/Down navigation to their siblings and the tree."""

from __future__ import annotations

from textual.binding import Binding
from textual.widgets import Checkbox, Input, Select, Tree


class FilterFieldBehavior:
    """Shared left/right/down navigation for widgets living in the `#filters` row."""

    def focus_adjacent_filter(self, delta: int) -> None:
        siblings = list(self.screen.query_one("#filters").children)
        index = siblings.index(self)
        target = index + delta
        if 0 <= target < len(siblings):
            siblings[target].focus()
        # end if
    # end def focus_adjacent_filter

    def action_focus_prev_filter(self) -> None:
        self.focus_adjacent_filter(-1)
    # end def action_focus_prev_filter

    def action_focus_next_filter(self) -> None:
        self.focus_adjacent_filter(1)
    # end def action_focus_next_filter

    def action_focus_tree(self) -> None:
        self.screen.query_one("#rows-tree", Tree).focus()
    # end def action_focus_tree

# end class FilterFieldBehavior


class FilterInput(FilterFieldBehavior, Input):
    """Input that hands Left/Right at the text boundary to the neighboring filter, Down to the tree."""

    BINDINGS = [Binding("down", "focus_tree", show=False)]

    def action_cursor_left(self) -> None:
        if self.cursor_position == 0:
            self.action_focus_prev_filter()
        else:
            super().action_cursor_left()
        # end if
    # end def action_cursor_left

    def action_cursor_right(self) -> None:
        if self.cursor_position == len(self.value):
            self.action_focus_next_filter()
        else:
            super().action_cursor_right()
        # end if
    # end def action_cursor_right

# end class FilterInput


class FilterSelect(FilterFieldBehavior, Select):
    """Select with no native Left/Right meaning, so those always move to the neighboring filter."""

    BINDINGS = [
        Binding("left", "focus_prev_filter", show=False),
        Binding("right", "focus_next_filter", show=False),
    ]

# end class FilterSelect


class FilterCheckbox(FilterFieldBehavior, Checkbox):
    """Checkbox with no native Left/Right/Down meaning, so all three navigate the filter row/tree."""

    BINDINGS = [
        Binding("left", "focus_prev_filter", show=False),
        Binding("right", "focus_next_filter", show=False),
        Binding("down", "focus_tree", show=False),
    ]

# end class FilterCheckbox
```

Notes:
- `FilterInput` overrides `action_cursor_left`/`action_cursor_right` — the exact
  action names `Input`'s own bindings already point at — so its inherited
  home/end/word-move/etc. bindings keep working unchanged; only boundary
  behavior changes.
- `FilterSelect`'s Up/Down stay bound (by `Select` itself) to open the dropdown
  overlay; while that overlay is open, focus lives on the internal
  `SelectOverlay`, not on this widget, so the new bindings simply don't fire
  in that state — no extra guarding needed.

### 2. Wire into `tui.py`

- Import `FilterInput`, `FilterSelect`, `FilterCheckbox` from
  `game_collections.apply.filter_widgets`.
- In `_mount_picker`, swap the four `Input(...)` calls for `FilterInput(...)`,
  the two `Select(...)` calls for `FilterSelect(...)`, and the `Checkbox(...)`
  call for `FilterCheckbox(...)` — same ids/args, just the class changes.

### 3. Tree: Up at the top row escapes to the filters

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

- `src/game_collections/apply/filter_widgets.py` — new module: mixin + 3
  filter-row widget subclasses.
- `src/game_collections/apply/tui.py` — import the new widgets, swap them into
  `_mount_picker`, add the `action_cursor_up` override to `_BundleTree`.

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
