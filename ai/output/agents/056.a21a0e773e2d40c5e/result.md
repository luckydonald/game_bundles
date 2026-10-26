## Findings

I found the code you asked about, why it exists, how the resolver and prompt work, and examples of both kinds of `<li>` list. The newest archive has no DLC `<li>` list at all. I also found an existing bug: the parser treats some explainer-style lists as DLC lists.

### 1. Where DLC `<li>` items become game entries

Parsing happens in `src/game_collections/sources/humblebundle/parser.py`.
- **`_DlcPackDetailsParser`** (lines 132–179) is an `HTMLParser` over the raw `description_text` HTML.
  - The first `<a href>` containing `store.steampowered.com/app/` becomes `base_game_url`.
  - Every `<li>` in the **first `<ul>` only** becomes a `dlc_names` entry. The first-`<ul>` rule is the `_in_first_ul` / `_first_ul_done` flags, set at lines 151–153 and 173–175.
  - Everything after that first list is ignored. In the Our Life pack, the later feature-bullet `<ul>`s are skipped this way.
- **`_parse_dlc_pack_details(html)`** (261–274) is the wrapper. Its docstring says to call it only for items tagged as a DLC pack, because ordinary games commonly have a Steam link and an early bullet list.
- **`_bundle_item`** (parser.py:413–501) is the only caller.
  - Lines 417–424 build `tags` from `cta_badge.badge`.
  - Lines 473–475 call `_parse_dlc_pack_details` only when `"dlc" in tags`. The gate is just that badge.
  - Lines 476–478 call `_parse_edition_bundle_components` only when `"dlc" not in tags`.
- **`_parse_edition_bundle_components(title, html)`** (219–258) is a separate, narrow `<p>`-based path, not `<li>`-based.
  - It matches the title `"<Base> - <X> Edition"`.
  - The first `<p>` must equal the edition name.
  - The second `<p>` must be `Includes: Base game + <X> DLC + <Y> DLC.`
  - Any other shape returns `[]`.
- **Model fields** are in `humblebundle/models.py`: `base_game_url`, `bundled_dlc_names` and `edition_component_titles` (about lines 90–99). `HumbleResolution` gained `splits` and `requires`.

Resolution into entries happens in `humblebundle/resolver.py`.
- **`resolve_item`** (434–462) sets `requires=[steam id of base_game_url]`. It uses `bundled_dlc_names or edition_component_titles` as the component titles. Each title goes through `_resolve_title(..., cache_key=f"{machine_name}::{index}")`, and the results get `requires`.
- **`resolve_archive`** (464–525) writes `HumbleResolution(splits=[...], requires=...)` whenever there are DLC names, edition components, or more than one result (lines 498–503).
- **`crawler._games_for_item`** (crawler.py:309–320) emits one `Game` per split, tied together with `GameGroup(id=machine_name, name=title)` and `requires`.

### 2. Why it was needed

The original request is in `ai/query.md`.
- Line 2221 is the `/plan` about the Dagon "DLC Pack" in the love-letter-to-lovecraft bundle. The pack lists 3 DLCs in its description, links a free base game, and carries a `DLC` badge. The request asks for the DLCs plus the base game as a requirement, and for a "Multiple…" option above "Other…" in the prompt.
- Line 1524 is the earlier `/plan` about items that are themselves several products (Frostpunk GotY, "Dead Cells + The Bad Seed DLC").

Git history, oldest first. The commit-message text below is quoted.
- `cfe06cb4b` (Aug 31 2026), "[humblebundle|parser] dlc packs":
  - Added `base_game_url`/`bundled_dlc_names` and `_parse_dlc_pack_details`.
  - Verified against the real `ourlife_beginningsandalways_dlcpack` and `adatewithdeathdeluxedlcpack` items from `archives/humblebundle/bundle/2026-08-12_handsome-husbandos/source.json`.
- `cc35d006a` (Aug 31 2026), "resolver split":
  - Made `resolve_item` return a list of resolved games.
  - Added `sources/prompting.py` with the shared "Multiple…" option.
  - Added `HumbleResolution.requires`/`splits`, `_games_for_item`, and moved `StoreCandidate` into `storefronts.py`.
- `2f2924254` (Sep 1 2026), "edition/sub resolution":
  - Added `_parse_edition_bundle_components` (Steelrising "Bastille Edition").
  - Added `steamdb` Sub (package) expansion via `parse_steamdb_sub_apps`.
  - Fixed `resolve_archive` writing a merged `ids=` entry instead of `splits=`.
  - Made the "Multiple…" flow interleaved.

The tests encode the same story.
- **Parser tests** in `tests/test_humblebundle_parser.py`:
  - Line 154, `test_parse_dlc_pack_details_extracts_base_game_and_dlc_list`, uses the real Our Life HTML.
  - Line 187, `..._returns_none_for_plain_description`.
  - Line 195, `test_bundle_page_wires_dlc_pack_details_onto_the_item`.
  - Line 252, `test_bundle_page_ignores_dlc_pack_shape_on_a_non_dlc_item`.
  - Lines 320–396 cover the Edition parser.
- **Resolver tests** in `tests/test_humblebundle_resolver.py`:
  - Line 348, `test_resolve_item_splits_a_dlc_pack_and_attaches_requires`.
  - Line 372, edition split.
  - Line 259, the steamdb Sub auto-expand.
  - Lines 449–537 cover "Multiple…" and `splits`.
- **Prompt tests** in `tests/test_prompting.py`, lines 38–144.

### 3. Resolver and prompt behaviour

**Search.** `StorefrontResolver` (resolver.py:221) searches storefronts via `STORE_SEARCH_URLS` (66–72) and parses results with `parse_store_candidates` (159–182).
- `_search_steam` (245–280) tries steampowered.com first. It falls back to steamdb.info only when there isn't exactly one candidate whose `normalized_title` equals the title.
- `_resolve_title` (299–432) runs these steps.
  1. It returns the cached entry if `mapping.games[cache_key]` exists (332–337).
  2. For each store in `item.redeem_on`, it searches and keeps the exact `normalized_title` matches.
  3. If there is exactly one exact match, it takes it silently, announcing it only when `allow_multiple=False` (372–374). If that match is a `steam:sub/<id>`, it expands into the Sub's member apps, each cached under `cache_key::N` (354–371).
  4. Otherwise it calls `self._choose(title, provider, candidates, allow_multiple=..., interleaved=True, known_names=...)` (380).
  5. A `None` answer means unresolved. A string goes through `parse_store_identity` and is re-asked if it is invalid. `EnterMultiple` triggers a loop of `_collect_name` and a recursive `_resolve_title` per name, cached under `cache_key::N` (392–411).
  6. If nothing resolved, it records `unresolved:source:humblebundle:<cache_key>` (423–425).
  7. The result is stored in `mapping.games[cache_key]` (427).

**Interactive vs `--non-interactive`.** The switch is in `src/game_collections/cli.py:801–915`, `scrape_humblebundle_command`.
- **Choosing the chooser (lines 828–833).** `--non-interactive` uses `lambda _title, _provider, _candidates, **_kwargs: None`. The default is `prompting.choose_store_candidate`.
- **Under `--non-interactive`.** Every non-unique title becomes `unresolved:source:humblebundle:<key>`. No chooser or name prompt runs, and a "Multiple…" can't happen.
- **The interactive prompt**, `choose_store_candidate` (`src/game_collections/sources/prompting.py:76–158`):
  - Menu: numbered candidates, then `Multiple…` (only if `allow_multiple`), then `Other…`. The default selection is "Other…", and a blank paste means unresolved.
  - `Other…` asks "Paste the store URL or direct ID; leave blank for unresolved".
  - `Multiple…` with `interleaved=True` returns an `EnterMultiple` marker. Otherwise it collects names and returns `ChosenNames`.
  - `collect_one_name` (48–73) asks "Name of one separate game (N so far) (blank to finish)" and rejects names already in `known_names`.
  - `announce_exact_match` (41–45) prints "Exact match found — id".
  - The resolver also takes injectable `collect_name` and `announce_exact_match` callables (resolver.py:224–237), which is how tests drive it.
- **Other consumers.** Green Man Gaming at cli.py:995–1040 uses the same `choose_store_candidate`. `search.py` uses the non-interleaved `ChosenNames` form.

**Caching.** `config/humblebundle-store-ids.yml` holds a `HumbleResolutionMap` (resolver.py:75–96, with `load_resolution_map` and `render_resolution_map` nearby).
- Plain items use `machine_name`; split components use `machine_name::N` (1-based).
- It is saved per offer by `on_offer` → `crawler.write_resolution_map` (crawler.py:476), before the list is written (cli.py:838–853). A later validation failure therefore can't lose answers.
- Unresolved keys are echoed at the end (cli.py:864–868).
- The README entry is `src/game_collections/sources/README.md` line 35. Line 42 notes that the weekly workflow runs `--non-interactive`. Lines 16, 19 and 24 cover `on_offer`, recovery and caching.

### 4. HTML structure examples

**The newest archive** (`archives/humblebundle/bundle/2026-10-21_15th-anniversary-scifi-exposure/`, `source.json` and `metadata.json`) has 9 items under `data.bundle_data.tier_item_data`.
- None of them has a `dlc` badge or a DLC `<li>` list: `crysisremastered`, `crysis2remastered`, `crysis3remastered`, `ghostrunner`, `ghostrunner2`, `marathon`, `robocop_roguecity_collection`, `xenonauts2`, and `charitywater`, which is not a game.
- The only `<li>` content is in `xenonauts2`: 10 bullets across 3 `<ul>`s, all feature marketing. For example: `<li>A massive variety of enemy types will keep you on your toes as you fight against a multitude of species...</li>`. These are interleaved with `<br><br>` prose. This is explainer text, and it is correctly not parsed, because the item has no `dlc` badge.
- `robocop_roguecity_collection` ("RoboCop: Rogue City - Collection") has no `<li>` at all. The bonus content is `<br>- The secondary weapon...` plain text. It was resolved by hand to `steam:bundle/61116` (config line 1001).
- The uncommitted config diff only adds `crysis*remastered`, `ghostrunner*`, `marathon` and `robocop_roguecity_collection`, all resolved to a single Steam ID. No `::N` split keys were added.
- A scan of every archived bundle found 39 items with `cta_badge.badge == "dlc"`. None are in the newest bundle.

**A real DLC list** (Dagon, `archives/humblebundle/bundle/2026-08-21_love-letter-to-lovecraft/source.json`, key `dagon_byhplovecraftdlcpack`, badge `{'badge':'dlc'}`):
```
<strong>This DLC Pack contains 3 DLCs for Dagon: By H.P Lovecraft. ... FREE <a href="https://store.steampowered.com/app/1481400/Dagon_by_H_P_Lovecraft/">here</a>.</strong>
<ul>
<li>Dagon - The Eldritch Box DLC</li>
<li>Dagon - The Little Glass Bottle DLC</li>
<li>Dagon - The Railway Horror DLC</li>
</ul>
<p class="bb_paragraph">...
```
The pattern is a leading `<strong>` sentence with a Steam `<a>`, then a `<ul>` of bare titles. Each `<li>` is exactly a full Steam product title, with no description.

Our Life (`2026-08-12_handsome-husbandos`, `ourlife_beginningsandalways_dlcpack`) has the same shape: six titles "Our Life: Beginnings & Always: ...". After the first `<ul>` come many single-`<li>` `<ul>`s of feature bullets such as `<ul><li>4 different periods of life to experience...</li></ul>`. These are ignored only because of the first-`<ul>` cutoff.

**Explainer lists that are wrongly treated as DLC lists.** For several items with a `dlc` badge, the first `<ul>` is a contents list or feature list, not a list of separate DLC titles. There is no Steam link either, so `base_game_url` is `None`. These are the Dying Light 2 cosmetic bundles in `2026-09-30_dying-light-2-stay-human-complete-dlc-bundle`.

For example, `dyinglight2stayhuman_breckenbundle`:
```
<strong> The bundle contains: </strong> <br>
<ul>
<li class="p1">Brecken Outfit — lead the way and move swiftly as one of the first runners.</li>
<li class="p1">Voltaic Wrench&nbsp;— shock your enemies by bashing their heads in.</li>
<li class="p1">Brecken’s Paraglider — when running is not enough, fly to your destination.</li>
</ul>
```
Its archived `metadata.json` records `bundled_dlc_names = ['Brecken Outfit — lead the way ...', 'Voltaic Wrench ...', ...]` and a three-way `splits`. All three splits resolved to the same `steam:2269820`, and `config/humblebundle-store-ids.yml` lines 359–364 hold `dyinglight2stayhuman_breckenbundle::1/::2/::3` all set to that ID. `dyinglight2-chickenbundle` is the same.

Other `dlc`-badged items with explainer or feature lists, which are likely wrongly parsed too:
- `monstertrain_thelastdivinitydlc`
- `warhammer_*collectorseditionupgrade`
- `agameofthrones_*`
- `terraformingmars-originalpromopack`
- `nottonight_onelove`
- `gloomhaven-soloscenarios_mercenarychallenges`
- `carcassonne_theprincessthedragonexpansion`

Their lists are feature or content bullets.

Reliable signals that separate a real DLC-pack list from an explainer list, from the examples above:
- A Steam `/app/` link plus an "includes N DLCs for ..." lead-in (this is how `base_game_url` gets set).
- A `<li>` that is a short bare title with no " — " prose.
- A `<li>` that starts with the base-game name.
- The `<li>` count matching "contains N DLCs".

I haven't proposed or made any code changes. This task was read-only.