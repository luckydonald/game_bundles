# Fix: spurious "DLC pack" splitting on normal game descriptions

## Context

While scraping Humble Bundle, the resolver prompted the user to pick a Steam match for:

> Resolve 'Survive and fight the horde  Monsters will come in waves. Fight them off using a variety of melee and ranged weapons, use herbs to recover your health, and protect each other's backs!' on steam:

immediately after logging `Game 7/9: Whisper Mountain Outbreak`. That text is a marketing bullet point from the game's own Steam description, not a DLC — but the code treated it as one.

Root cause, confirmed by reading `src/game_collections/sources/humblebundle/parser.py` and `resolver.py`:

- `_bundle_item` (parser.py:369) unconditionally runs `_parse_dlc_pack_details(raw.get("description_text") or "")` on **every** item, regardless of whether Humble tagged it as a DLC pack (`cta_badge.badge == "dlc"` → `tags == ["Dlc"]`). The function's own docstring rationalizes this: "Safe to run on every item's description, not just ones already tagged 'Dlc' - it's cheap and simply finds nothing on a normal item's description." That assumption is false.
- `_DlcPackDetailsParser` structurally grabs (a) the first `<a href="...store.steampowered.com/app/...">` anywhere in the description as `base_game_url`, and (b) every `<li>` text inside the *first* `<ul>` anywhere in the description as `bundled_dlc_names` — with zero semantic check that this is actually a DLC list. A normal game's Steam description commonly contains both: a self-referential/franchise Steam link, and an early feature-bullet `<ul>` ("Survive and fight the horde...", "Explore a vast open world...", etc.).
- `resolver.py`'s `resolve_item` (line 315) then gates DLC-splitting purely on `if item.bundled_dlc_names:` (line 326) — not on `item.tags` — so any item where the parser spuriously found a `<ul>` gets split into one fake "game" per bullet, each pushed through `_resolve_title`, which prompts the user when there's no exact storefront match.

`HumbleItem`'s own docstring in `models.py` (lines 81-84) already documents the *intended* contract: these fields are "Populated for 'DLC pack' items (see `cta_badge`/`tags == 'Dlc'`)…" — the code just never enforces it. GreenManGaming has no equivalent DLC-splitting logic (confirmed via grep), so this is Humble-only.

## Fix

Gate the DLC-pack extraction on the Humble-provided "Dlc" tag, matching the already-documented contract, instead of running it unconditionally and hoping it "finds nothing":

**`src/game_collections/sources/humblebundle/parser.py`** (`_bundle_item`, around line 369):
- Change the unconditional call:
  ```python
  base_game_url, bundled_dlc_names = _parse_dlc_pack_details(raw.get("description_text") or "")
  ```
  to only run when `"Dlc" in tags` (tags is already computed just above at lines 319-322), otherwise `(None, [])`.
- Update `_parse_dlc_pack_details`'s docstring (lines 180-185) to drop the now-false "safe to run on every item" claim and instead note it must only be called for items already tagged as a DLC pack.

No change needed in `resolver.py` — once `bundled_dlc_names` is only ever populated for genuine DLC-pack items, `resolve_item`'s existing `if item.bundled_dlc_names:` check becomes correct automatically.

## Tests

- `tests/test_humblebundle_parser.py`: existing tests (`test_bundle_page_wires_dlc_pack_details_onto_the_item`, `test_parse_dlc_pack_details_extracts_base_game_and_dlc_list`, `test_parse_dlc_pack_details_returns_none_for_plain_description`) already use `cta_badge: {"badge": "dlc"}` for the positive case, so they keep passing unchanged.
- Add a new regression test: a bundle item **without** a `"dlc"` `cta_badge` (a normal game) whose `description_text` contains both a `store.steampowered.com/app/...` link and an early `<ul><li>...</li></ul>` feature-bullet list — assert the resulting `HumbleItem.base_game_url is None` and `HumbleItem.bundled_dlc_names == []`, i.e. the parser no longer runs on it at all. This directly reproduces and guards against the "Whisper Mountain Outbreak" scenario.

## Verification

```console
env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_humblebundle_parser.py tests/test_humblebundle_resolver.py -q
env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q
```
