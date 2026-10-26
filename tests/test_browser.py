"""Tests for the shared background Chromium launch helper."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from game_collections.sources.browser import first_or_new_page, launch_background_context


def test_launch_is_headed_and_minimized() -> None:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def launch(*args: Any, **kwargs: Any) -> str:
        calls.append((args, kwargs))
        return "context"
    # end def launch

    playwright = SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch))
    assert launch_background_context(playwright, "/tmp/profile") == "context"
    args, kwargs = calls[0]
    assert args == ("/tmp/profile",)
    assert kwargs["headless"] is False
    assert "--start-minimized" in kwargs["args"]
# end def test_launch_is_headed_and_minimized


def test_first_or_new_page_reuses_existing_tab() -> None:
    context = SimpleNamespace(pages=["initial"], new_page=lambda: "fresh")
    assert first_or_new_page(context) == "initial"
    assert first_or_new_page(SimpleNamespace(pages=[], new_page=lambda: "fresh")) == "fresh"
# end def test_first_or_new_page_reuses_existing_tab
