"""Shared launch of the headed `patchright` Chromium used for Cloudflare-gated sites."""

from __future__ import annotations

from typing import Any


__all__ = [
    "BACKGROUND_BROWSER_ARGS",
    "launch_background_context",
    "first_or_new_page",
]


# Cloudflare's managed challenge only passes in a *headed* browser, so hiding
# the window via headless mode is not an option. Starting minimized keeps the
# window out of the user's way instead; activation on later tab opens is
# avoided separately by reusing one page (see `first_or_new_page`).
BACKGROUND_BROWSER_ARGS: tuple[str, ...] = ("--start-minimized",)


def launch_background_context(playwright: Any, user_data_dir: str) -> Any:
    """Launch a headed, minimized persistent Chromium context."""
    return playwright.chromium.launch_persistent_context(
        user_data_dir,
        headless=False,
        no_viewport=True,
        args=list(BACKGROUND_BROWSER_ARGS),
    )
# end def launch_background_context


def first_or_new_page(context: Any) -> Any:
    """Return the context's initial tab if it still exists, else open one.

    Every `context.new_page()` makes Chromium activate itself and jump to the
    foreground, so callers keep a single page and navigate it with `goto`.
    """
    if context.pages:
        return context.pages[0]
    # end if
    return context.new_page()
# end def first_or_new_page
