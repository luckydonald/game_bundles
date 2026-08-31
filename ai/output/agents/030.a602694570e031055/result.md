Now I have everything needed for a complete report.

## Summary

### 1. DLC-pack detection / extraction — `src/game_collections/sources/humblebundle/parser.py`

- **`_DlcPackDetailsParser`** (lines 130–177): a raw `HTMLParser` subclass.
  - **Base-game URL**: on the very first `<a>` tag encountered whose `href` contains `"store.steampowered.com/app/"`, it sets `self.base_game_url` to that href. Only the *first* such link in the whole description is used, and there is no proximity/context check to any particular sentence ("Be sure to download the game for FREE here").
  - **Bundled-DLC names**: it tracks the *first* `<ul>` element in the document (`_in_first_ul`/`_first_ul_done`); every `<li>` text inside that first `<ul>` (and only that one) is stripped and appended to `self.dlc_names`. Once that first `<ul>` closes, `_first_ul_done = True` and no further list is ever inspected (see the second test fixture in `test_bundle_page_wires_dlc_pack_details_onto_the_item`/the parser test, which includes a second `<ul>` with "4 different periods of life to experience" that is deliberately *not* picked up).
- **`_parse_dlc_pack_details(html)`** (lines 180–192): thin wrapper — returns `(None, [])` for blank input, otherwise feeds the HTML to the parser above and returns `(base_game_url, dlc_names)`. Its own docstring states the design intent explicitly:
  > "Safe to run on every item's description, not just ones already tagged 'Dlc' - it's cheap and simply finds nothing on a normal item's description."
- **Call site — `_bundle_item`** (line 369): `base_game_url, bundled_dlc_names = _parse_dlc_pack_details(raw.get("description_text") or "")` is called **unconditionally for every single item**, before any check of `item_type`, `tags`, or the `cta_badge` (`"Dlc"`) that Humble itself uses to flag DLC-pack items. There is no `if "Dlc" in tags:` guard anywhere in `parser.py`. The `HumbleItem.base_game_url`/`bundled_dlc_names` docstring in `models.py` (lines 81-84) even says these fields are meant to be "Populated for 'DLC pack' items (see `cta_badge`/`tags == 'Dlc'`)…" — but the code never actually checks that tag before running the extraction; the comment describes intent, not what the code does.

### 2. Resolver logic — `src/game_collections/sources/humblebundle/resolver.py`

- **`StorefrontResolver.resolve_item(item, mapping)`** (lines 315–337):
  - Computes `requires` from `item.base_game_url` via `parse_store_identity("steam", str(item.base_game_url))` if that URL is set.
  - **The actual DLC-pack branch**: `if item.bundled_dlc_names:` — this is the *only* gate deciding whether an item is treated as a DLC pack. It is purely "did the parser find a non-empty list of bundled DLC names," with **no re-check of `item.tags`** at this layer either. If true, it loops over every name in `item.bundled_dlc_names` and calls `self._resolve_title(dlc_name, stores, ...)` for each one — i.e., **each extracted `<li>` text is searched for as if it were an independent game/DLC title** on Steam/GOG/etc., exactly like a normal title would be.
  - `_resolve_title` (lines 258–313) does the exact-match search, and if there's no unique exact match it invokes the injected `choose` callback (`CandidateChooser`) which is what shows the "Multiple…"/candidate-picker prompt in the CLI (`prompting.py` / `cli.py`).
- **`StorefrontResolver.resolve_archive`** (lines 339–393) drives this for every distinct game item in the archive, logging `log(f"  Game {index}/{total}: {item.title}")` (line 359) **before** calling `resolve_item` — this is exactly the `"Game 7/9: Whisper Mountain Outbreak"` log line format the user saw, confirming the prompt was triggered from inside `resolve_item`/`_resolve_title` for that very item.
- **Split fan-out into `Game` records** happens later in `crawler.py`'s `_games_for_item` (lines 258–267): when `item.resolution.splits` is non-empty, it creates a `GameGroup` and emits one `Game` per split with `requires=item.resolution.requires`.

### 3. The heuristic for "what text counts as a DLC name"

There is no semantic/keyword heuristic at all (no check for phrases like "This DLC pack contains N DLCs for…", no check for `tags == ["Dlc"]`, no minimum-count check). It is purely structural:
- "base game" = href of the first `<a>` anywhere in the raw description HTML pointing at `store.steampowered.com/app/…`.
- "bundled DLC names" = the `<li>` texts of the first `<ul>` anywhere in the raw description HTML (any subsequent `<ul>`s are ignored).
- This extraction runs on **every** item's `description_text`, not just ones Humble tagged as "Dlc" (per the docstring's stated assumption that non-DLC descriptions "simply find nothing").

### 4. Test fixtures (`tests/test_humblebundle_parser.py`)

- `test_parse_dlc_pack_details_extracts_base_game_and_dlc_list` (lines 151–181): real `ourlife_beginningsandalways_dlcpack` description — bold intro text with a Steam link ("Be sure to download the game for FREE `<a href="...store.steampowered.com/app/1129190/...">here</a>`"), followed by a `<ul>` of 6 DLC names, followed by more prose and a *second* `<ul>` ("4 different periods of life to experience") that is correctly ignored because it isn't the first `<ul>`.
- `test_parse_dlc_pack_details_returns_none_for_plain_description` (line 184): confirms `<p>A <strong>great</strong> game.</p>` → `(None, [])`.
- `test_bundle_page_wires_dlc_pack_details_onto_the_item` (line 192): real `adatewithdeathdeluxedlcpack` fixture, tagged `cta_badge={"badge": "dlc"}` → `tags == ["Dlc"]`, verifying `base_game_url` is wired onto `HumbleItem`.
- `tests/test_humblebundle_resolver.py::test_resolve_item_splits_a_dlc_pack_and_attaches_requires` (line 285): constructs a `HumbleItem` with `tags=["Dlc"]`, `bundled_dlc_names=["DLC One"]`, `base_game_url=...`, and asserts `resolve_item` returns one `ResolvedGame` per DLC name with `requires` set to the base game's qualified id.

Note: I could not find an actual archived/failing Humble Bundle fixture in the repo containing "Whisper Mountain Outbreak" — the only occurrence of that title is in `lists/humblebundle/bundle/2026-08-21_love-letter-to-lovecraft/tier-{1,2,3}.yml`, and that list's own `references:` block cites `archives/isthereanydeal/bundle/16506/...` (an isTheReAnyDeal-sourced list, not a Humble-parsed one), and that isthereanydeal archive JSON has no HTML description with bullet lists at all. So the specific "Survive and fight the horde…" incident is not directly reproducible from checked-in fixtures — the "Game {index}/{total}: {title}" log format is unique to `humblebundle/resolver.py`, `greenmangaming/{resolver,crawler}.py`, and `dailyindiegame/crawler.py`, so the run in question came from one of those flows even though the archived Whisper Mountain Outbreak game itself isn't in the repo's `archives/humblebundle` snapshots.

### Hypothesis for the bug

`Whisper Mountain Outbreak` is a normal, non-DLC game — but the flaw is that `_parse_dlc_pack_details` is run on **every** item's description regardless of its `tags`/`cta_badge`, based on the (incorrect) assumption that a normal game description will "simply find nothing." Many normal Steam-game store descriptions do, in fact, contain both ingredients the parser structurally looks for:
1. A link to `store.steampowered.com/app/<id>/...` somewhere in the marketing copy (e.g., a self-referential "Wishlist/Buy it on Steam" link, or a link to a related/franchise title), which gets picked up as `base_game_url`.
2. An early `<ul><li>...</li></ul>` feature-bullet list (a very common marketing pattern — "Survive and fight the horde of infected...", "Explore a vast open world...", etc.), which gets picked up wholesale as `bundled_dlc_names` because it's simply the *first* `<ul>` in the HTML, with zero semantic validation that it's actually a DLC list.

Because `resolve_item`'s only condition for treating an item as a "DLC pack" is `if item.bundled_dlc_names:` (not `if item.bundled_dlc_names and "Dlc" in item.tags:`), a plain game whose description happens to have this shape gets incorrectly split: each feature bullet (e.g. "Survive and fight the horde…") is treated as an independent DLC title and gets pushed through `_resolve_title`, which tries to find an exact storefront match and, failing that, prompts the user to pick/search for it — exactly the spurious "resolve" prompt observed immediately after `Game 7/9: Whisper Mountain Outbreak` was logged.