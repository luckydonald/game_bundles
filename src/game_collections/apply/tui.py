"""Textual picker for `game-collections apply`."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Checkbox, Footer, Header, Input, Select, Static

from game_collections.apply.config import ApplySelection
from game_collections.apply.metadata import BundleMetadata


ALL_SOURCES = "(all)"


def _row_label(bundle: BundleMetadata) -> str:
    date = bundle.date or "?"
    kind = bundle.bundle_kind or "-"
    tier = f"tier {bundle.tier}" if bundle.tier is not None else "single"
    return f"[{bundle.source}/{kind}] {date}  {bundle.item_count:>3} items  {tier:<8}  {bundle.name}"
# end def _row_label


@dataclass(frozen=True, slots=True)
class _Filters:
    source: str = ALL_SOURCES
    min_items: int | None = None
    max_items: int | None = None
    date_after: str | None = None
    date_before: str | None = None

    def matches(self, bundle: BundleMetadata) -> bool:
        if self.source != ALL_SOURCES and bundle.source != self.source:
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
    #filters { height: auto; padding: 1; }
    #filters Input, #filters Select { width: 20; margin-right: 1; }
    #rows { height: 1fr; }
    #actions { height: auto; padding: 1; }
    """
    BINDINGS = [("ctrl+s", "save", "Save & exit"), ("escape", "cancel", "Cancel")]

    def __init__(self, bundles: list[BundleMetadata], excluded: set[str]) -> None:
        super().__init__()
        self._bundles = bundles
        self._excluded = set(excluded)
        self._row_filters = _Filters()
    # end def __init__

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="filters"):
            yield Select(
                [(ALL_SOURCES, ALL_SOURCES)] + [(source, source) for source in self._sources()],
                value=ALL_SOURCES,
                id="filter-source",
            )
            yield Input(placeholder="min items", id="filter-min-items")
            yield Input(placeholder="max items", id="filter-max-items")
            yield Input(placeholder="date after (YYYY-MM-DD)", id="filter-date-after")
            yield Input(placeholder="date before (YYYY-MM-DD)", id="filter-date-before")
        # end with
        with VerticalScroll(id="rows"):
            for index, bundle in enumerate(self._bundles):
                yield Checkbox(
                    _row_label(bundle),
                    value=bundle.list_id not in self._excluded,
                    id=f"row-{index}",
                )
            # end for
        # end with
        with Horizontal(id="actions"):
            yield Button("Save & Exit (ctrl+s)", id="save-button", variant="success")
            yield Button("Cancel (esc)", id="cancel-button", variant="error")
            yield Static(id="status")
        # end with
        yield Footer()
    # end def compose

    def _sources(self) -> list[str]:
        return sorted({bundle.source for bundle in self._bundles})
    # end def _sources

    def _checkbox(self, index: int) -> Checkbox:
        return self.query_one(f"#row-{index}", Checkbox)
    # end def _checkbox

    def _apply_filters(self) -> None:
        visible = 0
        for index, bundle in enumerate(self._bundles):
            matches = self._row_filters.matches(bundle)
            self._checkbox(index).display = matches
            if matches:
                visible += 1
            # end if
        # end for
        self.query_one("#status", Static).update(f"{visible}/{len(self._bundles)} shown")
    # end def _apply_filters

    def on_mount(self) -> None:
        self._apply_filters()
    # end def on_mount

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "filter-source":
            self._row_filters = _Filters(
                source=str(event.value),
                min_items=self._row_filters.min_items,
                max_items=self._row_filters.max_items,
                date_after=self._row_filters.date_after,
                date_before=self._row_filters.date_before,
            )
            self._apply_filters()
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
                source=self._row_filters.source,
                min_items=as_int(raw),
                max_items=self._row_filters.max_items,
                date_after=self._row_filters.date_after,
                date_before=self._row_filters.date_before,
            )
        elif event.input.id == "filter-max-items":
            self._row_filters = _Filters(
                source=self._row_filters.source,
                min_items=self._row_filters.min_items,
                max_items=as_int(raw),
                date_after=self._row_filters.date_after,
                date_before=self._row_filters.date_before,
            )
        elif event.input.id == "filter-date-after":
            self._row_filters = _Filters(
                source=self._row_filters.source,
                min_items=self._row_filters.min_items,
                max_items=self._row_filters.max_items,
                date_after=raw or None,
                date_before=self._row_filters.date_before,
            )
        elif event.input.id == "filter-date-before":
            self._row_filters = _Filters(
                source=self._row_filters.source,
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
        for index, bundle in enumerate(self._bundles):
            if self._checkbox(index).value:
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
