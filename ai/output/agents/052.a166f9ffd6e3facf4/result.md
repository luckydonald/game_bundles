**Summary:** Raw HTML is fetched and parsed in memory and never saved as a file. `source.json` is only written after parsing and resolution succeed, so a parse failure leaves nothing on disk.

Paths below are relative to `/Users/user/Documents/programming/Python/game_bundles/src/game_collections/` (`sources/...` and `cli.py`). I found no separate scrape/runner module; the CLI in `cli.py` drives `crawler.py`.

## (1) Fetch, parse and write order

**Fetch**
- `HumbleHttpClient.fetch` (`sources/humblebundle/crawler.py:86-109`) returns `response.text` (HTML). It retries on 429/5xx and raises `HumbleCrawlError` after 3 attempts.
- It is called in `crawl_humble_offers` (`crawler.py:147`):
  - the index: `parse_bundle_index(fetch(BUNDLES_URL))` at `:175`
  - each offer page: `page = fetch(url)` at `:186`

**Parse**
- Parsing runs right after the fetch, in the same `try` (`crawler.py:187-191`): `parse_choice_page(page, observed)` for `/membership`, otherwise `parse_bundle_page(page, listing, observed)`.
- Each returns `(HumbleArchive, source_dict)`. In `parse_bundle_page` the `HumbleArchive(...)` constructor is at `parser.py:602` and the return is `return archive, {"bundle_data": bundle, "listing": listing_data}` at `:626`.
- The Choice equivalent is at `parser.py:748-776`.
- The "source" is the extracted embedded JSON (`bundle_data` and `listing`), not the HTML.

**Resolve, then write**
- Resolution is `resolver.resolve_archive(archive, mapping, log=log)` at `:203`, or a cached copy.
- `on_offer(offer)` fires at `:208-209`. The CLI's `on_offer` (`cli.py:836-850`) calls `write_resolution_map`, then `write_humble_offer`.
- `write_humble_offer` (`crawler.py:290-308`) writes both archive files together:
  - `atomic_write(metadata_path, dump_versioned_json(CURRENT_VERSION, archive.model_dump(by_alias=True, mode="json")))` at `:306`
  - `atomic_write(source_path, dump_versioned_json(CURRENT_VERSION, offer.source))` at `:307`
- The lists YAML is written after that (`:350` and `:413`, via `_write_merged_game_list`).

**Consequence:** the order is fetch, parse into models, resolve, then write `metadata.json` and `source.json` together, then the list YAML. There is no write-before-parse step, so a pydantic failure at `parser.py:602` leaves nothing on disk for that offer. Raw HTML and the extracted JSON are both lost.

## (2) Resume and cache

- The page is always fetched, even when a cache exists. The README says so at `sources/README.md:22`, and the docstring at `crawler.py:159-165` explains why: the cache key (`_offer_key`, `:219-237`) depends on parsed fields. The cache only skips `resolver.resolve_archive`, which does one storefront search per game.
- Cache check (`crawler.py:192-206`): `_archive_paths(archive_root, archive)` is built from the freshly parsed archive, then `load_cached_archive(HumbleArchive, metadata_path, source_path, current_version=CURRENT_VERSION)` is called. A hit reuses the cached resolved archive and source.
- `load_cached_archive` is `sources/common.py:54-91`. It returns `None`, treated as a miss, when:
  - either `metadata.json` or `source.json` is missing (`:72`)
  - the envelope version differs (`:77-79`): `version.sort_key() != current_version.sort_key()`
  - the data fails validation (`:84`: `model_validate_json(json.dumps(data))`)
  - the JSON is invalid, caught by `except (OSError, ValueError, ValidationError): return None` at `:87`
- The cache does not migrate stale files. `cli._migrate_source_archives` (`cli.py:139-159`) runs first in each scrape command (`cli.py:826`) and migrates the whole `archives/<source>/` tree.
- `--refresh` / `--no-cache` is at `cli.py:816-821`. It passes `archive_root=None if refresh else archive_root` (`cli.py:861`), so the cache check at `crawler.py:193` is skipped. A refresh then redoes the resolution and overwrites the existing archives.
- Because `archive_root=None` skips the cache check, every offer is re-resolved on refresh.
- The same `archive_root` parameter is a read-cache gate and has no other role in the crawl.

## (3) Pydantic ValidationError handling

- Pydantic v2's `ValidationError` subclasses `ValueError`. That is why the catch in `crawl_humble_offers` already covers it. I did not verify this against the installed pydantic version.
- The catch is `except (OSError, ValueError, HumbleCrawlError) as error: errors.append(f"{url}: {error}")` at `crawler.py:211-212`. It is per offer, so the loop continues with the next URL.
- The error text is the multi-line pydantic message. For example, the `HumbleArchive(...)` constructor at `parser.py:602` or the `HumbleItem` built in `_bundle_item` (`:408`) can raise it. Hand-raised parser errors are `HumbleParseError(ValueError)` (`parser.py:57`).
- The CLI prints each one as `error: <url>: ...` (`cli.py:873-874`). If `report.errors` is non-empty it then exits with code 1 (`:880-881`), after printing "Wrote N file(s)...".
- The outer `except (OSError, ValueError, RuntimeError)` at `cli.py:883` prints the bare error and exits 1.
- The `finally` block (`cli.py:886-904`) still runs `finish_scrape_git_session`, so a git commit happens for offers that succeeded.
- Nothing is persisted for the failed offer. There is no raw payload, no `source.json` and no record of the failure.

There is one asymmetry. The index fetch at `crawler.py:177` has the same catch, but its error is formatted as `f"{BUNDLES_URL}: {error}"`.

## (4) Archive layout

For Humble, `_archive_paths` (`crawler.py:240-248`) gives:
- `archives/humblebundle/choice/<YYYY-MM>/{metadata.json,source.json}`, for example `2026-06`
- `archives/humblebundle/bundle/<YYYY-MM-DD>_<slug>/{metadata.json,source.json}`, for example `bundle/2026-06-17_upload-vr-summer-2026/`

The key comes from `_offer_key` (`:219-237`):
- Choice: derived from `machine_name` matching `<month>_<year>_choice`.
- Bundle: `dates.start or dates.end` (a UTC date) plus the URL slug, which must match `[a-z0-9][a-z0-9-]*`.
- `_offer_key` raises `HumbleCrawlError` if the bundle has neither date.
- Because the directory name depends on parsed dates, a raw file cannot be saved at a stable key before parsing succeeds. A recovery mode would need a different key, for example the URL slug.

Both files are written as `dump_versioned_json` envelopes. The `Versioned` envelope shape is `{"version": [...], "data": {...}}` (`sources/common.py:94-97`). `metadata.json` holds `archive.model_dump(by_alias=True, mode="json")`; `source.json` holds `offer.source`.

Lists are written separately: `lists/humblebundle/choice/<key>.yml` and `lists/humblebundle/bundle/<key>.yml`. The list YAML references both archive files through `Reference(path=...)` entries.

## README coverage

`sources/README.md:11-25` documents the resume behavior, the `log`/`on_offer`/`archive_root` parameters, and `--refresh`.
- Line 17 says a hit requires valid JSON, an exact envelope version, and data that still validates.
- Line 22 says Humble's page is always fetched.
- It says nothing about what happens to a page that fails to parse. The README does not mention raw-HTML retention or any recovery mode.

## Shared pattern for a generic recovery mode

All five sources use the same pattern:
- Each has `_archive_paths(archive_root, key) -> (metadata.json, source.json)` under `archives/<source>/bundle/<key>/`. Humble also has `archives/humblebundle/choice/<key>/`.
  - `sources/greenmangaming/crawler.py:137`
  - `sources/dailyindiegame/crawler.py:160`
  - `sources/isthereanydeal/crawler.py:268`
  - `sources/dekudeals/crawler.py:117`
- Each calls the same `load_cached_archive(Model, metadata, source, current_version=CURRENT_VERSION)`:
  - `sources/dailyindiegame/crawler.py:220`
  - `sources/greenmangaming/crawler.py:196`
  - `sources/isthereanydeal/crawler.py:315`
  - `sources/dekudeals/crawler.py:218`
- Each catches `except (OSError, ValueError, <Src>CrawlError)` per offer and appends to `errors`:
  - `sources/dailyindiegame/crawler.py:245`
  - `sources/greenmangaming/crawler.py:232`
  - `sources/isthereanydeal/crawler.py:387` (also catches `ItadParseError`)
  - `sources/dekudeals/crawler.py:277` (also catches `DekuParseError`)
- The CLI wiring is identical, with `archive_root=None if refresh else archive_root` in `cli.py` at `:948`, `:1037`, `:1142` and `:1229`.

A difference that matters for key choice: for dailyindiegame, greenmangaming, isthereanydeal and dekudeals the key is known before the fetch (bundle number, slug or id), so a recovery file could be stored at a stable key. Humble's key is only known after parsing.

A generic hook would fit in `sources/common.py` and be called from each crawler's `except` block, passing the fetched payload and the target URL.