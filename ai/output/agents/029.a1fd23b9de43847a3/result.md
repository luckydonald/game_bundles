This is unrelated to storefront candidate prompting (separate ITAD detail-page solver, not relevant to "Multiple…" feature). I have enough to answer fully.

## Report

### 1. The interactive prompt builder functions (full code)

The prompt UI is **not** in `resolver.py` — it lives in `cli.py` as plain `typer.echo`/`typer.prompt` calls (no `questionary`; that library isn't used anywhere in the repo). `resolver.py` only defines the `CandidateChooser` callback *type* that the prompt function must satisfy.

**`src/game_collections/cli.py:253-280`** — `_choose_store_candidate` (Humble Bundle path):
```python
def _choose_store_candidate(
    item: HumbleItem,
    provider: StoreName,
    candidates: list[StoreCandidate],
) -> str | None:
    typer.echo(f"Resolve {item.title!r} on {provider}:")
    for index, candidate in enumerate(candidates, start=1):
        typer.echo(f"  {index}. {candidate.title} — {candidate.qualified_id}")
        typer.echo(f"     {candidate.url}")
    # end for
    other = len(candidates) + 1
    typer.echo(f"  {other}. Other…")
    while True:
        selection = typer.prompt("Select a result", default=str(other))
        if selection.isdecimal() and 1 <= int(selection) <= len(candidates):
            return candidates[int(selection) - 1].qualified_id
        # end if
        if selection == str(other):
            manual = typer.prompt(
                "Paste the store URL or direct ID; leave blank for unresolved",
                default="",
                show_default=False,
            )
            return manual or None
        # end if
        typer.echo(f"Enter a number from 1 to {other}.", err=True)
    # end while
# end def _choose_store_candidate
```

**`src/game_collections/cli.py:283-297`** — `_choose_search_candidate` (used by `complete`, wraps the above by synthesizing a fake `HumbleItem`):
```python
def _choose_search_candidate(
    title: str,
    provider: StoreName,
    candidates: list[StoreCandidate],
) -> str | None:
    """Prompt for one storefront result while completing a draft list."""
    item = HumbleItem(
        machine_name="search",
        title=title,
        item_type="game",
        is_game=True,
        redeem_on=[provider],
    )
    return _choose_store_candidate(item, provider, candidates)
# end def _choose_search_candidate
```

**`src/game_collections/cli.py:669-696`** — `_choose_gmg_store_candidate` (Green Man Gaming): a **separately duplicated, byte-for-byte identical** copy of `_choose_store_candidate`, just typed against `GmgItem` instead of `HumbleItem`. There is no `_choose_gmg_search_candidate` wrapper — GMG's `complete`/`scrape` paths (around line 725-728) reuse `_choose_gmg_store_candidate` directly as the `choose` callback (it's called positionally as `(item_or_title, provider, candidates)`, and since `_choose_store_candidate`/`_choose_gmg_store_candidate` only use `item.title` via f-string, the fake-item wrapper pattern isn't even needed there — GMG's `complete` flow just passes GMG items directly, not titles).

The `"Other…"` option index is always `len(candidates) + 1`, printed as the **last** line, echoed once (`typer.echo(f"  {other}. Other…")`), and the `default=str(other)` makes pressing Enter select it.

### 2. Free-text "Other…" flow end-to-end

When the user types the value matching `other`'s index, `_choose_store_candidate`/`_choose_gmg_store_candidate` prompt again for `"Paste the store URL or direct ID; leave blank for unresolved"` and return that raw string (or `None` if left blank) — **it does not re-run search.py's ranked search**. The returned string is handled by the caller:

- In `StorefrontResolver.resolve_item` (`resolver.py:278-283`): `selected = self._choose(...)`; if not `None`, it's passed through `parse_store_identity(typed_provider, selected)` (imported from `sources.storefronts`) to turn a pasted URL or bare ID into a qualified `"steam:12345"`-style ID, then appended to `ids`.
- In `search.py`'s `resolve_title` (`search.py:117-121`): same — `selected = choose(...)`; if not `None`, `ids.append(parse_store_identity(provider, selected))`.

So "Other…" is a manual override that bypasses search entirely — it expects the user to paste a URL/ID for the *same title/provider* being resolved, not a different search term. It never calls back into `search.py`'s candidate-search loop (`resolver.search(provider, title)`); it's a dead-end leaf that either produces one ID or `None` (unresolved).

### 3. Sharing across `complete` and other sources

- **Humble Bundle**: `cli.py:444` — `complete_command` passes `_choose_search_candidate` into `complete_game_list(...)` (from `search.py`). `cli.py:531-535` — `scrape_humblebundle_command` passes `_choose_store_candidate` directly into `StorefrontResolver`.
- **Green Man Gaming**: `cli.py:725-728` — `scrape_greenmangaming_command` passes `_choose_gmg_store_candidate` into `GmgStorefrontResolver` (`sources/greenmangaming/resolver.py`). GMG has **no** `complete`-style integration with `search.py` — grep confirms `search.py` only imports from `humblebundle.resolver` (line 10-17) and `isthereanydeal.resolver` (line 18-22), not from `greenmangaming`. So `complete_game_list`/`resolve_title` in `search.py` are Humble/generic-storefront-only; GMG's own resolver is entirely separate and self-contained.
- **isthereanydeal**: Uses a completely different code path — `resolve_isthereanydeal_markers` / `resolve_game_with_aliases` (imported in `search.py:18-22`), driven by `itad_resolve: ItadResolve` (a plain `Callable[[str], ItadGameResolution]`), not the candidate-list/`choose` prompt pattern at all. No interactive prompt for ITAD.

So the prompt UI is **duplicated**, not shared: Humble and GMG each have their own copy in `cli.py` (`_choose_store_candidate` vs `_choose_gmg_store_candidate`), structurally identical, differing only in the item type annotation. `search.py`'s generic `resolve_title`/`complete_game_list` machinery is provider-agnostic and driven by the `SearchChooser` callable type (`search.py:28`), but only Humble's resolver/CLI path wires into it via `_choose_search_candidate`.

### 4. Return type / result structure

- `CandidateChooser` / `SearchChooser` signature: `(item_or_title, provider, candidates: list[StoreCandidate]) -> str | None`. Return value is either:
  - `None` → unresolved for that provider (no ID added; contributes to `unresolved_stores`/`failed`/`unresolved:` markers).
  - a pasted URL/ID string → resolved via `parse_store_identity` into one qualified ID string, appended to the `ids` list for that item/title.
- There is **no dedicated return type/enum** distinguishing "auto-resolved", "user picked from list", and "user typed custom" — all three collapse into the same `list[str]` of qualified IDs (or absence thereof) by the time they reach `resolve_item`/`resolve_title`. The prompt function itself is the only place that knows *how* the ID was obtained.
- In `search.py`'s `complete_game_list` (lines 200-208), the caller checks: `found = resolve_title(...)`; if truthy, ids are extended (`resolved_any = True`); if falsy (empty list, i.e., `choose` returned `None`), a synthetic marker `unresolved:store:{provider}:{marker_name}` is appended and `failed = True`. The per-game `unresolved` list (returned as second tuple element of `complete_game_list`) collects only *names*, not per-provider or per-choice detail.
- **No existing sentinel choices** beyond "Other…" — no "Skip", "None of these", enum, or `Literal` type marking special menu entries. The only "special" values in the codebase are ID-string prefixes used as unresolved markers: `unresolved:store:{provider}:{slug}` (`search.py:73`), `unresolved:source:humblebundle:{machine_name}` (`resolver.py:286`), and `unresolved:source:isthereanydeal:{...}` (`isthereanydeal/resolver.py:18`, `UNRESOLVED_PREFIX`). These are data-layer markers, not prompt-menu choices.

### 5. Existing "one offer → multiple output games" pattern?

**None exists.** Grepped `resolver.py` and `crawler.py` for `for offer`/`results.append`/`games.append`:

- `resolver.py`: `resolve_item(self, item: HumbleItem, mapping) -> list[str]` (line 249) returns a `list[str]` of **storefront IDs for one item** (e.g., both a Steam and GOG ID for the same game across different `redeem_on` stores) — it is *never* a list of separate games. `resolve_archive` (line 292) builds a `resolved: dict[str, list[str]]` keyed one-to-one by `item.machine_name`.
- `crawler.py:293` and `crawler.py:331`: `pool_games.append(Game(name=item.title, ids=item.resolution.ids))` / `games.append(Game(name=item.title, ids=item.resolution.ids))` — strictly one `Game` per `HumbleItem`, deduplicated by `seen_pool_ids`/`seen_ids` (sets of already-seen qualified IDs), never split into multiple `Game` entries from one item.

So today, one Humble "offer"/item always maps to exactly one `Game` in the output `games:` list (with potentially multiple storefront IDs inside that single game's `ids` list). Introducing a "Multiple…" prompt option that lets one title resolve into several separate `Game` entries would be new functionality — there's no existing loop shape to extend for that; `resolve_item`'s `-> list[str]` return type and the `Game(name=item.title, ids=...)` call sites in `crawler.py` would need to become one-to-many rather than one-to-one.