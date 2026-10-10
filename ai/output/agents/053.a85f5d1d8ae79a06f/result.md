I found the raise location for all five errors. Humble error 1 is the only one I couldn't pin to a single input. Nothing was edited.

## Humble Bundle

### 1. `Steam URLs must use store.steampowered.com`

- **Raise site:** `src/game_collections/sources/storefronts.py:106-108`, inside `parse_store_identity(provider, value)`.
  ```python
  if provider == "steam":
      if host not in STORE_HOSTS["steam"]:
          raise ValueError("Steam URLs must use store.steampowered.com")
  ```
  `STORE_HOSTS["steam"]` is only `{"store.steampowered.com"}` (line 28). Any other host fails, including `steamcommunity.com`, `steamdb.info` and `www.steampowered.com`. Non-URL inputs like `steam:123` or a bare decimal AppID are handled earlier (lines 88-102).
- **Which caller is uncaught:** three humble callers use `parse_store_identity`.
  - `resolver.py:167`, in the search-result parser, wraps it in `try/except ValueError` and skips the result.
  - `resolver.py:436` (`base_game_url` → `requires`) also catches `ValueError`.
  - `resolver.py:412` does not catch it: `ids.append(parse_store_identity(typed_provider, selected))` in `_resolve_title`. `selected` comes from `self._choose(...)`.
- **Where `selected` comes from:** `choose_store_candidate` in `sources/prompting.py:~92-165`. Picking a numbered candidate returns its `qualified_id`, which is already valid. The "Other…" row (`prompting.py:~153-160`) returns whatever the user pasted, unvalidated: `typer.prompt("Paste the store URL or direct ID; leave blank for unresolved") → return manual or None`. So the error most likely comes from a pasted non-`store.steampowered.com` URL, such as steamcommunity or steamdb, for a Dying Light 2 item. Candidates from `_search_steam` (`resolver.py:244-279`) build `https://store.steampowered.com/{app|sub|bundle}/...`, so they pass the host check.
- **What the exception does:** `crawl_humble_offers` (`humblebundle/crawler.py:~247`) catches `(OSError, ValueError, HumbleCrawlError)` and records `errors.append(f"{url}: {error}")`. The whole offer is lost and the user's typed input is not re-prompted. The `try/except ValueError` around `build_*_archive` (`crawler.py:~214`) only covers building, not `resolver.resolve_archive` at `crawler.py:~234`.
- **Unconfirmed:** I could not tell from the code which input was pasted. `/sub/<id>` URLs on `store.steampowered.com` do not raise this message. They raise a different one (`Steam URL does not contain an AppID or bundle ID`, line 122), because only `/app/` and `/bundle/` are parsed (lines 110-119).
- **Likely fix:** validate the pasted value inside `_resolve_title` or `choose_store_candidate` and re-prompt. Alternatively, catch `ValueError` at `resolver.py:412` and fall back to the `unresolved:source:humblebundle:{cache_key}` marker (`resolver.py:~417`).
- **Tests:**
  - `tests/test_humblebundle_resolver.py:81-85` covers the error for `https://example.com/app/440`.
  - Lines 157-165 cover the blank selection giving the unresolved marker.
  - Nothing tests a bad pasted URL going through `resolve_item`.

### 2. `GameList: games List should have at least 1 item`

- **Constraint:** `src/game_collections/models.py:192`, `games: list[Game] = Field(min_length=1)`. `GameListV1` has the same constraint at line 264.
- **Construction:** `humblebundle/crawler.py:442-461`, the final `GameList(... games=games)` in `write_humble_offer`. The Choice-with-pick-options branch has the same shape at line 387.
- **How it ends up empty:**
  - Lines 405-418 loop over each `tier.items` and keep only items with `item.is_game`. Non-game items such as software or books are skipped (`parser.py:469`: `item_type == "game" and "coupon" not in tags`).
  - Tiers with no games are dropped (`if games:`, line 417).
  - So a software-only bundle like `make-play-games-in-godot-software` leaves `tiers_with_games == []`.
  - It then falls to the `else` branch (line ~430), where `merge_tiered_games([])` returns an empty `games` list. It is not the `len == 1` branch, and the `kind == "choice"` branch has its own empty guard.
  - Pydantic then raises. The `ValueError` is caught at `crawler.py:~247` and recorded as an error.
- **Empty-bundle handling:** nothing in `crawl_humble_offers` or `write_humble_offer` skips an empty bundle. I did not find a skip-with-warning for empty bundles in the other sources either. `grep` for `unresolved`, `skip` and `empty` turned up only per-game handling.
- **Where a skip would go:** `write_humble_offer` has no log argument. `crawl_humble_offers` has `log` and `on_offer`, so the check could go before `on_offer(offer)` (`crawler.py:~240`), or `write_humble_offer` could return `()`.
- **Parked payload:** a failure in `build_*_archive` parks a recovery payload. This failure happens later, at write time, so the archive was already fetched and resolved before it failed.
- **Tests:** `tests/test_humblebundle_crawler.py` has no case for a non-game-only bundle. I didn't open that file; I only grepped it.

## Deku Deals

### 3. `unrecognized tiering_style: 'all_one_price'`

- **Raise site:** `src/game_collections/sources/dekudeals/parser.py:200-202`.
  ```python
  tiering_style = bundle.get("tiering_style")
  if tiering_style not in ("price_per_tier", "price_per_item"):
      raise DekuParseError(f"bundle page has an unrecognized tiering_style: {tiering_style!r} ({url})")
  ```
- **Hardcoded in four places:**
  - `parser.py:164`: `DekuBundleDraft.tiering_style: Literal["price_per_tier","price_per_item"]`.
  - `dekudeals/models.py:107`: the same `Literal` on `DekuArchive`, with docs at lines 53-59.
  - `dekudeals/crawler.py:250`: item inclusion per tier uses `draft.tiering_style == "price_per_item" or int(tier.identifier) in item.tier_ids`.
  - `crawler.py:338` and `crawler.py:366`: `archive.tiering_style == "price_per_item"` selects `pick_quota` (this is `write_deku_offer`).
- **Documented behavior:** `sources/README.md:101` says there are two real styles, "both modeled by one `DekuTier`".
  - `price_per_tier` is cumulative price breakpoints. Each item's `tiers` list says which breakpoints unlock it. It becomes ordinary `GameList.tiers`.
  - `price_per_item` is Build-Your-Own. Every tier fixes an `item_minimum` pick count over one shared pool, and every item's `tiers` is empty. It becomes `pick_quota` tiers via `merge_tiered_games`.
- **`all_one_price`:** it is not in the README. By name it is a single flat price for the whole set (the failing bundles are charity, "complete" and humble-choice-style). That would mean one tier containing all items.
  - In `crawler.py:250`, an item is included if the tier id is in `item.tier_ids`. If these items carry an empty `tiers` list, as `price_per_item` items do, they would all be dropped. The mapping would likely need to treat `all_one_price` like `price_per_item` for inclusion, but not for `pick_quota`.
  - I did not see a live page, so this is unconfirmed.
- **Tests:** `tests/test_dekudeals_parser.py:140-149` (`test_bundle_page_rejects_unrecognized_tiering_style`, using `"something_new"`). It will keep passing if the new value is added. Positive cases are lines 89-137.
- **Existing tests:** `test_dekudeals_crawler.py:40` has a `price_per_tier` fixture and `test_dekudeals_parser.py:71,117` have both existing styles. No `all_one_price` fixture exists.

### 4. `item page has no storefront links`

- **Raise site:** `dekudeals/parser.py:285-286` in `parse_item_page`, when `_ITEM_STORE_LINK_PATTERN` finds no `data-out-analytics-id='…' href='…'` rows. The failing items are goodies/art packs such as `dying-light-2-stay-human-goodies-pack-arts`.
- **Single caller:** `dekudeals/crawler.py:162` inside `_resolve_item_ids`, which then builds `ids = qualified_ids_from_urls(store_urls)` and always appends `dekudeals:{slug}` (lines 163-166).
  - This fits the README: store ids are "silently skipped" when the store is unrecognized.
  - A missing-links page could reasonably be treated the same way: `store_urls = []` still yields `dekudeals:{slug}`.
  - But the `DekuParseError` propagates up to `crawl_deku_offers` (`crawler.py:277`), which aborts the whole bundle.
- **Unresolved markers elsewhere:**
  - Humble uses `unresolved:source:humblebundle:{cache_key}` (`humblebundle/resolver.py:417`).
  - Green Man Gaming uses `unresolved:source:greenmangaming:{cache_key}` (`greenmangaming/resolver.py:243`).
  - ITAD uses `unresolved:source:isthereanydeal:{bundle_id}:{slug}` (`isthereanydeal/parser.py:319`).
  - `common.py:605` and `isthereanydeal/parser.py:287` ignore these when counting resolved providers.
  - Deku has no unresolved marker. `dekudeals:{slug}` is the always-present id.
- **Tests:**
  - `tests/test_dekudeals_parser.py:198-205` (`test_item_page_requires_at_least_one_store_link`) asserts the raise. It would need changing if the behavior changes.
  - `tests/test_dekudeals_crawler.py:57-103` covers id resolution and the mapping cache. There is no test for an item with no links.

### 5. `bundle page has an item with no slug/name`

- **Raise site:** `dekudeals/parser.py:237-240`, in the item loop of `parse_bundle_page`.
  ```python
  if not isinstance(item_slug, str) or not item_slug or not isinstance(item_name, str) or not item_name:
      raise DekuParseError(f"bundle page has an item with no slug/name: {url}")
  ```
- **Failing bundle:** `garbage-dwellers`. That bundle likely contains an item with a null `slug`, i.e. one Deku has no item page for.
- **Skipping:** this loop is the only place items become `DekuItemDraft`s. `parse_bundle_page` has no log argument, so a warning would need one. Dropping the item would not break the tier-membership logic at `crawler.py:250`, because it iterates `draft.items`. A caveat: `parse_bundle_page` already rejects an empty `items_raw` at line ~195, and after skipping an all-bad list you would need a recheck. `DekuTier` has its own non-empty constraint (`dekudeals/models.py:45`, `ids` is `min_length=1`). Tier items may legitimately be empty, since line 110 requires only `tiers`.
- **Tests:** none for this raise. `test_dekudeals_parser.py` covers `bundle_slug`, tiering and the item page only.

## Docs and fixtures

- `src/game_collections/sources/README.md:100-101` is the only Deku behavior documentation. There is no `sources/dekudeals/README`, and the earlier file listing shows none.
- The README makes no mention of empty bundles (Humble), `all_one_price`, goodies items, or items without slugs.
- `tests/fixtures/` contains only `steam/`. Both the Deku and Humble tests build their inputs inline, using `_inertia_page(props)`, `_price_tier_bundle()` and `_item_row()` helpers in `tests/test_dekudeals_parser.py`.