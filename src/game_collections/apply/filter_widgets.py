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
