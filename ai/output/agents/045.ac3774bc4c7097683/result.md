## Findings

**1. Source of the log** — This is `game-collections scrape humblebundle` output, not isthereanydeal (despite the "Bundle X/Y" wording, which is stale/mismatched — see note below):
- `unresolved: <machine_name>` → `src/game_collections/cli.py:706-707` (numeric-looking Humble `machine_name`s, matching "unresolved: 332" etc.)
- `error: <context>: <exc>` → `cli.py:709-710`, fed by `HumbleCrawlReport.errors`, built at `src/game_collections/sources/humblebundle/crawler.py:211` (`errors.append(f"{url}: {error}")`) inside `crawl_humble_offers` (`crawler.py:146-215`)
- `Archived <NAME>: N file(s)` → `on_offer` callback, `cli.py:685`
- `Wrote N file(s) for N offer(s); N unresolved game(s).` → `cli.py:712-715` (exact match, unique to the Humble command; isthereanydeal's equivalent at `cli.py:983` has no "unresolved" clause)
- Note: the literal `Bundle {index}/{total}: <slug>` wording currently only exists in `isthereanydeal/crawler.py:304,310`; Humble's own progress log at `crawler.py:183,197` says `Offer {index}/{total}: {url}` (confirmed via `git log -S "Bundle {index}/{total}"` — never present in humblebundle/crawler.py). The rest of the log (unresolved counts, "Wrote N…offer(s)") is unambiguously Humble's format, so this looks like a slightly stale/hand-edited log or a since-renamed log line — worth flagging to the user rather than treating as settled.

**2. The duplicate-name validator** — `src/game_collections/models.py`, `GameList.validate_games` (`@model_validator(mode="after")`, lines 162-167):
```
names = [game.name.casefold() for game in self.games]
if len(names) != len(set(names)):
    raise ValueError("list contains duplicate game names")
```

**3. Where the duplicate arises for Humble** — `write_humble_offer` in `src/game_collections/sources/humblebundle/crawler.py`:
- Tier loop `crawler.py:347-362` and Choice-pool loop `crawler.py:308-318` dedup only by **resolved storefront ids** (`seen_ids`/`seen_pool_ids`, via `_item_all_ids`, `crawler.py:249-254`), never by `Game.name`.
- Root cause: unresolved items get a **per-item-unique** placeholder id, `f"unresolved:source:humblebundle:{cache_key}"` where `cache_key == item.machine_name` (`resolver.py:417`, cache key set in `resolve_item`/`resolve_archive`, `resolver.py:427-518`). Two separate items with the identical display title but different `machine_name`s (e.g. duplicate/edition listings, both still unresolved — consistent with the same run logging unresolved 332/333/337/346) get distinct ids, so the ids-based `seen_ids` check never catches the name collision, and it only surfaces later as a `GameList` validation error at write time.

**4. Reusable dedup pattern** — `src/game_collections/sources/common.py:157` and `:216-219` (`find_matching_game`/`merge_game_list`) already do `game.name.casefold()` comparisons and could be reused to add a name-based dedup guard. Note `greenmangaming/crawler.py:269-276` has the identical ids-only dedup pattern (same latent gap, not a fix), and `isthereanydeal/crawler.py:597-604` also only dedups by `item.ids`.