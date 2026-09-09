# Fix: interactive "Multiple…" resolution can silently produce duplicate game names, losing a whole bundle's work

## Context

`ai/errors/5.txt` is a log from `game-collections scrape --git greenmangaming`. During interactive resolution, the user split two entries via "Multiple…" (`BioShock: The Collection` and `Destiny 2: Year of Prophecy Edition`) and, in doing so, typed a name that duplicated another name already destined for the same bundle's `GameList` — once by re-typing the very same name twice for one split, once by typing a name (`Destiny 2: The Edge of Fate`) that already existed as a separate item elsewhere in the same bundle. Both only surfaced as a hard Pydantic error ("list contains duplicate game names") *after* the entire bundle's interactive resolution had finished — discarding all of that manual work for `2k-collection` and `destiny-2-expansion-bundle-2025`.

A second, compounding problem: the reviewed resolution map (`config/greenmangaming-store-ids.yml` / `config/humblebundle-store-ids.yml`), which caches every interactive answer so re-runs don't re-prompt, is only written to disk *after* the final `GameList` write for that bundle succeeds (`cli.py`'s `on_offer` callbacks). Since `resolve_archive` fully completes — and therefore fully populates the in-memory mapping — before `on_offer` even runs, there's no reason the map write should be gated on the GameList write succeeding. In this exact log it was saved anyway only because a later bundle (`one-special-day-2025`) happened to succeed afterward and re-dumped the same shared mapping object; had it been the last bundle in the run, those answers would have been lost outright and every prompt re-asked next time.

Goal: reject a colliding name immediately at prompt time (with a clear message and a re-prompt, no lost session), and make already-resolved answers durable regardless of what happens afterward.

## Fix 1 — persist the resolution map before the final GameList write

In `src/game_collections/cli.py`, both `on_offer` callbacks currently write the map last:
- `scrape_humblebundle_command`'s `on_offer` (~cli.py:664-675): `write_resolution_map(resolution_map, mapping)` is the last line, after `write_humble_offer(...)`.
- `scrape_greenmangaming_command`'s `on_offer` (~cli.py:835-846): `write_gmg_resolution_map(resolution_map, mapping)` is likewise last, after `write_gmg_offer(...)`.

Reorder each so the resolution-map write happens **first**, immediately after `on_offer` is entered (the mapping is already fully resolved by the time `on_offer` runs — `resolve_archive` finished before `crawl_*_offers` calls it). Then write the offer/GameList files. This way a downstream validation failure while writing the final list no longer risks losing already-answered prompts.

## Fix 2 — reject duplicate names live, at prompt time

Thread an optional, mutable `known_names: set[str]` (casefolded game names already committed to the current bundle/list) through the chooser and both resolvers, so a name typed under "Multiple…" that collides with another name is rejected immediately instead of only failing at final `GameList` validation (`models.py:162-171`, `GameList.validate_games`).

### `src/game_collections/sources/prompting.py`

- `choose_store_candidate(...)`: add a keyword-only `known_names: set[str] | None = None`. In the existing "Multiple…" collection loop (lines ~94-106), before appending an accepted `name`, casefold it and check against both `known_names` and the names collected so far *in this same loop*. On a collision, `typer.echo` a clear rejection ("... is already used by another game in this list — enter a different name.", `err=True`) and loop back to prompt again instead of appending. On acceptance, if `known_names` is provided, add the casefolded name to it immediately (so later prompts — in this loop, or from a different item entirely — see it too).
- `collect_one_name(count, known_names=None)`: same idea for the interleaved path used by `humblebundle.resolver` — loop internally until a non-colliding name or a blank answer is returned; register accepted names into `known_names` before returning.

### `src/game_collections/sources/greenmangaming/resolver.py`

- `resolve_archive`: after computing `distinct`, seed `known_names = {item.title.casefold() for item in distinct}` and pass it through `resolve_item` → `_resolve_title`.
- `_resolve_title(title, stores, cache_key, mapping, known_names)`: since this same title (or a recursively-split sub-title) might be *replaced* by a split, `known_names.discard(title.casefold())` before the `for store_value in stores` loop (so accepting the Multiple default, which is `title` itself, doesn't immediately self-collide), and `known_names.add(title.casefold())` right before every "kept as one entry" return path (the cached-`existing` early return, and the final non-split `return [ResolvedGame(name=title, ...)]`). Pass `known_names` down into `self._choose(...)` and into the recursive `_resolve_title(sub_title, ..., known_names)` calls for split sub-titles, so nested Multiple splits and cross-item checks both work uniformly.
- Update the `CandidateChooser` type alias and the non-interactive lambda wired in `cli.py` (`lambda _title, _provider, _candidates: None` → accept `**_kwargs`, matching humble's already-flexible lambda) to tolerate the new keyword argument.

### `src/game_collections/sources/humblebundle/resolver.py`

- Mirror the same seed-and-thread pattern in `resolve_archive` and `_resolve_title` (interleaved variant): seed `known_names` from `distinct` item titles, discard/readd around the store loop, pass to `self._choose(..., known_names=known_names)` and to `self._collect_name(count, known_names)`, and thread it into the recursive `_resolve_title(name, ..., known_names=known_names)` call inside the `EnterMultiple` handling loop.
- Also register each auto-expanded Steam "Sub" app name (the `sub_apps` expansion path) into `known_names` as those `ResolvedGame`s are built, since that's the same "one item becomes many names" shape, just non-interactive.

### `src/game_collections/search.py` (`complete_game_list`, used by `game-collections complete`)

- Before the main per-game loop, seed `known_names` from every game's `name` in the draft list.
- Inside the loop, `known_names.discard(name.casefold())` before calling `resolve_title(...)`, and `known_names.add(name.casefold())` back at the end of the iteration whenever `split is None` (the entry stays under its own name whether or not it resolved). Thread `known_names` into `resolve_title(...)` the same way the resolvers do (no extra bookkeeping needed for the `split is not None` branch — the chooser already registers each accepted split name live).

### Type/signature fallout

`CandidateChooser` and `SearchChooser` type aliases, and every fake/stub chooser used in tests (grep for `choose_store_candidate`, `collect_one_name`, `CandidateChooser`, `SearchChooser`), need to accept the new optional `known_names` keyword. Prefer widening the callable type (e.g. a small `Protocol` with `known_names: set[str] | None = None`) over `Callable[[...], ...]`, since plain `Callable` typing can't express keyword-only params.

## Verification

- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_search.py tests/test_cli.py -q` and the greenmangaming/humblebundle resolver test modules (grep `tests/` for `resolver` and `prompting` to find exact filenames) — add/extend cases for: (a) typing the same name twice under one "Multiple…" split gets rejected and re-prompted rather than accepted; (b) typing a name that collides with a different item already in the same bundle/list gets rejected the same way; (c) resolution map is written even when the final `GameList` construction for that bundle raises (simulate a duplicate that still slips through, e.g. two originally-different crawled item titles that are identical, and assert the map file reflects the resolved answers regardless).
- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest` full suite.
- Manually skim `src/game_collections/sources/greenmangaming/crawler.py` write path once more to confirm the reordered `on_offer` still reports errors/unresolved counts identically (no behavior change there, just write order).
