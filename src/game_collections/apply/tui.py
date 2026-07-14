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

from rich.markup import escape
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Checkbox, Footer, Header, Input, ProgressBar, Select, Static, Tree
from textual.widgets.tree import TreeNode

from game_collections.apply.config import ApplySelection
from game_collections.apply.metadata import BundleMetadata, load_bundle_metadata
from game_collections.lists import LoadedGameList, discover_game_lists
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

# end class _NodeData


class _BundleTree(Tree[_NodeData]):
    """A tree with Finder-like navigation and Enter-to-select/open instead of Enter-to-expand."""

    BINDINGS = [
        ("left", "collapse_or_to_parent", "Collapse/parent"),
        ("right", "expand_or_first_child", "Expand"),
        ("+", "expand_cursor", "Expand"),
        ("-", "collapse_cursor", "Collapse"),
        ("enter", "toggle_selection", "Select/deselect/open"),
    ]

    def __init__(self, on_toggle: Callable[[_NodeData], None], on_open: Callable[[_NodeData], None]) -> None:
        super().__init__("bundles", id="rows-tree")
        self._on_toggle = on_toggle
        self._on_open = on_open
        self.show_root = False
        self.guide_depth = 2
    # end def __init__

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

# end class _BundleTree


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
    BINDINGS = [("ctrl+s", "save", "Save & exit"), ("escape", "cancel", "Cancel")]

    def __init__(
        self,
        lists_root: Path,
        excluded: set[str],
        match_mode: Literal["any", "all"] = "all",
        tier_mode: Literal["all", "highest"] = "highest",
    ) -> None:
        super().__init__()
        self._lists_root = lists_root
        self._excluded = set(excluded)
        self._row_filters = _Filters()
        self._bundles: list[BundleMetadata] = []
        self._checked: set[str] = set()
        self._expanded_sources: set[str] = set()
        self._hide_filtered = False
        self._game_lists_by_id: dict[str, LoadedGameList] = {}
        self.all_game_lists: list[LoadedGameList] = []
        self.match_mode: Literal["any", "all"] = match_mode
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
        self.query_one("#loading").remove()
        self._mount_picker()
    # end def _finish_loading

    def _mount_picker(self) -> None:
        filters = Horizontal(
            Input(placeholder="min items", id="filter-min-items"),
            Input(placeholder="max items", id="filter-max-items"),
            Input(placeholder="date after (YYYY-MM-DD)", id="filter-date-after"),
            Input(placeholder="date before (YYYY-MM-DD)", id="filter-date-before"),
            Select(
                [("mode: all", "all"), ("mode: any", "any")],
                value=self.match_mode,
                allow_blank=False,
                id="filter-mode",
            ),
            Select(
                [("tiers: highest", "highest"), ("tiers: all", "all")],
                value=self.tier_mode,
                allow_blank=False,
                id="filter-tiers",
            ),
            Checkbox("hide filtered", value=self._hide_filtered, id="filter-hide-filtered"),
            id="filters",
        )
        rows = _BundleTree(self._toggle, self._open)
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

    def _tree(self) -> _BundleTree:
        return self.query_one("#rows-tree", _BundleTree)
    # end def _tree

    def _source_label(self, source: str, bundles: list[BundleMetadata]) -> str:
        total = len(bundles)
        checked_count = sum(1 for bundle in bundles if bundle.list_id in self._checked)
        if total == 0 or checked_count == 0:
            glyph = "[ ]"
        elif checked_count == total:
            glyph = "[x]"
        else:
            glyph = "[-]"
        # end if
        return escape(f"{glyph} {source} ({checked_count}/{total})")
    # end def _source_label

    def _bundle_label(self, bundle: BundleMetadata) -> str:
        glyph = "[x]" if bundle.list_id in self._checked else "[ ]"
        return escape(f"{glyph} {_row_label(bundle)}")
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

        shown_bundles = 0
        for source in self._sources():
            source_bundles = [bundle for bundle in self._bundles if bundle.source == source]
            matching_bundles = [bundle for bundle in source_bundles if self._row_filters.matches(bundle)]
            # A filter always deselects what it excludes (see _deselect_filtered_out); "hide
            # filtered" only additionally controls whether those now-deselected, non-matching
            # bundles stay visible (greyed out) or disappear from the tree entirely.
            visible_bundles = matching_bundles if self._hide_filtered else source_bundles
            if not visible_bundles:
                continue
            # end if
            source_node = tree.root.add(
                self._source_label(source, visible_bundles),
                data=_NodeData(kind="source", source=source),
            )
            for bundle in visible_bundles:
                source_node.add(
                    self._bundle_label(bundle),
                    data=_NodeData(kind="bundle", source=source, list_id=bundle.list_id),
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
        node = event.node
        data = node.data
        if data is None or node.children:
            return
        # end if
        if data.kind == "bundle":
            self._populate_games(node, data)
        elif data.kind == "game":
            self._populate_links(node, data)
        # end if
    # end def on_tree_node_expanded

    def _populate_games(self, node: TreeNode[_NodeData], data: _NodeData) -> None:
        game_list = self._game_lists_by_id.get(data.list_id or "")
        if game_list is None:
            return
        # end if
        for index, game in enumerate(game_list.data.games):
            node.add(
                escape(game.name),
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

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "filter-mode":
            self.match_mode = cast(Literal["any", "all"], event.value)
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
        if event.checkbox.id == "filter-hide-filtered":
            self._hide_filtered = event.value
            self._rebuild_tree()
        # end if
    # end def on_checkbox_changed

    def _deselect_filtered_out(self) -> None:
        """A filter always deselects the bundles it excludes, not just hides them.

        One-way: widening the filter back doesn't re-select anything - only an explicit
        `enter` on the tree (or ``ctrl+a``) brings a bundle back into the selection.
        """
        for bundle in self._bundles:
            if not self._row_filters.matches(bundle):
                self._checked.discard(bundle.list_id)
            # end if
        # end for
    # end def _deselect_filtered_out

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
        selected: list[str] = []
        excluded: list[str] = []
        for bundle in self._bundles:
            if bundle.list_id in self._checked:
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
