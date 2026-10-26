"""Decide whether a `<ul>` in a Humble "DLC pack" description lists separate DLCs or is just explainer text."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from game_collections.sources.storefronts import StoreCandidate, normalized_title


__all__ = [
    "MAX_TITLE_WORDS",
    "PROSE_SEPARATORS",
    "DlcListChooser",
    "DlcListVerdict",
    "SteamSearch",
    "classify_dlc_list",
    "looks_like_prose",
]


# A real storefront product title is short; the longest bare DLC title seen on Humble is well under this.
MAX_TITLE_WORDS = 10
# Separators that explainer bullets use between a name and its description, e.g. "Voltaic Wrench — shock your enemies".
# A plain " - " or ": " is deliberately absent: real titles use them ("Dagon - The Eldritch Box DLC", "Our Life: Beginnings & Always").
PROSE_SEPARATORS = (" — ", " – ")

DlcListVerdict = Literal["yes", "no", "ask"]
# `(item title, bullets) -> are these separate games/DLCs?` - injected so the CLI picks prompt vs. non-interactive "no".
DlcListChooser = Callable[[str, list[str]], bool]
SteamSearch = Callable[[str], list[StoreCandidate]]


def looks_like_prose(text: str) -> bool:
    """True for a bullet that reads as a description rather than a bare product title."""
    if len(text.split()) > MAX_TITLE_WORDS:
        return True
    # end if
    if text.rstrip().endswith((".", "!", "?")):
        return True
    # end if
    return any(separator in text for separator in PROSE_SEPARATORS)
# end def looks_like_prose


def classify_dlc_list(
    bullets: list[str],
    base_game_url: str | None,
    search_steam: SteamSearch,
) -> DlcListVerdict:
    """Decide a single `<ul>`: "no" for obvious prose, "yes" for strong evidence, else "ask".

    Evidence for "yes" combines two independent signals: the description links a (free) Steam
    base game, and the first bullet exactly matches one Steam search result. A real DLC pack's
    bullets are full storefront titles ("Dagon - The Eldritch Box DLC"), whereas an explainer line
    ("Brecken Outfit — lead the way…") never exact-matches anything. Only the first bullet is
    searched to keep this to a single request.
    """
    if not bullets:
        return "no"
    # end if
    if any(looks_like_prose(bullet) for bullet in bullets):
        return "no"
    # end if
    if base_game_url is None:
        return "ask"
    # end if
    wanted = normalized_title(bullets[0])
    exact = [candidate for candidate in search_steam(bullets[0]) if normalized_title(candidate.title) == wanted]
    if len(exact) == 1:
        return "yes"
    # end if
    return "ask"
# end def classify_dlc_list

