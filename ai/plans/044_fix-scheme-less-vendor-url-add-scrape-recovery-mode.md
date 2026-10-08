# Fix scheme-less vendor URL + add scrape recovery mode

## Context

`scrape humblebundle` fails on `/games/2d-rewind-collection-from-s2-games`: `publisher-url` is `www.starlight.org` (no scheme) and `HumbleLink.url: HttpUrl | None` rejects it. There are two problems.

1. The parser passes scraped strings through `_optional_url` (parser.py ~306), which only strips whitespace.
2. When model construction fails (parser.py:602 / `_bundle_item`), nothing is persisted. The page is fetched, the embedded JSON extracted, the pydantic build raises, `crawl_humble_offers` (crawler.py:211) records the error, and the next run must re-fetch. `metadata.json`/`source.json` are only written after parse and resolve (`write_humble_offer`, crawler.py:290).

## Part 1: URL normalization

In `_optional_url` in `src/game_collections/sources/humblebundle/parser.py`, after stripping, prefix `//host/..` with `https:` and prefix values without `://` with `https://`; leave everything else unchanged.
Add a comment explaining that Humble vendors type bare hostnames.
Still-invalid values keep failing loudly. This also covers charity url/logo_url and cover art. No model or schema change.

## Part 2: Recovery mode

The *extracted* payload (the `source` dict: `{"bundle_data", "listing"}` for bundles, the Choice equivalent) is what the models are built from.
Persist it when the build step fails, and on the next run build from it instead of re-fetching.

- New module `src/game_collections/sources/recovery.py` (own module, no private-prefixed names), generic so other sources can adopt it later (they share the same crawler shape and `common.py` helpers).
- The payload stays in a separate holding dir, `archives/<source>/recovery/`, never in the real `bundle/`/`choice/` archive dirs. Once it parses and is written to its proper place, the recovery file is deleted.
- `write_recovery(root, url, payload, error)` writes `archives/<source>/recovery/<url-slug>.json` as a `dump_versioned_json` envelope via `atomic_write` from `common.py`.
- A strict `RecoveryRecord` model holds `url`, `observed_at`, `payload` (the extracted source dict), and error details for easier fixing.
- The error details are the exception type and full message, plus for a pydantic `ValidationError` the structured `errors()` list (loc, msg, type, input), so the offending field is visible without rerunning (e.g. `developers[0].url = 'www.starlight.org'`).
- The error is refreshed on every failed retry.
- The record is keyed by URL slug because Humble's normal archive key (`_offer_key`) depends on parsed dates and is unknown on failure.
- `load_recovery(root, url)` returns the record or `None`; an invalid or version-mismatched envelope is `None`, which falls back to a normal fetch.
- `clear_recovery(root, url)` removes the file.
- Parser (`parser.py`): split `parse_bundle_page`/`parse_choice_page` into (a) extract the embedded JSON from the HTML and (b) build `(HumbleArchive, source)` from that payload, so (b) can run from a saved payload. I need to read the parser to find the clean seam. Extraction errors (no payload found) stay non-recoverable since there is nothing to save.
- Crawler (`crawl_humble_offers`, crawler.py ~186-212): per offer, use the recovery file if one exists (skipping `fetch`), else fetch and extract. On `ValueError`/`ValidationError` from step (b), write the recovery file and then append the error as today. On success, clear the recovery file. Log "Using recovered payload for <url>".
- `--refresh` ignores and overwrites recovery files, consistent with its refetch meaning.
- Gitignore `archives/*/recovery/` since it is transient failure state, so `--git` never commits it.
- Docs: `sources/README.md` resume section (~line 17-22, currently silent on failures) and the root README `scrape humblebundle` paragraph.

Scope: implement for Humble now with the generic helper. Other sources are a follow-up, and adoption is simple because their keys are known before the fetch.

## Tests

- `tests/test_humblebundle_parser.py`: scheme-less, `//host`, and already-schemed URLs (near the fixture at ~line 59).
- Recovery module: round-trip plus a corrupt-file case.
- Crawler: with a fake fetch, the first run's build fails, so the recovery file (with error details) is written and the error reported. The second run succeeds without calling fetch, writes the archive and list, and removes the recovery file. Use sanitized fixtures.

## Verification

- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_humblebundle_parser.py tests/test_schema.py -q`, then the full suite.
- `game-collections validate`; schemas are unchanged because no public model changes.
- Optional live check (ask first, network): scrape the 2d-rewind URL.
- Commit per the repo's lplp style (explicit paths, message via `ai/git/pending-commit.md`).
