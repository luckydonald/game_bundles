# Bundle-in-bundle DLC packs (Humble) + generalized "Multiple…" resolution

## Context

Humble bundle pages sometimes bundle a "DLC Pack" as a single tier item that
actually represents several separate DLCs for one (often free) base game —
e.g. in the `love-letter-to-lovecraft` bundle, "Dagon: By H.P. Lovecraft DLC
Pack" bundles 3 DLCs and requires the free base game, linked from the item's
description. Today the crawler/resolver/model stack treats every Humble tier
item as exactly **one** output `Game`, so a DLC pack collapses into one
mis-named, unresolvable entry, and there's no way to record that a DLC
requires its (often free, not separately bundled) base game.

This also exposed a related gap in the interactive resolution prompt
(`cli.py`'s candidate chooser): it only ever offers "pick a numbered
candidate" or "Other…" (paste a URL/ID for the *same* title). There is no
escape hatch for "this one candidate list is actually several separate
games", which is the general form of the DLC-pack problem and should be
available whenever resolving any title, not just Humble DLC packs.

Finally, a DLC's ownership can't always be checked the same way its base game
is: the manually-curated `--source collection` ownership source cannot
practically enumerate DLC app IDs the way it enumerates base games, and it's
unverified whether the Steam Web API (`GetOwnedGames`) surfaces owned DLC app
IDs at all. That needs a live check against real API responses before any
code decides how `web`-source ownership treats DLC — guessing here would
violate this repo's established "verify, don't guess external shapes"
practice.

## Execution shape

This plan has two stages, run as **two separate execution passes** with a
return to plan mode in between:

- **Stage 0 (run now, then return to plan mode):** a live investigation spike
  against the real Steam Web API and Steam Store API to determine DLC
  ownership/parent-detection semantics. No production code changes.
- **Stage 1 (planned in detail below, refined after Stage 0's findings if
  needed):** the actual model/parser/resolver/CLI changes.

---

## Stage 0 — Steam DLC ownership investigation (execute first)

Goal: answer, with real HTTP responses (not assumptions), for a real Steam
account and a real DLC app ID the user provides:

1. Does `IPlayerService/GetOwnedGames` (`src/game_collections/launchers/steam/api.py`,
   `SteamApiClient`) include an owned DLC's app ID in its `response.games[]`
   array, alongside/like a base game? Try with and without
   `include_appinfo`/`include_free_sub`/`include_extended_appinfo` variations
   if the plain call doesn't show it.
2. Does the public Steam Store endpoint `https://store.steampowered.com/api/appdetails?appids=<id>`
   (not currently used anywhere in this repo) return, for a known DLC app ID,
   a `type: "dlc"` field and a `fullgame.appid` pointing at the base game? Try
   it for both a DLC the user owns and one they don't, to see if ownership
   affects the response at all (it shouldn't — this is a catalog endpoint,
   not an ownership endpoint).
3. Write up findings in the conversation (not committed to the repo) covering:
   whether `web`-source ownership (`owned_app_ids_from_api`,
   `src/game_collections/launchers/steam/adapter.py`) already "just works"
   for DLC, needs a different API call, or can't detect DLC ownership at all
   — and whether `appdetails` is a viable, reliable source for base-game
   parent-detection to complement/replace Humble's own base-game link.

Do not write any production code in this stage. After reporting findings,
return to plan mode to fold the answer into (or adjust) Stage 1 below —
particularly the "`web`-source DLC ownership" open question left there.

---

## Stage 1 — Model, crawl, resolve, and prompt changes

### 1. Launcher-neutral model (`src/game_collections/models.py`)

Add a `requires` field to `Game` (`models.py:63-87`), parallel to the existing
`ids`/`group` fields:

```python
requires: list[NonEmptyString] = Field(default_factory=list)
```

Semantics: qualified IDs of other games that must be owned/present for this
entry to make sense — today's only producer is "the free base game a DLC
needs". No launcher-specific behavior belongs here (per this repo's
launcher-neutral list-loading rule) — it's just data, same as `ids`.

Reuse the **existing, already-validated but currently unused** `GameGroup`
model (`models.py:54-60`, wired into `GameList.validate_games`,
`models.py:137-148`) as the provenance link for games split out of one
compound Humble offer — this is exactly what it was built for; no model
changes needed there.

### 2. Humble parser — structured DLC-pack extraction

`src/game_collections/sources/humblebundle/models.py` — add to `HumbleItem`:
- `base_game_url: HttpUrl | None = None`
- `bundled_dlc_names: list[NonEmptyString] = Field(default_factory=list)`

`src/game_collections/sources/humblebundle/parser.py`, `_bundle_item`
(`parser.py:251-258` area) — before/alongside the existing `_markdown()` call
on `raw.get("description_text")`, add a small helper (e.g.
`_parse_dlc_pack_details(html: str) -> tuple[str | None, list[str]]`) that,
on the raw HTML (not the markdownified text), extracts:
- the first `<a href="...">` inside the description whose href matches a
  known storefront app-URL shape (start with Steam's
  `store.steampowered.com/app/<id>/...`, matching the pattern already handled
  in `sources/storefronts.py`'s `parse_store_identity`) → `base_game_url`.
- the `<li>` text items of the first `<ul>` in the description → `bundled_dlc_names`.

This should run for every item (cheap, harmless if it finds nothing) rather
than gating strictly on `cta_badge.badge == "dlc"` — the existing `cta_badge`
handling (`parser.py:253-256`) already tags such items `"Dlc"` in
`HumbleItem.tags`, which the resolver will use as the primary trigger; the
raw-HTML link/list extraction is what turns "we know it's a DLC pack" into
"we know what it's for and what's inside".

### 3. Resolver — auto-split + base-game auto-resolve

`src/game_collections/sources/humblebundle/resolver.py`:

- Introduce a small `ResolvedGame` model (name, ids, requires) so
  `resolve_item`/`resolve_archive` can return **one or more** named results
  per `HumbleItem` instead of the current 1:1 `list[str]` of IDs
  (`resolve_item`, `resolver.py:249-282`; `resolve_archive`,
  `resolver.py:292-`).
- If `item.base_game_url` is set, resolve it deterministically via
  `parse_store_identity("steam", item.base_game_url)` — no search/prompt
  needed, it's already a direct storefront URL — and attach it as
  `requires=[base_id]` on every `ResolvedGame` this item produces.
- If `item.bundled_dlc_names` is non-empty ("Dlc" tag + parsed list), auto-split:
  for each sub-name, run the same per-title search+choose logic `resolve_item`
  already does for a single title (extract that inner loop into a reusable
  helper), producing one `ResolvedGame` per sub-name, each tagged with
  `group=GameGroup(id=item.machine_name, name=item.title)` and the shared
  `requires`.
- `HumbleResolutionMap` (durable cache) needs to store split results per
  machine_name (e.g. a `splits: dict[str, list[ResolvedGame]]` alongside the
  existing `games: dict[str, list[str]]`), so re-running `scrape` doesn't
  re-prompt for already-resolved splits.

`src/game_collections/sources/humblebundle/crawler.py` — the `Game(name=item.title,
ids=item.resolution.ids)` construction sites (`crawler.py:293` and `~331`, plus
the choice-pool variant) become: for each `ResolvedGame` produced for that
item, emit `Game(name=resolved.name, ids=resolved.ids, requires=resolved.requires,
group=resolved.group)`.

### 4. CLI prompt — merge the duplicated choosers, add "Multiple…"

`_choose_store_candidate` (`cli.py:253-280`) and `_choose_gmg_store_candidate`
(`cli.py:669-696`) are byte-for-byte identical except for the item type, and
both only ever use `item.title`. Extract one shared implementation into a new
module, e.g. `src/game_collections/sources/prompting.py` (new, small, reusable
concern — not bolted onto `cli.py`), taking `title: str` directly instead of
an item:

```python
def choose_store_candidate(title: str, provider: StoreName, candidates: list[StoreCandidate]) -> ChosenCandidate: ...
```

Define the discriminated result type in the same module:

```python
class ChosenNames(StrictModel):
    names: list[NonEmptyString]

ChosenCandidate = str | ChosenNames | None
```

Menu layout becomes:
```
  1. <candidate 1>
  2. <candidate 2>
  N. Multiple…
  N+1. Other…
```
Selecting "Multiple…" loops: prompt for a name (first prompt's `default` is
the title just searched, per the request; subsequent prompts default blank
to finish), collecting into `ChosenNames(names=[...])`.

Callers (`resolver.py`'s `resolve_item`/reusable single-title helper,
`greenmangaming/resolver.py`'s equivalent, and `search.py`'s `resolve_title`)
special-case a `ChosenNames` result: instead of appending one ID, recursively
run the *normal* search+resolve flow for each name in `names` (i.e., not just
paste-a-URL — actually re-search, per "try to resolve on its own as usual
first"), producing multiple `ResolvedGame`/qualified-ID results tied together
by a shared `GameGroup`.

`cli.py:283-297`'s `_choose_search_candidate` (the fake-`HumbleItem`-wrapper
used by `complete`) is deleted — callers just pass `title` straight into the
shared `choose_store_candidate` now that it no longer needs an item.

`greenmangaming/resolver.py` and `search.py`'s `resolve_title`/
`complete_game_list` get the same `ChosenNames` handling so `complete` and
GMG scraping both gain the "Multiple…" escape hatch too (this is the "merge
properly" outcome — one chooser, all three call sites benefit, not a
Humble-only bolt-on).

### 5. Ownership: `--source collection` reduces DLC checks to the base game

Per explicit direction: a manually-curated Steam collection can't practically
be expected to separately list a DLC's own app ID, so for the `collection`
ownership source specifically, a `Game` with a non-empty `requires` should be
considered checked-for-ownership via its `requires` IDs (the base game)
rather than its own `ids`. This is the natural place to look:
`src/game_collections/completion.py`'s `evaluate_completion` (currently a
flat `ids`-vs-`owned_app_ids` set check, `completion.py:29-98`) and/or
`src/game_collections/launchers/steam/adapter.py`'s
`owned_app_ids_from_collection` consumer — the exact touch point depends on
whether the source is visible at `evaluate_completion` call time; if not,
thread an `ownership_source` flag through or special-case at the
`SteamAdapter.evaluate()` call site instead.

`web`-source (`owned_app_ids_from_api`) and `installed`-source
(`owned_app_ids_from_installed`) DLC handling stay as their natural
DLC-appid check for now — Stage 0's findings determine whether `web` needs
special handling (e.g. if `GetOwnedGames` doesn't surface DLC IDs at all, it
may need the same `requires`-reduction as `collection`, or a different API
call entirely). Do not guess this — implement per Stage 0's actual findings.

## Verification

- `uv run pytest` — especially any existing `tests/test_schema.py`, Humble
  parser/resolver/crawler tests, and `completion.py`/adapter tests; add
  fixtures using the real captured DLC-pack HTML already found in
  `archives/humblebundle/bundle/2026-08-12_handsome-husbandos/source.json`
  (`ourlife_beginningsandalways_dlcpack`, `adatewithdeathdeluxedlcpack`) as
  parser test input — these are real, already-archived examples, not
  invented ones.
- Regenerate `schemas/game-list.schema.json` and
  `schemas/humblebundle-archive.schema.json` after the model changes
  (`uv run game-collections schema`); `tests/test_schema.py` will catch drift
  if this is skipped.
- Manually re-run `scrape humblebundle` (non-`--git`, dry local run) against
  the `love-letter-to-lovecraft` bundle (or `handsome-husbandos`) and confirm
  the Dagon/Our Life/Date with Death DLC packs now resolve into multiple
  named `Game` entries sharing a `group`, each with `requires` pointing at
  the base game.
- Manually exercise the new "Multiple…" prompt path via `complete` on a
  sample draft list to confirm it re-searches each typed name normally and
  produces separate, correctly grouped games.
