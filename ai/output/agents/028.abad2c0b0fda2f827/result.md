## 1. Where offers/games are extracted from HTML (crawler.py / parser.py)

**crawler.py** (`src/game_collections/sources/humblebundle/crawler.py`) fetches pages and delegates parsing:
- `crawl_humble_offers` (line 146) calls `parse_bundle_page(page, listing, observed)` for `/games/...` bundle pages or `parse_choice_page` for `/membership` (lines 186-190).
- The raw fetched HTML itself is **not archived** — only the JSON derived from it. `write_humble_offer` (line 266+) writes two files per offer: `metadata.json` (the normalized `HumbleArchive.model_dump()`) and `source.json` (the `offer.source` dict returned by the parser, e.g. `{"bundle_data": bundle, "listing": listing_data}` — see parser.py line 458). The raw HTML page text is discarded after parsing; it's never itself persisted.

**parser.py** (`src/game_collections/sources/humblebundle/parser.py`):
- `parse_bundle_page` (line 356) pulls the embedded `<script id="webpack-bundle-page-data">` JSON blob (`_embedded`/`scripts` dict, lines 61-127), not the rendered HTML DOM. Item-level data comes from `bundle["tier_item_data"]` (a machine_name → item-JSON map), turned into `HumbleItem`s by `_bundle_item` (line 251).
- Each item's description comes from `raw.get("description_text")` (an **HTML string embedded in the JSON payload**, itself containing `<p>`, `<ul><li>` etc.), converted to Markdown via `_markdown()`/`markdownify` (line 258, using `_markdown` at line 164). So the full offer-description HTML (including any nested DLC list) does reach the parser, but only survives as **Markdown text on `HumbleItem.description`** — no HTML retained, no sub-item extraction.
- The "DLC" pill you see on humblebundle.com as `<span class="extra-info fine-print">DLC</span>` is **not** literal markup anywhere in the captured JSON. It's client-side-rendered from a `cta_badge` field: `raw.get("cta_badge")` → `{"badge": "dlc", "icon": "hb-gamepad"}` (lines 253-256). The parser already reads this and appends `badge["badge"].title()` (`"Dlc"`) into `HumbleItem.tags`. This is the **only** place `fine-print`/`extra-info`/`DLC` concepts are touched in the codebase (grep across humblebundle/greenmangaming/isthereanydeal found matches only in humblebundle: crawler.py/parser.py/models.py have no literal "DLC" string besides `cta_badge` handling; steamdb.py and comments elsewhere just mention DLC in prose, no special-case logic).
- There is **no code anywhere** that parses/searches the description HTML for nested sub-item lists (`<li>`) or for a "download the base game here" link — the base-game link (`<a href="...">here</a>`) just becomes part of the Markdown description text, unstructured.

## 2. models.py — raw/archived offer representation

`src/game_collections/sources/humblebundle/models.py`:

```python
class HumbleItem(StrictModel):
    machine_name: NonEmptyString
    title: NonEmptyString
    item_type: NonEmptyString | None = None
    is_game: bool
    retail_price: HumblePrice | None = None
    youtube_urls: list[HttpUrl] = Field(default_factory=list)
    cover_art_url: HttpUrl | None = None
    developers: list[HumbleLink] = Field(default_factory=list)
    publishers: list[HumbleLink] = Field(default_factory=list)
    redeem_on: list[NonEmptyString] = Field(default_factory=list)
    platforms: list[NonEmptyString] = Field(default_factory=list)
    description: str = ""          # <-- Markdown, not HTML; no sub-item structure
    key_expiration_text: NonEmptyString | None = None
    tags: list[NonEmptyString] = Field(default_factory=list)   # <-- "Dlc" badge lands here
    genres: list[NonEmptyString] = Field(default_factory=list)
    rating: dict[str, object] = Field(default_factory=dict)
    region_locked: bool | None = None
    excluded_countries: list[NonEmptyString] = Field(default_factory=list)
    resolution: HumbleResolution = Field(default_factory=HumbleResolution)
```

`HumbleTier` (line 68) is just `identifier`, `name`, `item_count`, `minimum_price`, `items: list[HumbleItem]`. `HumbleArchive` (line 139) holds `tiers: list[HumbleTier]` plus bundle-level metadata. **No field exists** for description HTML (only `str` Markdown `description`), no sub-item/child-DLC list field, no base-game reference field, no `requires`/`bundled_items` concept anywhere in this file.

## 3. resolver.py — offer-to-storefront resolution

`src/game_collections/sources/humblebundle/resolver.py`, `StorefrontResolver.resolve_item` (line 249) and `resolve_archive` (line 292):
- Resolution operates **per distinct `HumbleItem`** keyed by `machine_name`, one flat title-search per item against each store in `item.redeem_on` (steam/gog/epic/ubisoft/humble), picking exact-title matches or falling back to a `CandidateChooser` callback (interactive/manual pick). Results are cached in `HumbleResolutionMap.games: dict[machine_name -> list[qualified_id]]` (models line 63-84 in resolver.py).
- `resolve_archive` collects "every distinct real game" via `item.is_game and item.machine_name not in seen_names` (lines 299-306) — a DLC-pack item like `adatewithdeathdeluxedlcpack` has `is_game=True` (since `item_content_type == "game"`), so it is treated **exactly like any other single game/offer**: one title search ("A Date with Death Deluxe DLC Pack"), one resolved ID list. There is **no concept of "this offer bundles multiple things"** anywhere in resolver.py — no splitting an item into constituent sub-games, and no separate resolution of the base game it requires (the base game, if it also appears elsewhere in the bundle as its own item, would only get resolved as an unrelated separate item; if it doesn't appear as its own bundle item, it's never resolved/id'd at all).

## 4. Wider models.py — DLC / base-game relationship

Grep for `dlc`, `requires`, `base_game`, `requirement` across `src/game_collections` (excluding `__pycache__`) found:
- `src/game_collections/models.py` line 100: `raise ValueError("reference requires a path or URL")` — unrelated (English word "requires", not a modeling concept).
- `src/game_collections/completion.py` line 49: a **comment** noting "of the base app + DLC" (Steam AppID ambiguity context, not a model field).
- `src/game_collections/sources/storefronts.py` line 90: similar comment about Steam bundle IDs ("app + DLC) has no single AppID").
- `src/game_collections/sources/isthereanydeal/game_alias_config.py` lines 19-20: comment about Steam vs Epic DLC slugs being unresolved aliases, not a model field.
- `src/game_collections/sources/humblebundle/steamdb.py` line 127: comment noting DLC is filtered out of steamdb scraping results.

**No Pydantic model field anywhere** in `src/game_collections/models.py` (the launcher-neutral `Game`/`GameList`/`Reference` contract) represents DLC-vs-base-game relationships, a "requires" edge, or a `base_game`/`requirement` concept. `Game` (in `models.py`) is just `name` + `ids: list[QualifiedGameId]` (plus grouping fields) — flat, no relational structure.

## 5. Real archived raw HTML/JSON snippet with DLC pack + nested items

No `love-letter-to-lovecraft` archive exists yet under `archives/humblebundle/bundle/` (most recent archives run 2026-06-17 through 2026-08-28). However `archives/humblebundle/bundle/2026-08-12_handsome-husbandos/source.json` contains real DLC-pack items with nested sub-DLC lists. Structure: top-level `{"bundle_data": {...}, "listing": {...}}`; `bundle_data["tier_item_data"]["<machine_name>"]["description_text"]` holds the raw captured HTML fragment (not the full page HTML — just this field). Example (`ourlife_beginningsandalways_dlcpack`, `item_content_type: "game"`, `cta_badge: {"badge": "dlc", "icon": "hb-gamepad"}`):

```
<strong>This DLC Pack contains 6 DLCs for&nbsp;<em>Our Life: Beginnings &amp; Always!&nbsp; </em>Be sure to download the game for FREE <a href="https://store.steampowered.com/app/1129190/Our_Life_Beginnings__Always/">here</a>.<em><br><br></em></strong>
<ul>
<li>Our Life: Beginnings &amp; Always: Cove Wedding Story</li>
<li>Our Life: Beginnings &amp; Always: Baxter's Story</li>
<li>Our Life: Beginnings &amp; Always: Derek's Story</li>
<li>Our Life: Beginnings &amp; Always: Step 3 Expansion</li>
<li>Our Life: Beginnings &amp; Always: Step 2 Expansion</li>
<li>Our Life: Beginnings &amp; Always: Step 1 Expansion</li>
</ul>
<br>A nostalgic visual novel where you design your own character...
```

Second example, `adatewithdeathdeluxedlcpack`:
```
<p><strong>This DLC pack contains 3 DLCs for&nbsp;<em>A Date with Death! </em>Be sure to download the game for FREE <em><a href="https://store.steampowered.com/app/2415010/A_Date_with_Death/">here</a>.</em></strong><br><br>You're just an ordinary person... </p>
```

This confirms: the base-game download link is an ordinary `<a href="https://store.steampowered.com/app/.../">` inside `description_text`, and the sub-DLC list is an ordinary `<ul><li>` list inside the same field — both get flattened into `HumbleItem.description` as Markdown text by `_markdown()`, with no structured extraction of the link URL or the list items as separate entities anywhere downstream (parser, models, resolver, or writer).