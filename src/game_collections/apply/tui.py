"""Textual picker for `game-collections apply`."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from rich.style import Style
from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Checkbox, Footer, Header, Input, ProgressBar, Select, Static, Tree
from textual.widgets._tree import TOGGLE_STYLE
from textual.widgets.tree import TreeNode

from game_collections.apply.config import ApplySelection
from game_collections.apply.filter_widgets import FilterCheckbox, FilterInput, FilterSelect
from game_collections.apply.metadata import BundleMetadata, load_bundle_metadata
from game_collections.apply.tree_checkbox import CheckState, is_checkbox_click, render_checkbox
from game_collections.lists import LoadedGameList, discover_game_lists
from game_collections.models import Game
from game_collections.sources.storefronts import product_url


def _open_url(url: str) -> None:
    """Hand a URL (or a custom URI scheme like ``steam://...``) off to the OS's own handler."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", url])
    elif sys.platform.startswith("win"):
        os.startfile(url)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", url])
    # end if
# end def _open_url


def _row_label(bundle: BundleMetadata) -> str:
    date = bundle.date or "????-??-??"
    kind = bundle.bundle_kind or "-"
    tier = f"tier {bundle.tier}" if bundle.tier is not None else "single"
    return f"[{bundle.source}/{kind}] {date}  {bundle.item_count:>3} items  {tier:<8}  {bundle.name}"
# end def _row_label


@dataclass(frozen=True, slots=True)
class _Filters:
    min_items: int | None = None
    max_items: int | None = None
    date_after: str | None = None
    date_before: str | None = None

    def matches(self, bundle: BundleMetadata) -> bool:
        if self.min_items is not None and bundle.item_count < self.min_items:
            return False
        # end if
        if self.max_items is not None and bundle.item_count > self.max_items:
            return False
        # end if
        if self.date_after is not None and (bundle.date is None or bundle.date < self.date_after):
            return False
        # end if
        if self.date_before is not None and (bundle.date is None or bundle.date > self.date_before):
            return False
        # end if
        return True
    # end def matches

# end class _Filters


@dataclass(frozen=True, slots=True)
class _NodeData:
    """What a tree node represents: a source group, a bundle, one of its games, or a game's link."""

    kind: Literal["source", "bundle", "game", "link"]
    source: str
    list_id: str | None = None
    game_index: int | None = None
    url: str | None = None
    enabled: bool = True
    check_state: CheckState | None = None

# end class _NodeData


class BundleTree(Tree[_NodeData]):
    """A tree with Finder-like navigation and Enter-to-select/open instead of Enter-to-expand."""

    BINDINGS = [
        ("left", "collapse_or_to_parent", "Collapse/parent"),
        ("right", "expand_or_first_child", "Expand"),
        ("+", "expand_cursor", "Expand"),
        ("-", "collapse_cursor", "Collapse"),
        ("shift+left", "collapse_cursor_recursive", "Collapse item+children"),
        ("shift+right", "expand_cursor_recursive", "Expand item+children"),
        ("ctrl+left", "collapse_all", "Collapse all"),
        ("ctrl+right", "expand_all", "Expand all"),
        ("enter", "toggle_selection", "Toggle selection/activate"),
    ]

    def __init__(
        self,
        on_toggle: Callable[[_NodeData], None],
        on_open: Callable[[_NodeData], None],
        populate_node: Callable[[TreeNode[_NodeData]], None],
    ) -> None:
        super().__init__("bundles", id="rows-tree")
        self._on_toggle = on_toggle
        self._on_open = on_open
        self._populate_node = populate_node
        self.show_root = False
        self.guide_depth = 2
    # end def __init__

    def action_cursor_up(self) -> None:
        if self.cursor_line <= 0:
            first_filter = self.screen.query_one("#filters").children[0]
            first_filter.focus()
        else:
            Tree.action_cursor_up(self)
        # end if
    # end def action_cursor_up

    def action_collapse_or_to_parent(self) -> None:
        node = self.cursor_node
        if node is None:
            return
        # end if
        if node.allow_expand and node.is_expanded:
            node.collapse()
        elif node.parent is not None:
            self.action_cursor_parent()
        # end if
    # end def action_collapse_or_to_parent

    def action_expand_or_first_child(self) -> None:
        node = self.cursor_node
        if node is None or not node.allow_expand:
            return
        # end if
        if not node.is_expanded:
            node.expand()
        else:
            self.action_cursor_down()
        # end if
    # end def action_expand_or_first_child

    def action_expand_cursor(self) -> None:
        node = self.cursor_node
        if node is not None and node.allow_expand:
            node.expand()
        # end if
    # end def action_expand_cursor

    def action_collapse_cursor(self) -> None:
        node = self.cursor_node
        if node is not None and node.allow_expand:
            node.collapse()
        # end if
    # end def action_collapse_cursor

    def _expand_recursive(self, node: TreeNode[_NodeData]) -> None:
        # Lazily-populated children (bundle -> games -> links) only exist once expanded,
        # and Tree's own `expand_all()` recurses synchronously over `node.children` before
        # our `NodeExpanded` handler (which populates them) ever runs - so a plain
        # `expand_all()` would stop at whatever's already loaded. Populate-then-recurse
        # ourselves instead.
        self._populate_node(node)
        if node.allow_expand:
            node.expand()
        # end if
        for child in node.children:
            self._expand_recursive(child)
        # end for
    # end def

    def _collapse_recursive(self, node: TreeNode[_NodeData]) -> None:
        if node.allow_expand:
            node.collapse()
        # end if
        for child in node.children:
            self._collapse_recursive(child)
        # end for
    # end def

    def action_expand_cursor_recursive(self) -> None:
        node = self.cursor_node
        if node is not None:
            self._expand_recursive(node)
        # end if
    # end def

    def action_collapse_cursor_recursive(self) -> None:
        node = self.cursor_node
        if node is not None:
            self._collapse_recursive(node)
        # end if
    # end def

    def action_expand_all(self) -> None:
        for child in self.root.children:
            self._expand_recursive(child)
        # end for
    # end def

    def action_collapse_all(self) -> None:
        for child in self.root.children:
            self._collapse_recursive(child)
        # end for
    # end def

    def action_toggle_selection(self) -> None:
        node = self.cursor_node
        if node is None or node.data is None:
            return
        # end if
        if node.data.kind in ("source", "bundle"):
            self._on_toggle(node.data)
        elif node.data.kind == "link":
            self._on_open(node.data)
        # end if
    # end def action_toggle_selection

    def render_label(self, node: TreeNode[_NodeData], base_style: Style, style: Style) -> Text:
        data = node.data
        if data is None or data.check_state is None:
            return super().render_label(node, base_style, style)
        # end if
        # Rebuild the expand-arrow prefix ourselves (rather than splicing into what
        # super().render_label() returns) so the checkbox lands *after* the arrow,
        # not before it.
        node_label = node._label.copy()
        node_label.stylize(style)
        if node.allow_expand:
            icon = (self.ICON_NODE_EXPANDED if node.is_expanded else self.ICON_NODE, base_style + TOGGLE_STYLE)
        else:
            icon = ("", base_style)
        # end if
        return Text.assemble(icon, render_checkbox(data.check_state, base_style), Text(" "), node_label)
    # end def

    async def _on_click(self, event: events.Click) -> None:
        # Textual dispatches "_on_click" to every class in the MRO that defines it, not just
        # the most-derived one - so calling `super()._on_click(event)` here would double up
        # with Tree's own base handler running automatically afterward. `prevent_default()`
        # (not `stop()`, which only affects bubbling to the *parent*) is what actually skips
        # that separate, automatic dispatch for this event.
        meta = event.style.meta
        if is_checkbox_click(meta) and "line" in meta:
            node = self.get_node_at_line(meta["line"])
            if node is not None and node.data is not None:
                self._on_toggle(node.data)
            # end if
            event.prevent_default()
        # end if
    # end def

# end class BundleTree


class ApplyPickerApp(App[ApplySelection | None]):
    """Filter and check/uncheck bundles, then save the selection to disk."""

    CSS = """
    #loading { align: center middle; width: 1fr; height: 1fr; }
    #loading-inner { width: auto; height: auto; }
    #loading-label { width: auto; content-align: center middle; margin-bottom: 1; }
    #loading-progress { width: 60; }
    #body { height: 1fr; }
    #filters { height: auto; padding: 1; }
    #filters Input, #filters Select { width: 20; margin-right: 1; }
    #rows-tree { height: 1fr; min-height: 5; }
    #actions { height: auto; padding: 1; }
    """
    BINDINGS = [
        ("ctrl+s", "save", "Save & exit"),
        ("escape", "cancel", "Cancel"),
        ("ctrl+a", "select_all_or_none", "Select all/none"),
    ]

    def __init__(
        self,
        lists_root: Path,
        excluded: set[str],
        match_mode: Literal["any", "all", "none"] = "all",
        tier_mode: Literal["all", "highest"] = "highest",
        owned_app_ids: frozenset[int] | None = None,
    ) -> None:
        super().__init__()
        self._lists_root = lists_root
        self._excluded = set(excluded)
        self._row_filters = _Filters()
        self._bundles: list[BundleMetadata] = []
        self._checked: set[str] = set()
        self._expanded_sources: set[str] = set()
        self._show_filtered = False
        self._game_lists_by_id: dict[str, LoadedGameList] = {}
        # None means ownership is unknown (no Steam adapter was queried) - in that case
        # nothing is marked as owned/unowned; every game/bundle renders as it did before.
        self._owned_app_ids = owned_app_ids
        self.all_game_lists: list[LoadedGameList] = []
        self.match_mode: Literal["any", "all", "none"] = match_mode
        self.tier_mode: Literal["all", "highest"] = tier_mode
    # end def __init__

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="loading"):
            with Vertical(id="loading-inner"):
                yield Static("Loading lists...", id="loading-label")
                yield ProgressBar(id="loading-progress", show_eta=False)
            # end with
        # end with
    # end def compose

    def on_mount(self) -> None:
        self._load_lists()
    # end def on_mount

    @work(thread=True)
    def _load_lists(self) -> None:
        def on_progress(index: int, total: int, path: Path) -> None:
            self.call_from_thread(self._update_loading_progress, index, total, path)
        # end def on_progress

        game_lists = discover_game_lists(self._lists_root, on_progress=on_progress)
        bundles = load_bundle_metadata(game_lists)
        self.call_from_thread(self._finish_loading, game_lists, bundles)
    # end def _load_lists

    def _update_loading_progress(self, index: int, total: int, path: Path) -> None:
        self.query_one("#loading-label", Static).update(f"Loading lists... ({index}/{total}) {path.name}")
        self.query_one("#loading-progress", ProgressBar).update(total=total, progress=index)
    # end def _update_loading_progress

    def _finish_loading(self, game_lists: list[LoadedGameList], bundles: list[BundleMetadata]) -> None:
        self.all_game_lists = game_lists
        self._bundles = bundles
        self._game_lists_by_id = {game_list.id: game_list for game_list in game_lists}
        self._checked = {bundle.list_id for bundle in bundles if bundle.list_id not in self._excluded}
        self._deselect_filtered_out()
        self.query_one("#loading").remove()
        self._mount_picker()
    # end def _finish_loading

    def _mount_picker(self) -> None:
        filters = Horizontal(
            FilterInput(placeholder="min items", id="filter-min-items"),
            FilterInput(placeholder="max items", id="filter-max-items"),
            FilterInput(placeholder="date after (YYYY-MM-DD)", id="filter-date-after"),
            FilterInput(placeholder="date before (YYYY-MM-DD)", id="filter-date-before"),
            FilterSelect(
                [("mode: off", "none"), ("mode: any", "any"), ("mode: all", "all")],
                value=self.match_mode,
                allow_blank=False,
                id="filter-mode",
            ),
            FilterSelect(
                [("tiers: highest", "highest"), ("tiers: all", "all")],
                value=self.tier_mode,
                allow_blank=False,
                id="filter-tiers",
            ),
            FilterCheckbox("show filtered (as unchecked)", value=self._show_filtered, id="filter-show-filtered"),
            id="filters",
        )
        rows = BundleTree(self._toggle, self._open, self._populate_node)
        actions = Horizontal(
            Button("Save & Exit (ctrl+s)", id="save-button", variant="success"),
            Button("Cancel (esc)", id="cancel-button", variant="error"),
            Static(id="status"),
            id="actions",
        )
        body = VerticalScroll(filters, rows, actions, id="body")
        self.mount_all([body, Footer()])
        self.call_after_refresh(self._initial_tree_setup)
    # end def _mount_picker

    def _initial_tree_setup(self) -> None:
        self._rebuild_tree()
        tree = self._tree()
        tree.focus()
        if tree.root.children:
            tree.cursor_line = 0
        # end if
    # end def _initial_tree_setup

    def _sources(self) -> list[str]:
        return sorted({bundle.source for bundle in self._bundles})
    # end def _sources

    def _tree(self) -> BundleTree:
        return self.query_one("#rows-tree", BundleTree)
    # end def _tree

    def _source_check_state(self, bundles: list[BundleMetadata]) -> CheckState:
        total = len(bundles)
        checked_count = sum(1 for bundle in bundles if bundle.list_id in self._checked)
        if total == 0 or checked_count == 0:
            return "unchecked"
        elif checked_count == total:
            return "checked"
        # end if
        return "mixed"
    # end def _source_check_state

    def _source_label(self, source: str, bundles: list[BundleMetadata]) -> Text:
        total = len(bundles)
        checked_count = sum(1 for bundle in bundles if bundle.list_id in self._checked)
        text = Text(f"{source} ({checked_count}/{total})")
        # Grey the whole category when every bundle shown under it is known to be
        # 0-owned - under "any"/"all" this can't actually happen (those bundles are
        # hidden outright instead, see _bundle_hidden_by_ownership), so this only ever
        # fires in "none" mode, where 0-owned bundles stay visible and selectable.
        if bundles and all(self._bundle_zero_owned(bundle) is True for bundle in bundles):
            text.style = "dim"
        # end if
        return text
    # end def _source_label

    def _game_owned(self, game: Game) -> bool:
        """Whether a game has at least one Steam ID present in ``owned_app_ids``.

        Returns ``True`` (never grey it out) when ownership is unknown entirely.
        """
        if self._owned_app_ids is None:
            return True
        # end if
        for identifier in game.qualified_ids:
            if identifier.provider != "steam":
                continue
            # end if
            try:
                app_id = int(identifier.value)
            except ValueError:
                continue
            # end try
            if app_id in self._owned_app_ids:
                return True
            # end if
        # end for
        return False
    # end def _game_owned

    def _bundle_owned_fraction(self, bundle: BundleMetadata) -> tuple[int, int] | None:
        """``(owned, total)`` games in a bundle, or ``None`` if ownership is unknown."""
        if self._owned_app_ids is None:
            return None
        # end if
        game_list = self._game_lists_by_id.get(bundle.list_id)
        if game_list is None:
            return None
        # end if
        games = game_list.data.games
        return sum(1 for game in games if self._game_owned(game)), len(games)
    # end def _bundle_owned_fraction

    def _bundle_zero_owned(self, bundle: BundleMetadata) -> bool | None:
        """``True``/``False`` if ownership is known, ``None`` if it isn't."""
        fraction = self._bundle_owned_fraction(bundle)
        if fraction is None:
            return None
        # end if
        return fraction[0] == 0
    # end def _bundle_zero_owned

    def _bundle_hidden_by_ownership(self, bundle: BundleMetadata) -> bool:
        """Hide a bundle that could never become eligible under the current `mode`.

        "any" needs at least one owned game, so hide only when 0 are owned. "all" needs
        *every* game owned, so hide as soon as even one isn't - not just when 0 are (that
        was a bug: "all" was hiding/greying exactly the same bundles as "any"). "none"
        skips ownership gating entirely, so nothing is hidden on this basis there.
        """
        fraction = self._bundle_owned_fraction(bundle)
        if fraction is None:
            return False
        # end if
        owned, total = fraction
        if self.match_mode == "any":
            return owned == 0
        elif self.match_mode == "all":
            return owned < total
        # end if
        return False
    # end def _bundle_hidden_by_ownership

    def _highest_tier_ids(self) -> set[str]:
        """``list_id``s that are the numerically-highest tier within their bundle directory."""
        groups: dict[str, list[BundleMetadata]] = {}
        for bundle in self._bundles:
            if bundle.tier is None:
                continue
            # end if
            parent = bundle.list_id.rpartition("/")[0]
            groups.setdefault(parent, []).append(bundle)
        # end for
        return {max(siblings, key=lambda bundle: bundle.tier or 0).list_id for siblings in groups.values()}
    # end def _highest_tier_ids

    def _bundle_matches_tier_filter(self, bundle: BundleMetadata, highest_tier_ids: set[str]) -> bool:
        if self.tier_mode == "all" or bundle.tier is None:
            return True
        # end if
        return bundle.list_id in highest_tier_ids
    # end def _bundle_matches_tier_filter

    def _bundle_matches_all_filters(self, bundle: BundleMetadata, highest_tier_ids: set[str]) -> bool:
        """Item-count/date, ownership (`mode`), and tier (`tiers: highest`) combined.

        This is the single "filtered out or not" concept the `show filtered` checkbox governs.
        """
        if not self._row_filters.matches(bundle):
            return False
        # end if
        if self._bundle_hidden_by_ownership(bundle):
            return False
        # end if
        if not self._bundle_matches_tier_filter(bundle, highest_tier_ids):
            return False
        # end if
        return True
    # end def _bundle_matches_all_filters

    def _bundle_label(self, bundle: BundleMetadata) -> Text:
        label = _row_label(bundle)
        fraction = self._bundle_owned_fraction(bundle)
        zero_owned = False
        if fraction is not None:
            owned, total = fraction
            label += f"  ({owned}/{total})"
            zero_owned = owned == 0
        # end if
        text = Text(label)
        if zero_owned:
            text.style = "dim"
        # end if
        return text
    # end def _bundle_label

    def _rebuild_tree(self) -> None:
        tree = self._tree()
        # Snapshot current expand state fresh each time - a plain `.add()` here would
        # never forget a source once expanded, silently re-expanding it forever even
        # after the user collapsed it.
        self._expanded_sources = {
            node.data.source for node in tree.root.children if node.data is not None and node.is_expanded
        }
        tree.root.remove_children()

        highest_tier_ids = self._highest_tier_ids()
        shown_bundles = 0
        for source in self._sources():
            source_bundles = [bundle for bundle in self._bundles if bundle.source == source]
            matching_bundles = [
                bundle for bundle in source_bundles if self._bundle_matches_all_filters(bundle, highest_tier_ids)
            ]
            # "show filtered" off: the list feeding the tree is filtered, so what's filtered
            # out simply isn't there. "show filtered" on: those bundles are added to the list
            # too, unchecked (see _deselect_filtered_out). No separate tracking either way -
            # if "show filtered" goes off again, whatever you'd checked among them just isn't
            # there to be part of the result anymore (see _build_selection).
            visible_bundles = source_bundles if self._show_filtered else matching_bundles
            if not visible_bundles:
                continue
            # end if
            source_node = tree.root.add(
                self._source_label(source, visible_bundles),
                data=_NodeData(kind="source", source=source, check_state=self._source_check_state(visible_bundles)),
            )
            for bundle in visible_bundles:
                bundle_check_state = "checked" if bundle.list_id in self._checked else "unchecked"
                source_node.add(
                    self._bundle_label(bundle),
                    data=_NodeData(
                        kind="bundle", source=source, list_id=bundle.list_id, check_state=bundle_check_state
                    ),
                    expand=False,
                    allow_expand=True,
                )
            # end for
            if source in self._expanded_sources:
                source_node.expand()
            # end if
            shown_bundles += len(visible_bundles)
        # end for

        self.query_one("#status", Static).update(f"{shown_bundles}/{len(self._bundles)} shown")
    # end def _rebuild_tree

    def on_tree_node_expanded(self, event: Tree.NodeExpanded[_NodeData]) -> None:
        self._populate_node(event.node)
    # end def on_tree_node_expanded

    def _populate_node(self, node: TreeNode[_NodeData]) -> None:
        """Lazily fill in a node's children the first time it's expanded (bundle -> games,
        game -> links); a no-op for anything already populated or without lazy children.
        """
        data = node.data
        if data is None or node.children:
            return
        # end if
        if data.kind == "bundle":
            self._populate_games(node, data)
        elif data.kind == "game":
            self._populate_links(node, data)
        # end if
    # end def

    def _game_label(self, game: Game) -> Text:
        text = Text(game.name)
        if not self._game_owned(game):
            text.style = "dim"
        # end if
        return text
    # end def _game_label

    def _populate_games(self, node: TreeNode[_NodeData], data: _NodeData) -> None:
        game_list = self._game_lists_by_id.get(data.list_id or "")
        if game_list is None:
            return
        # end if
        for index, game in enumerate(game_list.data.games):
            node.add(
                self._game_label(game),
                data=_NodeData(kind="game", source=data.source, list_id=data.list_id, game_index=index),
                expand=False,
                allow_expand=True,
            )
        # end for
    # end def _populate_games

    def _populate_links(self, node: TreeNode[_NodeData], data: _NodeData) -> None:
        game_list = self._game_lists_by_id.get(data.list_id or "")
        if game_list is None or data.game_index is None:
            return
        # end if
        game = game_list.data.games[data.game_index]

        steam_value: str | None = None
        for identifier in game.qualified_ids:
            url = product_url(identifier.provider, identifier.value)
            if url is None:
                continue
            # end if
            if identifier.provider == "steam":
                steam_value = identifier.value
            # end if
            node.add_leaf(
                Text(f"Store: {identifier.provider}"),
                data=_NodeData(kind="link", source=data.source, url=url, enabled=True),
            )
        # end for

        launch_enabled = steam_value is not None
        launch_label = Text("Launch on Steam", style=None if launch_enabled else "dim")
        node.add_leaf(
            launch_label,
            data=_NodeData(
                kind="link",
                source=data.source,
                url=f"steam://rungameid/{steam_value}" if steam_value is not None else None,
                enabled=launch_enabled,
            ),
        )
    # end def _populate_links

    def _open(self, data: _NodeData) -> None:
        if data.enabled and data.url is not None:
            _open_url(data.url)
        # end if
    # end def _open

    def _toggle(self, data: _NodeData) -> None:
        if data.kind == "bundle":
            if data.list_id in self._checked:
                self._checked.discard(data.list_id)
            else:
                self._checked.add(data.list_id)
            # end if
        else:
            bundles = [bundle for bundle in self._bundles if bundle.source == data.source]
            all_checked = bool(bundles) and all(bundle.list_id in self._checked for bundle in bundles)
            for bundle in bundles:
                if all_checked:
                    self._checked.discard(bundle.list_id)
                else:
                    self._checked.add(bundle.list_id)
                # end if
            # end for
        # end if
        self._rebuild_tree()
    # end def _toggle

    def action_select_all_or_none(self) -> None:
        """Select or deselect every bundle currently passing the item-count/date filters."""
        selectable = [bundle.list_id for bundle in self._bundles if self._row_filters.matches(bundle)]
        if not selectable:
            return
        # end if
        if all(list_id in self._checked for list_id in selectable):
            self._checked.difference_update(selectable)
        else:
            self._checked.update(selectable)
        # end if
        self._rebuild_tree()
    # end def action_select_all_or_none

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "filter-mode":
            new_match_mode = cast(Literal["any", "all", "none"], event.value)
            # Select posts a Changed event for its own initial `value=` on mount too;
            # only rebuild (mode now affects 0-owned hide/grey) on an actual change.
            if new_match_mode != self.match_mode:
                self.match_mode = new_match_mode
                self._deselect_filtered_out()
                self._rebuild_tree()
            # end if
        elif event.select.id == "filter-tiers":
            new_tier_mode = cast(Literal["all", "highest"], event.value)
            # Select posts a Changed event for its own initial `value=` on mount too;
            # only recompute the selection on an actual, user-driven change.
            if new_tier_mode != self.tier_mode:
                self.tier_mode = new_tier_mode
                self._apply_tier_mode_to_selection()
                self._rebuild_tree()
            # end if
        # end if
    # end def on_select_changed

    def _apply_tier_mode_to_selection(self) -> None:
        """Recompute checked state for sibling tier lists to match ``tier_mode``.

        Mirrors ``SteamAdapter``'s own "highest tier per bundle directory" grouping
        (see ``_selected_list_ids``) so the picker's checkmarks preview what `--tiers`
        will actually keep, instead of silently disagreeing with it until plan time.
        """
        groups: dict[str, list[BundleMetadata]] = {}
        for bundle in self._bundles:
            if bundle.tier is None:
                continue
            # end if
            parent = bundle.list_id.rpartition("/")[0]
            groups.setdefault(parent, []).append(bundle)
        # end for
        for siblings in groups.values():
            if self.tier_mode == "all":
                self._checked.update(bundle.list_id for bundle in siblings)
                continue
            # end if
            highest = max(siblings, key=lambda bundle: bundle.tier or 0)
            for bundle in siblings:
                if bundle.list_id == highest.list_id:
                    self._checked.add(bundle.list_id)
                else:
                    self._checked.discard(bundle.list_id)
                # end if
            # end for
        # end for
    # end def _apply_tier_mode_to_selection

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id == "filter-show-filtered":
            self._show_filtered = event.value
            self._rebuild_tree()
        # end if
    # end def on_checkbox_changed

    def _deselect_filtered_out(self) -> None:
        """A filter always deselects the bundles it excludes (item-count/date, `mode`'s
        ownership gate, `tiers: highest`), not just hides them - no separate tracking of
        why a bundle is deselected. One-way: widening a filter back doesn't re-select
        anything - only an explicit `enter` on the tree (or ``ctrl+a``) does.
        """
        highest_tier_ids = self._highest_tier_ids()
        for bundle in self._bundles:
            if not self._bundle_matches_all_filters(bundle, highest_tier_ids):
                self._checked.discard(bundle.list_id)
            # end if
        # end for
    # end def

    def on_input_changed(self, event: Input.Changed) -> None:
        raw = event.value.strip()

        def as_int(value: str) -> int | None:
            try:
                return int(value) if value else None
            except ValueError:
                return None
        # end def as_int

        if event.input.id == "filter-min-items":
            self._row_filters = _Filters(
                min_items=as_int(raw),
                max_items=self._row_filters.max_items,
                date_after=self._row_filters.date_after,
                date_before=self._row_filters.date_before,
            )
        elif event.input.id == "filter-max-items":
            self._row_filters = _Filters(
                min_items=self._row_filters.min_items,
                max_items=as_int(raw),
                date_after=self._row_filters.date_after,
                date_before=self._row_filters.date_before,
            )
        elif event.input.id == "filter-date-after":
            self._row_filters = _Filters(
                min_items=self._row_filters.min_items,
                max_items=self._row_filters.max_items,
                date_after=raw or None,
                date_before=self._row_filters.date_before,
            )
        elif event.input.id == "filter-date-before":
            self._row_filters = _Filters(
                min_items=self._row_filters.min_items,
                max_items=self._row_filters.max_items,
                date_after=self._row_filters.date_after,
                date_before=raw or None,
            )
        else:
            return
        # end if
        self._deselect_filtered_out()
        self._rebuild_tree()
    # end def on_input_changed

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-button":
            self.action_save()
        elif event.button.id == "cancel-button":
            self.action_cancel()
        # end if
    # end def on_button_pressed

    def _build_selection(self) -> ApplySelection:
        # A checked-but-filtered-out bundle (possible if you checked it while "show
        # filtered" was on, then turned it back off) never makes it into `selected`,
        # authoritatively - no separate tracking needed to enforce that.
        highest_tier_ids = self._highest_tier_ids()
        selected: list[str] = []
        excluded: list[str] = []
        for bundle in self._bundles:
            if bundle.list_id in self._checked and self._bundle_matches_all_filters(bundle, highest_tier_ids):
                selected.append(bundle.list_id)
            else:
                excluded.append(bundle.list_id)
            # end if
        # end for
        return ApplySelection(schema=1, selected=selected, excluded=excluded, updated_at=datetime.now(UTC))
    # end def _build_selection

    def action_save(self) -> None:
        self.exit(result=self._build_selection())
    # end def action_save

    def action_cancel(self) -> None:
        self.exit(result=None)
    # end def action_cancel

# end class ApplyPickerApp
