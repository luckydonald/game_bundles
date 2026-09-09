I now have a complete picture. Here is the investigation report.

## 1. Where the interactive prompt / "Multiple…" / "Other…" handling lives

`/home/user/git/luckydonald/game_collections/src/game_collections/sources/prompting.py` — this is the single shared chooser used by every source (greenmangaming, humblebundle, etc.):

- `choose_store_candidate()` (lines 55–118) prints `Resolve {title!r} on {provider}:`, lists candidates, then `Multiple…` and `Other…` rows.
- The "Multiple" branch (lines 90–106) loops calling `typer.prompt("Name of one separate game (blank to finish)", default=default)` (line 97), collecting names into a plain `list[str]` with **no uniqueness check whatsoever** — it only stops on a blank answer (`if not name: break`) — then returns them as `ChosenNames(names=names)`.
- `collect_one_name()` (lines 48–52) is the interleaved-mode sibling (used by `humblebundle.resolver`), same "blank ends collection" logic, no dedupe.

Green Man Gaming's resolver (`src/game_collections/sources/greenmangaming/resolver.py`) and the shared `search.py` both call into this same chooser via a `CandidateChooser`/`SearchChooser` callback; the CLI wires `choose_store_candidate` from `cli.py` (e.g. line 831 `choose = ... choose_store_candidate`).

## 2. "Multiple" flow → GameList entries, exact code path

For `scrape --git greenmangaming`, the path is:

1. `StorefrontResolver._resolve_title()` in `src/game_collections/sources/greenmangaming/resolver.py:174-231` — when `self._choose(...)` returns a `ChosenNames` (line 216), it recurses once per typed sub-title (`self._resolve_title(sub_title, stores, f"{cache_key}::{index}", mapping)`, line 219) and returns the list of `ResolvedGame`s — **no check that `sub_title` differs from `title` or from any other already-known name.**
2. `resolve_archive()` runs this per distinct item across a whole bundle, storing results into `GmgResolution(splits=[...])` per item (in `crawler.py`, around `resolve_archive`).
3. `_games_for_item()` in `src/game_collections/sources/greenmangaming/crawler.py:242-249` turns each split into a `Game(name=split.name, ids=split.ids, group=group)` with no name-collision check against other items.
4. `write_gmg_offer()` (`crawler.py:252+`) accumulates all `Game`s for a tier into `games: list[Game]` (loop at ~line 265-276) and only at the very end constructs `GameList(schema=1, name=..., games=games, ...)` (around line 290s) — this is the first and only place duplicate names would ever be caught.

## 3. Duplicate-name validator

`src/game_collections/models.py:162-190`, `GameList.validate_games` (`model_validator(mode="after")`):

```python
@model_validator(mode="after")
def validate_games(self) -> Self:
    names = [game.name.casefold() for game in self.games]
    if len(names) != len(set(names)):
        raise ValueError("list contains duplicate game names")
    # end if

    if duplicate_qualified_ids(self.games):
        raise ValueError("list contains duplicate qualified game IDs")
    # end if
    ...
```

It case-folds every `Game.name` and checks for set-size mismatch — this is exactly the check that fired for "BioShock: The Collection" (typed identically to the parent item's own name) and "Destiny 2: The Edge of Fate" (typed as a sub-name while it already existed as item #8 elsewhere in the bundle).

## 4. When is validation run relative to the interactive loop?

Only once, at the very end of the *entire* per-bundle interactive resolution, not incrementally:

- `crawl_gmg_offers()` (`crawler.py:150-229`) loops per bundle/slug (line 184). For each slug it fully runs `resolver.resolve_archive(archive, mapping, log=log)` (line 219) — which interactively resolves **every distinct item in that bundle**, including all "Multiple…" prompts — before calling `on_offer(offer)` (line 222-224).
- `on_offer` in `cli.py:835-846` calls `write_gmg_offer(...)` (line 837), which is where `GameList(...)` is finally constructed and validated, per tier.
- The whole per-slug block (including `on_offer`) is wrapped in `try: ... except (OSError, ValueError, GmgCrawlError) as error: errors.append(f"{slug}: {error}")` (`crawler.py:186/225-226`). Since Pydantic's `ValidationError` is a `ValueError` subclass, the failure surfaces as exactly `error: 2k-collection: 1 validation error for GameList\n  Value error, list contains duplicate game names [...]` in `report.errors`, printed by the CLI (`cli.py:869-870`).
- Consequence: nothing during the (potentially very long) interactive session validates names incrementally — the check only runs after the entire bundle's items (and every "Multiple…" sub-prompt series for that bundle) have been resolved. A failure there discards that bundle's `GameList` write entirely (`write_gmg_offer` never reaches `atomic_write` for the tier files), and — importantly — `write_gmg_resolution_map(resolution_map, mapping)` (`cli.py:845`) is also inside `on_offer`, so it's never reached for the failed bundle either, unless a *later* bundle in the same run succeeds and re-dumps the same in-memory `mapping` object (which does carry the failed bundle's already-resolved cache entries, since `_resolve_title` mutates `mapping.games` in place at `resolver.py:229` regardless of eventual write success). If the failing bundle is the last one crawled, its resolution-map entries are lost on disk entirely despite being resolved in memory.

## 5. Existing dedupe/collision check during "Multiple" or merge-back?

None found anywhere in the flow:
- `choose_store_candidate`'s Multiple-name loop (`prompting.py:94-106`) only checks `if not name: break` — no comparison against `title`, no comparison against previously entered names in the same loop, no comparison against anything already in the bundle/list.
- `_resolve_title`'s `ChosenNames` branch (`resolver.py:216-221`) just recurses per sub-title, no name check.
- `_games_for_item` / `write_gmg_offer`'s games-accumulation loop (`crawler.py:242-249` and the tier-building loop in `write_gmg_offer`) only dedupes by **qualified IDs** (`seen_ids` set of ID strings, `crawler.py` write loop) to avoid re-adding an item already covered by another item's IDs — it does not dedupe by **name** at all.
- The shared `search.py::complete_game_list`/`resolve_title` path (used by the `complete` command) has the identical gap: `games_out.append(...)` in the `Multiple…` split branch (`search.py:241-251`) has no name-collision check against `games_out` or the rest of the list either.

## 6. Handling when the typed sub-name equals an existing name (self or elsewhere)?

Not handled anywhere currently. Neither:
- typing the *same* name as the item currently being split (the "BioShock: The Collection" self-duplicate case), nor
- typing a name that already exists as a *different* entry in the bundle (the "Destiny 2: The Edge of Fate" cross-entry case),

is checked at prompt time, at `_resolve_title`/`resolve_title` recursion time, or at `Game`-list-assembly time. The only place either case is ever detected is the final `GameList.validate_games` case-fold duplicate check in `models.py:164-166`, by which point the entire bundle's interactive session (all items, all "Multiple…" sub-prompts) has already run to completion and is discarded/failed as a whole for that bundle.