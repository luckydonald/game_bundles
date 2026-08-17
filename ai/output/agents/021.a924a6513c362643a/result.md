No custom `__eq__`/`__hash__`/frozen config — just plain pydantic `BaseModel` equality (field-by-field), not hashable by default. No dedup/merge helper for `Reference` lists exists anywhere in the codebase (only `merge_game_list` for `Game` entries).

## Report

**`merge_game_list`** (`src/game_collections/sources/common.py:72-91`): merges only `games` (matched by `name.casefold()`, preserving existing manual edits + appending new ones). It explicitly takes `name`/`tier`/`pick_quota`/**`references`** wholesale from `fresh` via `fresh.model_copy(update={"games": merged_games})` — so any existing `references` on disk are fully discarded and replaced by whatever the current crawl produced, with no merging/appending logic at all.

**Write paths and reference construction:**
- `humblebundle/crawler.py:307-311,351-361` — `references=[Reference(name="Humble Bundle offer", url=archive.url), Reference(name="Crawl metadata", path=...), Reference(name="Crawl source", path=...)]`. This is the **only** source that routes through `_write_merged_game_list`/`merge_game_list` (`common.py:249-260`).
- `isthereanydeal/crawler.py:472-476,512-516` — `references=[Reference(name="isthereanydeal.com bundle", url=archive.url), "Crawl metadata", "Crawl source"]`. Writes via `atomic_write(path, render_game_list_yaml(...))` directly (line 479, 519) — **no merge call at all**, so re-crawling fully overwrites the file, references included.
- `greenmangaming/crawler.py:274-277` and `dailyindiegame/crawler.py:280-283` — same three-reference shape (source URL + metadata + source archive paths), also written via plain `atomic_write` (greenmangaming.py:281, dailyindiegame.py:287) with **no merge**.

**Where re-runs/cross-source overwrites lose information:**
1. isthereanydeal, greenmangaming, and dailyindiegame never merge at all — any manual edits to `references` (or `games`) on those lists are clobbered on every re-crawl, not just the `references` field.
2. `_existing_list_match` (`isthereanydeal/crawler.py:402-419`) does a substring/path-based dedup: if a bundle is "already covered by a dedicated scraper" (e.g. a humblebundle-authored list at a date-prefixed path), the ITAD crawl is **skipped entirely** (`write_itad_offer` line ~440, "Skipped … already covered by …") rather than merged — so no cross-source mirror reference is ever added to an existing humble list, and conversely if ITAD crawls first and Humble later merges via `merge_game_list`, Humble's `references` fully replace ITAD's, dropping the `isthereanydeal.com bundle` URL reference.
3. Even within humblebundle's own merge path, since `merge_game_list` overwrites `references` unconditionally from `fresh`, any hand-added reference (e.g. a manually appended mirror URL) is lost on the next scrape.

**`Reference` model** (`models.py:90-108`): plain Pydantic `StrictModel` (no `frozen`/custom `__eq__`/`__hash__`) with `name: NonEmptyString`, `path: ReferencePath | None`, `url: AnyHttpUrl | None`, validated to require at least one of `path`/`url`. Equality is default Pydantic field-wise equality; not hashable. No existing helper anywhere dedupes/merges `Reference` lists.

**`lists/README.md`**: documents `references` syntax/shape (`path`/`url`/both, relative-path rules) but states no policy on de-duplication, append-vs-replace, or "one entry per source" — no documented merge convention exists.