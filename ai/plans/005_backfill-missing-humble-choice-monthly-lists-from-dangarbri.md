# Backfill missing Humble Choice monthly lists from dangarbri.tech

## Context

`lists/humblebundle/choice/` currently only has `2026-07.yml`, produced by the live
`game-collections scrape humblebundle` crawler (`src/game_collections/sources/humblebundle/crawler.py`).
Humble's own site doesn't expose past Choice months to guests, but
https://dangarbri.tech/humblechoice mirrors every month back to June 2023 (title,
genre, and a per-game `humblebundle.com/membership/<month>-<year>/<slug>` link).
The user wants a one-off script to backfill all the months that mirror covers
(2023-06 through 2026-06 — 37 months), reusing the same list/archive shape and
storefront-ID resolution the real crawler uses, and to fold the per-game
membership links into each list's `references` since the existing schema
already supports arbitrary name/url reference entries.

## Source page shape (verified via `curl`)

```html
<h2>June 2026 Games</h2>
<div class="games">
  <div class="game-card">
    <a target="_blank" href="https://www.humblebundle.com/membership/june-2026/theriftbreaker">
      <img .../>
      <p class="title">The Riftbreaker</p>
      <p class="game-genre">Indie Strategy Adventure Rpg Action Simulation</p>
    </a>
    <p class="game-extra">Must be redeemed by ...</p>
  </div>
  ...
  <div class="game-card"> <!-- subscription perk, not a game -->
    <a href=".../ignplus_choicecoupon_2025">
      <p class="title">Get One Month Of Ign Plus</p>
      <p class="game-genre"></p>  <!-- empty genre marks non-game perks -->
    </a>
  </div>
</div>
```

Heuristic: a `.game-card` with an empty `.game-genre` is a subscription/coupon
perk (IGN Plus, Boot.Dev, DC Universe Infinite), not a game — exclude it from
`games:` but keep it recorded in the archive JSON for completeness. Titles on
the page are odd-cased ("Octopath Traveler Ii", "Ign Plus"); apply a small
regex fix-up that re-uppercases standalone roman-numeral tokens (I–X) so
generated names read naturally.

## New script: `scripts/backfill_humble_choice.py`

Reuse existing project code rather than reimplementing:

- `HumbleHttpClient` (`crawler.py:58`) for a polite retrying fetch of the
  dangarbri page (own `User-Agent`).
- `MONTHS` dict (`crawler.py:34`) to turn `"June 2026"` into `2026-06`.
- `complete_game_list` / `resolve_title` (`src/game_collections/search.py`) with
  `StorefrontResolver(client.fetch, lambda *_: None)` (same non-interactive
  pattern as `search_command`, `cli.py:170`) and `providers=("steam",)`,
  `mode="blank"` — exactly what `complete_command` does, just driven
  in-process instead of via the CLI, so ambiguous titles fall back to
  `unresolved:store:steam:<slug>` for later manual review instead of guessing.
- `Game`, `GameList`, `Reference` (`src/game_collections/models.py`).
- `_atomic_write`, `_game_list_yaml`, `_json` (`crawler.py:201/224/218`) so
  output formatting/atomicity matches the real crawler exactly.

Flow:

1. Fetch `https://dangarbri.tech/humblechoice`; parse with a small
   `html.parser.HTMLParser` subclass into `{month_key: [{"title", "genre", "url"}]}`.
2. For each month, skip if `lists/humblebundle/choice/{month}.yml` already
   exists (unless `--refresh` is passed).
3. Split entries into `games` (non-empty genre) and `excluded` (empty genre,
   subscription perks) using the heuristic above; apply the roman-numeral
   casing fix to game titles.
4. Build a draft `{"games": [{"name": ..., "ids": []}, ...]}` and run it
   through `complete_game_list` to resolve Steam IDs, printing unresolved
   titles to stderr (same UX as `complete_command`).
5. Write `archives/humblebundle/choice/{month}/source.json` (raw scraped
   month: included + excluded entries, each with its dangarbri title/url) and
   `metadata.json` (resolved games with final IDs, excluded perks, crawl
   timestamp, `"source": "https://dangarbri.tech/humblechoice"`) — clearly a
   community/community-mirrored backfill, not the official Humble API payload
   the live crawler stores, so it intentionally does **not** reuse the strict
   `HumbleArchive` model.
6. Write `lists/humblebundle/choice/{month}.yml` via `GameList` + `_game_list_yaml`
   with references:
   - `Humble Bundle offer` -> `https://www.humblebundle.com/membership/{month-slug}`
   - `Backfill source` -> `https://dangarbri.tech/humblechoice`
   - `Crawl metadata` / `Crawl source` -> the two archive paths (relative, like
     the live crawler)
   - one reference per included game, e.g. `name: "The Riftbreaker page"`,
     `url: https://www.humblebundle.com/membership/june-2026/theriftbreaker`
7. Print a short per-month summary (games written, unresolved count).

CLI flags (argparse, kept minimal):
- `--all` — process every missing month found on the page.
- `--month YYYY-MM` — repeatable, process only these specific months.
- `--from YYYY-MM --to YYYY-MM` — process the inclusive month range.
- One of `--all` / `--month` / `--from`+`--to` is required (no accidental
  full-run default).
- `--refresh` — also rewrite months that already have a list file.
- `--dry-run` — parse + resolve but don't write any files, just print the
  summary.

## Docs

Add a short paragraph to `lists/README.md` under "Generated Humble lists"
noting the one-off `scripts/backfill_humble_choice.py`, that it sources
historical months from the community mirror dangarbri.tech/humblechoice
(official Humble pages don't expose past months to guests), and that its
archive JSON is a best-effort partial record rather than the full official
crawl payload.

## Verification

- Run `env UV_CACHE_DIR=/tmp/uv-cache uv run python scripts/backfill_humble_choice.py --month 2026-06 --month 2026-05`
  first to sanity check output shape on two months. The remaining 35 months
  are left for the user to trigger later with `--from`/`--to` or `--all`, since
  a full run makes ~290 Steam search requests and takes a while.
- `env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections validate` after any run.
- Spot-check the generated `lists/humblebundle/choice/*.yml` files by eye, and
  check the unresolved-titles stderr output for names needing manual
  `game-collections complete` follow-up.
- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest` (schema is unchanged, so this
  should be unaffected, but confirms nothing else broke).
