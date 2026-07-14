"""Textual picker for `game-collections apply`."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input, ProgressBar, Select, SelectionList, Static
from textual.widgets.selection_list import Selection

from game_collections.apply.config import ApplySelection
from game_collections.apply.metadata import BundleMetadata, load_bundle_metadata
from game_collections.lists import LoadedGameList, discover_game_lists


def _row_label(bundle: BundleMetadata) -> str:
    date = bundle.date or "????-??-??"
    kind = bundle.bundle_kind or "-"
    tier = f"tier {bundle.tier}" if bundle.tier is not None else "single"
    return f"[{bundle.source}/{kind}] {date}  {bundle.item_count:>3} items  {tier:<8}  {bundle.name}"
# end def _row_label


@dataclass(frozen=True, slots=True)
class _Filters:
    sources: frozenset[str] | None = None
    min_items: int | None = None
    max_items: int | None = None
    date_after: str | None = None
    date_before: str | None = None

    def matches(self, bundle: BundleMetadata) -> bool:
        if self.sources is not None and bundle.source not in self.sources:
            return False
        # end if
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


class ApplyPickerApp(App[ApplySelection | None]):
    """Filter and check/uncheck bundles, then save the selection to disk."""

    CSS = """
    #loading { align: center middle; height: 1fr; }
    #loading Static { margin-bottom: 1; }
    #loading ProgressBar { width: 60; }
    #filters { height: auto; padding: 1; }
    #filters Input, #filters Select { width: 20; margin-right: 1; }
    #filter-source { width: 28; height: 8; margin-right: 1; }
    #rows { height: 1fr; }
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
        self.all_game_lists: list[LoadedGameList] = []
        self.match_mode: Literal["any", "all"] = match_mode
        self.tier_mode: Literal["all", "highest"] = tier_mode
    # end def __init__

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="loading"):
            yield Static("Loading lists...", id="loading-label")
            yield ProgressBar(id="loading-progress", show_eta=False)
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
        self._checked = {bundle.list_id for bundle in bundles if bundle.list_id not in self._excluded}
        self.query_one("#loading").remove()
        self._mount_picker()
    # end def _finish_loading

    def _mount_picker(self) -> None:
        filters = Horizontal(
            SelectionList(
                *(Selection(source, source, True) for source in self._sources()),
                id="filter-source",
            ),
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
            id="filters",
        )
        rows = SelectionList(id="rows")
        actions = Horizontal(
            Button("Save & Exit (ctrl+s)", id="save-button", variant="success"),
            Button("Cancel (esc)", id="cancel-button", variant="error"),
            Static(id="status"),
            id="actions",
        )
        self.mount_all([filters, rows, actions, Footer()])
        self.call_after_refresh(self._apply_filters)
    # end def _mount_picker

    def _sources(self) -> list[str]:
        return sorted({bundle.source for bundle in self._bundles})
    # end def _sources

    def _rows(self) -> SelectionList[str]:
        return self.query_one("#rows", SelectionList)
    # end def _rows

    def _apply_filters(self) -> None:
        visible = [bundle for bundle in self._bundles if self._row_filters.matches(bundle)]
        rows = self._rows()
        rows.clear_options()
        rows.add_options(
            Selection(_row_label(bundle), bundle.list_id, bundle.list_id in self._checked) for bundle in visible
        )
        self.query_one("#status", Static).update(f"{len(visible)}/{len(self._bundles)} shown")
    # end def _apply_filters

    def on_selection_list_selection_toggled(self, event: SelectionList.SelectionToggled) -> None:
        if event.selection_list.id == "filter-source":
            self._row_filters = _Filters(
                sources=frozenset(event.selection_list.selected),
                min_items=self._row_filters.min_items,
                max_items=self._row_filters.max_items,
                date_after=self._row_filters.date_after,
                date_before=self._row_filters.date_before,
            )
            self._apply_filters()
            return
        # end if

        value = event.selection.value
        if value in event.selection_list.selected:
            self._checked.add(value)
        else:
            self._checked.discard(value)
        # end if
    # end def on_selection_list_selection_toggled

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "filter-mode":
            self.match_mode = cast(Literal["any", "all"], event.value)
        elif event.select.id == "filter-tiers":
            self.tier_mode = cast(Literal["all", "highest"], event.value)
        # end if
    # end def on_select_changed

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
                sources=self._row_filters.sources,
                min_items=as_int(raw),
                max_items=self._row_filters.max_items,
                date_after=self._row_filters.date_after,
                date_before=self._row_filters.date_before,
            )
        elif event.input.id == "filter-max-items":
            self._row_filters = _Filters(
                sources=self._row_filters.sources,
                min_items=self._row_filters.min_items,
                max_items=as_int(raw),
                date_after=self._row_filters.date_after,
                date_before=self._row_filters.date_before,
            )
        elif event.input.id == "filter-date-after":
            self._row_filters = _Filters(
                sources=self._row_filters.sources,
                min_items=self._row_filters.min_items,
                max_items=self._row_filters.max_items,
                date_after=raw or None,
                date_before=self._row_filters.date_before,
            )
        elif event.input.id == "filter-date-before":
            self._row_filters = _Filters(
                sources=self._row_filters.sources,
                min_items=self._row_filters.min_items,
                max_items=self._row_filters.max_items,
                date_after=self._row_filters.date_after,
                date_before=raw or None,
            )
        else:
            return
        # end if
        self._apply_filters()
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
