# Humble Bundle Scraping Pipeline — Investigation Report

## Scope note
No local archive/list exists yet for the `dread-and-dark-fantasies-rpg-collection` bundle (it's a currently-live bundle, not yet crawled into `archives/humblebundle/` or `lists/humblebundle/`). I confirmed via existing archives that plain `"Steelrising"` (from the May 2024 and Dec 2025 bundles) already resolves cleanly to `steam:1283400` (`lists/humblebundle/bundle/2024-05-07_may-2024/bundle.yml:18-20`, `lists/humblebundle/bundle/2025-12-15_humbling-soulslike-bundle-encore/bundle.yml:15-17`). The new problem is specific to the title `"Steelrising - Bastille Edition"`, which is not a standalone Steam app page — it's a purchase option ("Buy Steelrising - Bastille Edition") on app 1283400's own store page, backed by Steam package/sub 729916 (base app + 2 DLCs). No single Steam URL with that exact title exists to give an unambiguous `normalized_title` match, and it isn't a recognized `bundle/<id>` steamdb hit either — so today it will fall through to the interactive "Multiple…"/"Other…" prompt with no good single answer.

## 1. `resolver.py` — title-to-Steam-appid resolution flow

File: `src/game_collections/sources/humblebundle/resolver.py`

- `StorefrontResolver.resolve_archive` (lines 339-393) iterates every distinct game-`HumbleItem` across tiers and calls `resolve_item` per item, then writes results into `HumbleResolution` (either flat `ids` or, for DLC packs, a list of `splits`).
- `StorefrontResolver.resolve_item` (lines 315-337): if `item.bundled_dlc_names` is non-empty (i.e. the item was gated as a DLC pack by the parser), it resolves each DLC name separately via `_resolve_title`, attaching `requires=[steam:<base_game_appid>]` (parsed from `item.base_game_url`) to every split. Otherwise it resolves `item.title` as a single title.
- `StorefrontResolver._resolve_title` (lines 258-313) is the actual per-title resolution loop:
  - Checks `mapping.games[cache_key]` first (reviewed/cached answer) — this is where a human-reviewed `steam:1283400` (or e.g. `steam:1283400` + Steelrising DLC appids) could just be pre-recorded to sidestep re-prompting.
  - For each store in `item.redeem_on` (e.g. `["steam"]`), searches candidates via `_search_steam` (steam) or `self.search` (other stores).
  - "Exact match" success path: if exactly one candidate's `normalized_title(candidate.title) == normalized_title(title)` (see `storefronts.normalized_title`, strips ™/®/© and punctuation, casefolds), that candidate's `qualified_id` is accepted with **no prompt**.
  - Otherwise calls `self._choose(title, provider, candidates)` — the injected `CandidateChooser`. In production this is `prompting.choose_store_candidate` (see below); in tests it's a stub lambda.
  - If the chooser returns a `ChosenNames` (i.e. user picked "Multiple…"), `_resolve_title` **recurses**: each declared sub-title is independently resolved from scratch across *all* stores (not just the current one), cached under a compound key `f"{cache_key}::{index}"`, and the results become several separate `ResolvedGame`s replacing the one original title.
  - If the chooser returns a plain URL/ID string, `parse_store_identity` normalizes it and it's appended to `ids`.
  - If nothing resolves for any store, falls back to the placeholder `unresolved:source:humblebundle:{cache_key}`.
  - Final `ids` are deduped and the result cached into `mapping.games[cache_key]` for future runs (`HumbleResolutionMap`, reviewed mapping YAML — see `load_resolution_map`/`render_resolution_map`, lines 172-187).
- `StorefrontResolver._search_steam` (lines 221-256): searches steampowered.com first; only if there is *not* exactly one exact-title match, and a `steamdb_fetch` was supplied, it falls back to steamdb.info's own search (`STEAMDB_SEARCH_URL`/`parse_steamdb_results`, see `steamdb.py`). Notably, this fallback returns `StoreCandidate`s built directly from steamdb rows, whose `qualified_id` is either `steam:<appid>` or `steam:bundle/<id>` (see comment lines 249-251) — steamdb.info's `/bundle/<id>/` rows are Steam **retail bundles**, not the storefront **package/sub** concept relevant here (a "Buy X - Y Edition" purchase-option sub is neither an appid nor a steamdb "Bundle" row — see gap analysis below).

**"Multiple matches" prompt flow** lives in `src/game_collections/sources/prompting.py` (`choose_store_candidate`, the real `CandidateChooser` implementation used outside tests — wired in wherever `StorefrontResolver` is constructed, e.g. in the CLI). It lists numbered candidates + `Multiple…` + `Other…`; picking `Multiple…` loops collecting free-text sub-titles (first prompt defaults to the searched title) and returns them as `ChosenNames`; picking `Other…` prompts for a manual URL/ID.

**Where invoked from `crawler.py`**: `crawl_humble_offers` (line 202) calls `resolver.resolve_archive(archive, mapping, log=log)` once per freshly-parsed (non-cached) offer. `write_humble_offer`'s `_games_for_item` (lines 258-268) turns a resolved item into one `Game` (flat `ids`) or, if `item.resolution.splits` is populated, several `Game`s sharing a `GameGroup` and each other's `requires` — this is the existing "DLC pack" fan-out mechanism.

## 2. `parser.py` — DLC pack gating logic

File: `src/game_collections/sources/humblebundle/parser.py`

Core pieces (added across commits `072398be3`, `583a28fcc`, `1d204c3bf`, `177ae837f`):

- **Gating condition** (line 371, inside `_bundle_item`):
  ```python
  base_game_url, bundled_dlc_names = (
      _parse_dlc_pack_details(raw.get("description_text") or "") if "dlc" in tags else (None, [])
  )
  ```
  `tags` is populated from Humble's own `cta_badge.badge` field (lines 319-323): `if isinstance(badge, dict) and isinstance(badge.get("badge"), str): tags.append(badge["badge"])`. So the **sole** gate for "is this item a DLC pack" is Humble's own site-provided badge value `"dlc"` on `cta_badge`, not any heuristic over the description text — this is exactly what commit `177ae837f`'s message describes fixing (a normal game's description was previously being pattern-matched into a false-positive split; now the parse function is only ever called when Humble has already tagged the item as `dlc`). See `test_bundle_page_ignores_dlc_pack_shape_on_a_non_dlc_item` (parser test, line 249) for the negative case and `test_bundle_page_wires_dlc_pack_details_onto_the_item` (line 192) for the positive case — both items have near-identical description HTML shape (a Steam link + a `<ul>`), and the only difference triggering the split is `cta_badge: {"badge": "dlc"}` vs `None`.

- **Extraction** (`_DlcPackDetailsParser`, lines 130-177, and `_parse_dlc_pack_details`, lines 180-193): a small `HTMLParser` subclass that:
  - grabs the **first** `<a href="...store.steampowered.com/app/...">` anywhere in the description as `base_game_url` (the free base game link Humble's copy always includes for a DLC pack, e.g. "download the game for FREE here");
  - grabs every `<li>` text inside the **first** `<ul>` in the description as `bundled_dlc_names` (Humble's copy: "This DLC Pack contains N DLCs for X" followed by a bullet list of DLC names) — subsequent `<ul>`s (e.g. a later "features" list) are ignored via `_first_ul_done`.
  - Docstring explicitly warns: only call this for items already tagged `dlc`, since a normal game's description commonly *also* has a Steam link + an early bullet list (feature list) and would otherwise be misidentified.

- **Wiring onto the model**: `HumbleItem.base_game_url` / `HumbleItem.bundled_dlc_names` (models.py lines 82-84) are populated straight from this extraction in `_bundle_item` (parser.py line 373-394) and then drive `resolver.resolve_item`'s split branch (resolver.py line 326).

**Key implication for the Steelrising case**: this "DLC pack" mechanism only fires when Humble's *own* item is badged `cta_badge.badge == "dlc"` and describes itself with the "This DLC Pack contains N DLCs for X... download the game for FREE here" + bullet-list-of-DLC-names copy pattern. For "Steelrising - Bastille Edition" the Humble item is presumably a normal **game** item (not badged `dlc` — it's the full base+DLCs edition, not a bare DLC add-on pack), so this gating path won't even trigger; the item goes through `resolve_item`'s plain single-title branch, which is where the Steam-side ambiguity (no single app page titled exactly "Steelrising - Bastille Edition") causes the "Multiple matches" prompt.

## 3. `steamdb.py` — usage and package/sub concept

File: `src/game_collections/sources/humblebundle/steamdb.py`

- Purpose: a **fallback-only** Steam title search against steamdb.info's own (unfiltered "Everything") search, used from `resolver._search_steam` only when steampowered.com's own search doesn't already give a unique exact-title match (see resolver.py lines 221-256). Requires a real headed Chromium session (`SteamDbBrowserClient`, patchright-based) because steamdb.info sits behind a Cloudflare managed challenge; tests inject a fake `steamdb_fetch` instead.
- `parse_steamdb_results` (lines 178-205) parses `/app/<id>/` and `/bundle/<id>/` result rows only. **There is no concept of a Steam "sub"/package ID anywhere in this file** — only `App` rows (bare numeric appid) and steamdb's own `Bundle` rows (`bundle/<id>`, i.e. a Steam *retail bundle*, which is a different Steam-side concept than a storefront "package"/"sub" that groups an app + its DLCs under one purchase button). `_RESULT_LINK_HREF` regex (line 39) only matches `^/(app|bundle)/(\d+)/$` — a steamdb.info `/sub/<id>/` page (like `steamdb.info/sub/729916` mentioned in the task, which lists package apps for "Steelrising - Bastille Edition") is **not recognized at all** by this parser; it would simply not match and be skipped/ignored if it ever appeared in search results.

## 4. `models.py` — relevant models

File: `src/game_collections/sources/humblebundle/models.py`

- `HumbleResolvedGame` (lines 33-39): `{name, ids}` — one split-out game.
- `HumbleResolution` (lines 42-56): `ids` (flat, single-game case) / `unresolved_stores` / `requires` (shared base-game dependency ids) / `splits: list[HumbleResolvedGame]` (DLC-pack case, `ids` left empty when `splits` is used). Docstring explicitly documents the ids-vs-splits duality.
- `HumbleItem` (lines 59-86): includes `resolution: HumbleResolution`, plus the DLC-pack-detection outputs `base_game_url: HttpUrl | None` and `bundled_dlc_names: list[NonEmptyString]` (lines 83-84, comment ties them to `cta_badge`/`tags == "dlc"`).
- **Identity string formats** used throughout (defined/consumed via `storefronts.parse_store_identity`, not this file): `steam:<appid>` (plain int), `steam:bundle/<id>` (Steam retail bundle — comment in `storefronts.py` lines 99-106 notes this exists specifically because "a Deluxe Edition only sold as a bundle of the base app + DLC has no single AppID"), and the unresolved placeholder `unresolved:source:humblebundle:<cache_key>` (resolver.py line 308). **No `steam:sub/<id>` or `steam:package/<id>` form exists anywhere.**

## 5. Existing DLC-pack-gating tests — representative fixture pattern

File: `tests/test_humblebundle_parser.py`

Pattern used (both the parsing unit and the full-item integration tests use *real, live-observed* Humble `description_text` HTML as the fixture, pasted verbatim, sourced from an actual archived bundle):

- `test_parse_dlc_pack_details_extracts_base_game_and_dlc_list` (line 151): calls `_parse_dlc_pack_details(description)` directly with real HTML from `ourlife_beginningsandalways_dlcpack` (comment cites the exact archive file: `archives/humblebundle/bundle/2026-08-12_handsome-husbandos/source.json`), asserts the returned `(base_game_url, dlc_names)` tuple.
- `test_bundle_page_wires_dlc_pack_details_onto_the_item` (line 192): builds a full synthetic `webpack-bundle-page-data` JSON payload (single tier, single `dlc_pack` item dict with `"cta_badge": {"badge": "dlc"}` and a `description_text`), feeds it through `parse_bundle_page`, and asserts on the resulting `HumbleItem.tags`, `.base_game_url`, `.bundled_dlc_names`.
- `test_bundle_page_ignores_dlc_pack_shape_on_a_non_dlc_item` (line 249): the false-positive-guard test — same description shape (Steam link + `<ul>`) but `"cta_badge": None`, asserts `tags == []`, `base_game_url is None`, `bundled_dlc_names == []`.

File: `tests/test_humblebundle_resolver.py`

- `test_resolve_item_splits_a_dlc_pack_and_attaches_requires` (line 285): builds a `HumbleItem` directly (no parser involved) with `tags=["dlc"]`, `base_game_url=...`, `bundled_dlc_names=["DLC One"]`, then calls `resolver.resolve_item(item, mapping)` and asserts the single split's `name`/`ids`/`requires`.
- `test_choosing_multiple_splits_a_title_into_separate_resolved_games` (line 309): the "Multiple…" prompt path — a fake `choose` returns `ChosenNames(names=["Game A", "Game B"])` only when asked about `"Combo Pack"`; asserts the two resulting `ResolvedGame`s and that `mapping.games` caches each under `"combo_pack::1"` / `"combo_pack::2"`.

For a new "Steelrising - Bastille Edition" test case, the natural home given this style would be a `test_humblebundle_resolver.py` test exercising `_resolve_title`/`resolve_item`'s ambiguous-Steam-title path (since, per the gating logic above, this item is **not** currently `cta_badge`-tagged `dlc`, so it doesn't go through the parser's DLC-pack split at all — it's a single-title resolution that currently has no clean answer and today would rely on `_choose` returning `ChosenNames` or a manual `Other…` URL).

## 6. `sub:`/package handling elsewhere in the codebase

Searched the whole `src/game_collections` tree for `sub:`, `package`, `steamdb.info/sub`, and `/sub/` — **no matches** relating to Steam packages/subs. The only "package"-ish concept is Steam's own **retail bundle** (`steam:bundle/<id>`, steamdb.info `/bundle/<id>/` rows), which is a different Steam entity than a storefront "sub"/package (subs group an app + DLCs for one buy-button but aren't separately sold as their own product/bundle page). There is currently **no way to express** "this Humble item resolves to base app X plus DLC apps Y, Z, purchased together as a single Steam sub" as a first-class identity or resolution shape. The closest existing mechanism is the DLC-pack `splits`/`requires` shape (item 4 above), but that's driven by *Humble's own description text listing DLCs*, not by Steam-side package/sub data — and it's gated strictly on `cta_badge.badge == "dlc"`.

## 7. Bundled-purchase-option / sub-package handling in `resolver.py` and `storefronts.py`

- `resolver.py`: covered in detail in item 1/3. Steam search results are scraped from steampowered.com's own `/search/?term=...` HTML (`_StoreLinkParser` in resolver.py, lines 86-143) via anchor `href`s parsed by `parse_store_identity`, which only recognizes `/app/<id>/` and `/bundle/<id>/` URL shapes (storefronts.py lines 91-107) — a Steam store page's embedded "Buy X - Y Edition" purchase-option widget (which is what surfaces sub 729916 for Steelrising) is **not** a separate search result and is **not scraped at all** anywhere in this pipeline; nothing fetches or parses a Steam app's own store page HTML for its purchase-option/sub table.
- `storefronts.py`: `parse_store_identity`'s steam branch (lines 91-107) recognizes exactly two shapes: `steam:<appid>` (from `/app/(\d+)/`) and `steam:bundle/<id>` (from `/bundle/(\d+)/`, Steam retail bundle, with an explicit comment about "Deluxe Edition only sold as a bundle of base app + DLC" — functionally close to what's needed, but it's for steampowered.com's own `/bundle/` URLs, which Steelrising's "Bastille Edition" purchase option is *not*: it's a `/sub/<id>/` purchase link, a URL shape this function does not handle and would raise `ValueError("Steam URL does not contain an AppID or bundle ID")` for).

## Summary: the exact gap to fill

1. **No recognition of Steam `/sub/<id>/` URLs anywhere.** `storefronts.parse_store_identity`'s steam branch only matches `/app/` and `/bundle/`; a Steam sub/package purchase-option URL (or a steamdb.info `/sub/<id>/` page) falls through to a `ValueError`. There's no `steam:sub/<id>` (or similar) qualified-ID form, and no downstream consumer (game-ownership matching, `Game.requires`, etc.) understands what such an identity would mean.
2. **`steamdb.py`'s result-row parser (`_RESULT_LINK_HREF`) doesn't recognize `/sub/` rows** even if steamdb.info's search surfaced one — it only matches `app`/`bundle`.
3. **Humble's DLC-pack split mechanism (parser.py `_parse_dlc_pack_details` + `cta_badge=="dlc"` gate) is description-text-driven and Humble-badge-gated**, not Steam-package-driven — "Steelrising - Bastille Edition" is a normal (non-`dlc`-badged) game item on Humble's side, so it never enters that split path at all today, even though conceptually it's the same "base game + N DLCs sold as one purchase" shape, just discovered from the **Steam** side (a sub/package) rather than the **Humble** side (a `dlc`-tagged description).
4. **No fallback in `resolver._search_steam`/`_resolve_title`** that, upon hitting an ambiguous/no-exact-match Steam title lookup, tries interpreting the title as a Steam purchase-option/sub name (e.g. stripping " - X Edition" and checking if the base title has an exact match, or querying a sub/package endpoint) before falling back to the interactive prompt — this is presumably the fix point: either (a) teach `parse_store_identity`/`steamdb.py` a `sub/<id>` shape and have `_search_steam` recognize steamdb "Sub" rows as candidates, and/or (b) extend the parser-side DLC-pack detection (or add a resolver-side heuristic) to recognize a Steam-side "Edition = base + DLC bundle" title shape independent of Humble's own `cta_badge`, splitting it into `requires=[base]` + per-DLC entries the same way `bundled_dlc_names` does today.