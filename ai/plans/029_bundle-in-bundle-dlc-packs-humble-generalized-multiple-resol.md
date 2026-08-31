# Bundle-in-bundle DLC packs (Humble) + generalized "Multiple…" resolution

## Context

Humble bundle pages sometimes bundle a "DLC Pack" as a single tier item that actually represents several separate DLCs for one (often free) base game — e.g. in the `love-letter-to-lovecraft` bundle, "Dagon: By H.P. Lovecraft DLC Pack" bundles 3 DLCs and requires the free base game, linked from the item's description. Today the crawler/resolver/model stack treats every Humble tier item as exactly **one** output `Game`, so a DLC pack collapses into one mis-named, unresolvable entry, and there's no way to record that a DLC requires its (often free, not separately bundled) base game.

This also exposed a related gap in the interactive resolution prompt (`cli.py`'s candidate chooser): it only ever offers "pick a numbered candidate" or "Other…" (paste a URL/ID for the *same* title). There is no escape hatch for "this one candidate list is actually several separate games", which is the general form of the DLC-pack problem and should be available whenever resolving any title, not just Humble DLC packs.

Finally, a DLC's ownership can't always be checked the same way its base game is: the manually-curated `--source collection` ownership source cannot practically enumerate DLC app IDs the way it enumerates base games, and it's unverified whether the Steam Web API (`GetOwnedGames`) surfaces owned DLC app IDs at all. That needs a live check against real API responses before any code decides how `api`-source ownership treats DLC — guessing here would violate this repo's established "verify, don't guess external shapes" practice.

## Execution shape

This plan had two stages; Stage 0 is now complete (findings below), Stage 1 is refined accordingly and ready to execute:

- **Stage 0 (done):** a live investigation spike against the real Steam Web API and Steam Store API to determine DLC ownership/parent-detection semantics.
- **Stage 1 (below):** the actual model/parser/resolver/CLI changes.

---

## Stage 0 — Steam DLC ownership investigation (complete)

Executed against the real account (SteamID64 `76561198044975919`, discovered via the existing `SteamFileGateway.discover()` — no manual input needed) and its live 1283-game `GetOwnedGames` response:

1. **`GetOwnedGames` does not surface owned DLC as separate entries.** Cross-checked a 321-game sample spread across the whole owned-games list against Steam's Store `appdetails` catalog endpoint: **zero** were `type: "dlc"`. This matches Valve's documented behavior — `IPlayerService/GetOwnedGames` returns only base products, never DLC app IDs, regardless of `include_appinfo`/`include_played_free_games`. So `api`-source ownership (`owned_app_ids_from_api`) fundamentally **cannot** detect DLC ownership by checking a DLC's own app ID against `owned_app_ids` — that check will (almost) always report "missing" for a DLC, owned or not.
2. **Store `appdetails` reliably exposes DLC/parent metadata**, independent of ownership (it's a public catalog endpoint, not an ownership check). Verified live: `GET https://store.steampowered.com/api/appdetails?appids=227310` (Euro Truck Simulator 2 – Going East!, a real DLC not owned by this account) returned `type: "dlc"` and `fullgame: {"appid": "227300", "name": "Euro Truck Simulator 2"}`. This is a viable, reliable source for base-game parent-detection, but it never confirms ownership of anything.
3. **Bonus finding, fixed in-session (not part of Stage 1 scope, already applied):** `SteamApiClient.get_owned_games()` was actually broken against the live API — Steam now returns a `has_leaderboards` boolean per game that `OwnedGame` (a `StrictModel`) rejected as an extra field, so `sync steam --source api` currently fails end-to-end for every account. Fixed by adding `has_leaderboards: StrictBool | None = None` to `OwnedGame` in `src/game_collections/launchers/steam/models.py:244`; re-verified live parsing succeeds (1283/1283 games) after the fix.

**Conclusion for Stage 1 §5:** since `GetOwnedGames` never returns DLC app IDs at all, `api`-source ownership needs the *same* `requires`-reduction as `collection`-source, not different handling — this isn't a `collection`-only special case, it's how every ownership source that goes through `GetOwnedGames` must treat a `requires`-carrying `Game`. Section 5 below is updated accordingly. `installed`-source is left as-is (its incidental appmanifest-based DLC detection, per prior exploration, actually can see real installed DLC app IDs — no reduction needed there, though nothing stops it from also falling back to `requires` if the DLC's own appid isn't found).

**Follow-up verification (same conclusion, now with a concrete known-owned DLC, not just a sample):** using the account's real Fallout 4 ownership (base game app ID `377160`, owned) and its "High Resolution Texture Pack" DLC (app ID `540810`, also owned) as a live test case:

- `GetOwnedGames`, even called with `appids_filter` explicitly restricted to `[540810, 377160]`, returned **only** `377160` (Fallout 4) — `540810` is silently dropped despite being owned. No parameter combination surfaces it; this is conclusive, not a sampling artifact.
- `appdetails?appids=377160` (the **base game's own** page) returns a public `dlc` field: `[3868650, 598110, 540810, 404090, 435881, 480631, 480630, 490650, 435880, 435870]` — the complete, authoritative list of every DLC app ID for that game, straight from Valve's catalog, no ownership check involved. This is a better source for "all DLCs of a game" than parsing Humble's own description HTML: it's exhaustive and independent of whatever a bundle page happens to mention.
- There is no public per-account "list all DLC I own" or "do I own DLC X" endpoint. The closest official mechanism, `ISteamUser/CheckAppOwnership`, requires a **publisher** API key scoped to that specific app — not usable by a hobbyist client against arbitrary third-party games. So `requires` (base-game) fallback isn't just the pragmatic choice, it's the *only* ownership signal available through the Web API for a DLC, short of the `installed`-source's incidental local appmanifest check.
- Bonus use for `appdetails`'s `dlc` list: once a Humble DLC-pack item's `base_game_url` resolves to a base-game app ID, that same `appdetails` call can cross-check/validate the parsed `bundled_dlc_names` count against the base game's real DLC count as a sanity check — optional, not required for Stage 1's core functionality.

**Superseding finding: a real, precise DLC-ownership source does exist.** Per a Reddit lead the user supplied (`r/Steam` thread on this exact question) plus a real dump the user exported and provided (`ai/references/https/store.steampowered.com/dynamicstore/userdata/_.json`): the logged-in store endpoint `https://store.steampowered.com/dynamicstore/userdata` returns `rgOwnedApps` — a flat list of **every** owned app ID, DLC included, unlike the public `GetOwnedGames` Web API. Verified against the user's real dump: `rgOwnedApps` has 2322 entries (vs. 1283 from `GetOwnedGames`), and both `377160` (Fallout 4) and `540810` (its "High Resolution Texture Pack" DLC, confirmed owned by the user) are present. This is exactly what Steam's own store frontend uses to render "in library" badges — DLC included.

The catch: this endpoint requires an authenticated **browser session** (Steam login cookies), not the `STEAM_WEB_API_KEY` the repo already uses — it's not part of the public Web API at all. Per explicit direction, this plan does **not** attempt live cookie-based fetching or a scripted Steam login flow (this repo's Steam safety invariants treat login-adjacent flows carefully, and a session cookie is a more sensitive, shorter-lived credential than an API key). Instead: the user periodically exports this JSON themselves (logged into steampowered.com, browser or `curl` with their cookie) to a local file, the same way they just did for this investigation, and the tool reads that file as an ownership source. This mirrors the existing `config/apply-selection.yml` convention (gitignored path, `config/README.md` and the private `config-git/` repo the user hard-links `config/apply-selection.yml` into for their own history) — the dump should live at a similar gitignored `config/` path.

**Revised conclusion for Stage 1 §5:** add a **fourth ownership source**, `dynamicstore`, alongside `api`/`installed`/`collection` — reads the user-exported dump and returns `set(rgOwnedApps)` directly, no `requires` reduction needed since DLC app IDs are genuinely present. This is the best available source (most complete, includes DLC natively) when the user keeps it exported, but it's additive, not a replacement: `--source api` (the `STEAM_WEB_API_KEY` path) stays exactly as it is today, unchanged, for users/automation (e.g. CI) without a manual dump — it just keeps the `requires`-based base-game fallback designed above for DLC, since it genuinely can't see DLC on its own. Same for `collection`. `dynamicstore` is simply the precise option when the user has it; nothing about `api` is removed or deprioritized by default (CLI default `--source` stays as it is today) — the user picks `dynamicstore` explicitly when they want the more accurate answer.

---

## Stage 1 — Model, crawl, resolve, and prompt changes

### 1. Launcher-neutral model (`src/game_collections/models.py`)

Add a `requires` field to `Game` (`models.py:63-87`), parallel to the existing `ids`/`group` fields:

```python
requires: list[NonEmptyString] = Field(default_factory=list)
```

Semantics: qualified IDs of other games that must be owned/present for this entry to make sense — today's only producer is "the free base game a DLC needs". No launcher-specific behavior belongs here (per this repo's launcher-neutral list-loading rule) — it's just data, same as `ids`.

Reuse the **existing, already-validated but currently unused** `GameGroup` model (`models.py:54-60`, wired into `GameList.validate_games`, `models.py:137-148`) as the provenance link for games split out of one compound Humble offer — this is exactly what it was built for; no model changes needed there.

### 2. Humble parser — structured DLC-pack extraction

`src/game_collections/sources/humblebundle/models.py` — add to `HumbleItem`:

- `base_game_url: HttpUrl | None = None`
- `bundled_dlc_names: list[NonEmptyString] = Field(default_factory=list)`

`src/game_collections/sources/humblebundle/parser.py`, `_bundle_item` (`parser.py:251-258` area) — before/alongside the existing `_markdown()` call on `raw.get("description_text")`, add a small helper (e.g. `_parse_dlc_pack_details(html: str) -> tuple[str | None, list[str]]`) that, on the raw HTML (not the markdownified text), extracts:

- the first `<a href="...">` inside the description whose href matches a known storefront app-URL shape (start with Steam's `store.steampowered.com/app/<id>/...`, matching the pattern already handled in `sources/storefronts.py`'s `parse_store_identity`) → `base_game_url`.
- the `<li>` text items of the first `<ul>` in the description → `bundled_dlc_names`.

This should run for every item (cheap, harmless if it finds nothing) rather than gating strictly on `cta_badge.badge == "dlc"` — the existing `cta_badge` handling (`parser.py:253-256`) already tags such items `"Dlc"` in `HumbleItem.tags`, which the resolver will use as the primary trigger; the raw-HTML link/list extraction is what turns "we know it's a DLC pack" into "we know what it's for and what's inside".

### 3. Resolver — auto-split + base-game auto-resolve

`src/game_collections/sources/humblebundle/resolver.py`:

- Introduce a small `ResolvedGame` model (name, ids, requires) so `resolve_item`/`resolve_archive` can return **one or more** named results per `HumbleItem` instead of the current 1:1 `list[str]` of IDs (`resolve_item`, `resolver.py:249-282`; `resolve_archive`, `resolver.py:292-`).
- If `item.base_game_url` is set, resolve it deterministically via `parse_store_identity("steam", item.base_game_url)` — no search/prompt needed, it's already a direct storefront URL — and attach it as `requires=[base_id]` on every `ResolvedGame` this item produces.
- If `item.bundled_dlc_names` is non-empty ("Dlc" tag + parsed list), auto-split: for each sub-name, run the same per-title search+choose logic `resolve_item` already does for a single title (extract that inner loop into a reusable helper), producing one `ResolvedGame` per sub-name, each tagged with `group=GameGroup(id=item.machine_name, name=item.title)` and the shared `requires`.
- `HumbleResolutionMap` (durable cache) needs to store split results per machine_name (e.g. a `splits: dict[str, list[ResolvedGame]]` alongside the existing `games: dict[str, list[str]]`), so re-running `scrape` doesn't re-prompt for already-resolved splits.

`src/game_collections/sources/humblebundle/crawler.py` — the `Game(name=item.title, ids=item.resolution.ids)` construction sites (`crawler.py:293` and `~331`, plus the choice-pool variant) become: for each `ResolvedGame` produced for that item, emit `Game(name=resolved.name, ids=resolved.ids, requires=resolved.requires, group=resolved.group)`.

### 4. CLI prompt — merge the duplicated choosers, add "Multiple…"

`_choose_store_candidate` (`cli.py:253-280`) and `_choose_gmg_store_candidate` (`cli.py:669-696`) are byte-for-byte identical except for the item type, and both only ever use `item.title`. Extract one shared implementation into a new module, e.g. `src/game_collections/sources/prompting.py` (new, small, reusable concern — not bolted onto `cli.py`), taking `title: str` directly instead of an item:

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

Selecting "Multiple…" loops: prompt for a name (first prompt's `default` is the title just searched, per the request; subsequent prompts default blank to finish), collecting into `ChosenNames(names=[...])`.

Callers (`resolver.py`'s `resolve_item`/reusable single-title helper, `greenmangaming/resolver.py`'s equivalent, and `search.py`'s `resolve_title`) special-case a `ChosenNames` result: instead of appending one ID, recursively run the *normal* search+resolve flow for each name in `names` (i.e., not just paste-a-URL — actually re-search, per "try to resolve on its own as usual first"), producing multiple `ResolvedGame`/qualified-ID results tied together by a shared `GameGroup`.

`cli.py:283-297`'s `_choose_search_candidate` (the fake-`HumbleItem`-wrapper used by `complete`) is deleted — callers just pass `title` straight into the shared `choose_store_candidate` now that it no longer needs an item.

`greenmangaming/resolver.py` and `search.py`'s `resolve_title`/`complete_game_list` get the same `ChosenNames` handling so `complete` and GMG scraping both gain the "Multiple…" escape hatch too (this is the "merge properly" outcome — one chooser, all three call sites benefit, not a Humble-only bolt-on).

### 5. Ownership: `api` and `collection` sources reduce DLC checks to the base game

Confirmed by Stage 0: `GetOwnedGames` never returns DLC app IDs, so checking a DLC's own `ids` against `owned_app_ids` from **either** the `api` source (`owned_app_ids_from_api`) or the `collection` source (`owned_app_ids_from_collection`, which a human curates by hand and can't be expected to separately list a DLC's own app ID either) will practically never report a DLC as owned. For both of these sources, a `Game` with a non-empty `requires` should be considered checked-for-ownership via its `requires` IDs (the base game) instead of/in addition to its own `ids`.

Touch point: `src/game_collections/completion.py`'s `evaluate_completion` (currently a flat `ids`-vs-`owned_app_ids` set check, `completion.py:29-98`) and/or `src/game_collections/launchers/steam/adapter.py`'s `SteamAdapter.evaluate()` call site — the exact spot depends on whether the active ownership source is visible at `evaluate_completion` call time; if not, thread an `ownership_source` flag through, or special-case in `adapter.py` before calling `evaluate_completion`. Suggested rule: a `Game` is "owned" for these two sources if `ids ∩ owned_app_ids` is non-empty **or** (when `requires` is non-empty) `requires ∩ owned_app_ids` is non-empty — the DLC's own ID stays checked first since it's harmless and future-proof (e.g. if Valve ever changes `GetOwnedGames`' behavior), `requires` is the practical fallback that actually fires today.

`installed`-source (`owned_app_ids_from_installed`) is left as its natural DLC-appid check — per prior exploration, Steam does write real `appmanifest_<dlc_id>.acf` files for installed DLC, so the appid can actually appear there. No reduction strictly needed, though it's harmless to apply the same `requires`-fallback rule uniformly across all three sources for consistency rather than special-casing two of three — recommend doing it uniformly in `evaluate_completion` rather than per-source.

### 6. New `dynamicstore` ownership source, slotted into the existing `auto` mode

The CLI already has exactly the "auto-detect and use whichever source is available" mechanism requested: `--source` (`cli.py:1082` and siblings) accepts `auto | api | collection | installed | none`, and `_steam_adapter`'s `auto` branch (`cli.py:999-1013`) tries `("api", "collection", "installed")` in order, catching `(OSError, ValueError, RuntimeError, SteamIoError)` per candidate and using the first one that succeeds. This is the pattern to extend, not a new mechanism to invent.

- Add `"dynamicstore"` as a fifth valid `--source` value (the `if source not in (...)` check at `cli.py:917` and the three `Annotated[str, typer.Option("--source", ...)]` help strings at `cli.py:1082/1142/1238`) and a new branch in `adapter_for_source` (`cli.py:936-`) that reads the local dump file and raises `OSError`/`FileNotFoundError` (already caught by the `auto` loop) when it's missing or stale beyond some threshold, so `auto` mode naturally skips it when absent.
- Per explicit direction ("this one is the best possible source"), prepend it to the `auto` priority order: `("dynamicstore", "api", "collection", "installed")` at `cli.py:1001` — `dynamicstore` wins whenever the dump file exists and validates, falling through to `api` otherwise. `--source api`/`STEAM_WEB_API_KEY` stays completely unchanged as its own explicit choice and as the first automatic fallback; nothing about it is removed or deprioritized when explicitly selected.
- Dump file location: a conventional gitignored path, e.g. `config/steam-dynamicstore-dump.json`, mirroring the existing `config/apply-selection.yml` convention — already gitignored at `.gitignore:974`, and already hard-linked into the user's private `config-git/` repo per `config-git/README.md` for their own history/backup; the user can do the same for this new file if they want it versioned privately. An optional `--dynamicstore-dump PATH` override, matching the existing `--steam-root`/`--lists-root` override style.
- New strict Pydantic model for the dump's envelope (new file, e.g. `src/game_collections/launchers/steam/dynamicstore.py`), storing both the fetch timestamp and the raw payload (see §7 for why): `DynamicStoreDumpFile(fetched_at: datetime, data: SteamDynamicStoreUserData)`. `SteamDynamicStoreUserData` follows the existing `StrictModel`/`extra=forbid` convention used throughout `launchers/steam/models.py` and every `sources/*/models.py` — this repo treats unmodeled external fields as errors deliberately, per `OwnedGamesPayload`/`GetOwnedGamesResponse` and the `has_leaderboards` lesson from Stage 0. The real dump has ~29 top-level keys (observed: `rgWishlist`, `rgOwnedPackages`, `rgOwnedApps`, `rgFollowedApps`, `rgMasterSubApps`, `rgPackagesInCart`, `rgAppsInCart`, `rgRecommendedTags`, `rgIgnoredApps`, `rgIgnoredPackages`, `rgHardwareUsed`, `rgCurators`, `rgCuratorsIgnored`, `rgCurations`, `bShowFilteredUserReviewScores`, `rgCreatorsFollowed`, `rgCreatorsIgnored`, `rgExcludedTags`, `rgExcludedContentDescriptorIDs`, `rgAutoGrantApps`, `rgRecommendedApps`, `rgPreferredPlatforms`, `rgPrimaryLanguage`, `rgSecondaryLanguages`, `bAllowAppImpressions`, `nCartLineItemCount`, `nRemainingCartDiscount`, `nTotalCartDiscount`); only `rgOwnedApps: list[int]` is actually consumed, but every other key needs a best-effort type so validation still catches real format drift rather than silently ignoring it.
- New ownership-source function, e.g. `owned_app_ids_from_dynamicstore(path: Path) -> set[int]` (`launchers/steam/adapter.py`, alongside `owned_app_ids_from_api`/`_from_installed`/`_from_collection`) that loads and validates the envelope file, returning `set(payload.data.rgOwnedApps)` directly — **no** `requires` reduction needed for this source, since real DLC app IDs are genuinely present (unlike `api`/`collection`).

### 7. Refresh-prompt UX: open Steam to the dump page, paste, save with a timestamp

Per explicit direction: both the TUI (`apply steam`) and CLI (`sync steam`) should be able to prompt the user to paste a fresh copy of the dump, opening the Steam client to the right page for convenience, and default to skipping so repeated runs stay fast.

- **Opening Steam to a URL is already solved in this repo.** `apply/tui.py:34-43` has `_open_url(url)`, which hands a `steam://...` URI off to the OS handler (`open` on macOS, `os.startfile` on Windows, `xdg-open` elsewhere) — already used for `steam://rungameid/{appid}` deep links (`apply/tui.py:972`). Steam's client supports `steam://openurl/<url>` to open that URL in its embedded browser (already logged in, so copy-paste is immediate) — reuse `_open_url("steam://openurl/https://store.steampowered.com/dynamicstore/userdata")` for this. `_open_url` should move out of `apply/tui.py` into a small shared module (e.g. alongside the new `dynamicstore.py`, or a tiny `os_open.py`) so both the TUI and the plain-CLI refresh flow can call the same function — `apply/tui.py` then imports it instead of keeping its own copy.
- **Shared core logic**, e.g. `maybe_refresh_dynamicstore_dump(path: Path, *, force: bool | None, interactive: bool) -> None`: `force=True` always prompts (even outside a detected interactive session); `force=False` never prompts (silent skip, for CI/automation); `force=None` (default) prompts only when `interactive` is true (a real TTY). When it existing, show the dump's `fetched_at` (from the envelope model in §6) as an absolute + relative timestamp ("Last updated: 2026-08-15 14:32 UTC (16 days ago)"). Default answer (bare Enter) is always "skip, don't update" — the fast path for repeated runs.
- **CLI path** (`sync steam`/`apply steam` non-TUI entry): a plain terminal prompt (`typer.confirm`-style, defaulting to `False`/skip) using `os.isatty`/similar for the `interactive` detection; if the user confirms, call `_open_url(...)`, then read pasted input via `sys.stdin` (paste followed by Enter+EOF, i.e. the same multi-line-paste-then-Ctrl-D pattern already good enough for terminal pasting — no new dependency needed), validate it against `SteamDynamicStoreUserData`, and on success atomically write the envelope (via the existing `atomic_write` helper in `sources/common.py`) with a fresh `fetched_at`. `Ctrl-C` during the paste wait cancels cleanly (caught, falls back to the existing dump untouched) rather than crashing the whole command.
- **New CLI flags**: a tri-state pair, e.g. `--refresh-dynamicstore/--no-refresh-dynamicstore` (`Annotated[bool | None, typer.Option(...)] = None`), matching `force` above — unset is the auto/interactive-only default, `--refresh-dynamicstore` forces the prompt even in a non-interactive shell (e.g. a script that pipes a paste in), `--no-refresh-dynamicstore` guarantees no prompt ever fires (safe for CI/cron).
- **TUI path** (`apply/tui.py`): on startup, a modal/dialog (Textual `Screen` or `ModalScreen`) asking the same yes/no question with the same timestamp display and the same default-to-skip behavior (Enter/Escape dismisses without changes) — "yes" triggers `_open_url(...)` then swaps to a paste screen (a `TextArea` widget accepting multi-line paste, with explicit Confirm/Cancel buttons — Cancel or Escape aborts without touching the file), validates and writes the same way as the CLI path.

## Verification

- Validate the new `dynamicstore` dump model against the user's real reference file at `ai/references/https/store.steampowered.com/dynamicstore/userdata/_.json` (2322 `rgOwnedApps` entries) and confirm `owned_app_ids_from_dynamicstore` returns a set containing both `377160` (Fallout 4) and `540810` (its owned "High Resolution Texture Pack" DLC).
- The `has_leaderboards` fix to `OwnedGame` (Stage 0, already applied) needs a regression test asserting `GetOwnedGamesResponse` parses a payload containing that field — add one near existing `steam/models.py`/`api.py` tests if none currently cover this shape.
- `uv run pytest` — especially any existing `tests/test_schema.py`, Humble parser/resolver/crawler tests, and `completion.py`/adapter tests; add fixtures using the real captured DLC-pack HTML already found in `archives/humblebundle/bundle/2026-08-12_handsome-husbandos/source.json` (`ourlife_beginningsandalways_dlcpack`, `adatewithdeathdeluxedlcpack`) as parser test input — these are real, already-archived examples, not invented ones.
- Regenerate `schemas/game-list.schema.json` and `schemas/humblebundle-archive.schema.json` after the model changes (`uv run game-collections schema`); `tests/test_schema.py` will catch drift if this is skipped.
- Manually re-run `scrape humblebundle` (non-`--git`, dry local run) against the `love-letter-to-lovecraft` bundle (or `handsome-husbandos`) and confirm the Dagon/Our Life/Date with Death DLC packs now resolve into multiple named `Game` entries sharing a `group`, each with `requires` pointing at the base game.
- Manually exercise the new "Multiple…" prompt path via `complete` on a sample draft list to confirm it re-searches each typed name normally and produces separate, correctly grouped games.
