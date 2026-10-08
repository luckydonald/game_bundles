# Fix: scheme-less vendor URL breaks Humble scrape

## Context
`scrape humblebundle` fails on `/games/2d-rewind-collection-from-s2-games`: the page's
`publisher-url`/`developer-url` is `www.starlight.org` (no scheme), and `HumbleLink.url: HttpUrl | None`
rejects it. The parser passes scraped strings through `_optional_url`, which only strips whitespace.

## Change
1. `src/game_collections/sources/humblebundle/parser.py` `_optional_url` (~line 306): after stripping,
   - `//host/...` -> prefix `https:`
   - no `://` present -> prefix `https://`
   - otherwise unchanged.
   Add a short comment explaining Humble vendors enter bare hostnames. Bare `# end` comments, no private-prefixed new names.
   This also covers the other callers (charity url/logo_url, cover art). Values that are still invalid keep failing loudly (strict models, no silent dropping).
2. `tests/test_humblebundle_parser.py`: add a test (next to the existing line ~59 developer fixture) with `"publisher-url": "www.starlight.org"` asserting `https://www.starlight.org/`, plus a `//host` case and an already-schemed case unchanged.
3. No model/schema change, so no schema regeneration (confirm with `tests/test_schema.py`).

## Verification
- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_humblebundle_parser.py tests/test_schema.py -q`
- Full `uv run pytest`.
- Optionally re-run `game-collections scrape humblebundle --url https://www.humblebundle.com/games/2d-rewind-collection-from-s2-games` (network; ask first).
- Commit per repo's commit-with-lplp-style (explicit paths, message via `ai/git/pending-commit.md`).
