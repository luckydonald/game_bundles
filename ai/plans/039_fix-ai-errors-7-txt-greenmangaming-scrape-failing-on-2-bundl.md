# Fix `ai/errors/7.txt`: GreenManGaming scrape failing on 2 bundles

## Context

`ai/errors/7.txt` is the output of a `game-collections scrape --git greenmangaming` run (already committed as `8bde6c46c`, "Manual `game-collections scrape --git greenmangaming` run."). Two bundles failed to write with:

```
error: 2k-collection: 1 validation error for GameList
  Value error, list contains duplicate game names
error: destiny-2-expansion-bundle-2025: 1 validation error for GameList
  Value error, list contains duplicate game names
```

(The 4 `unresolved: 332/333/337/346` lines are unrelated, pre-existing, benign — a whole-map snapshot of already-known unresolved games from *other*, successfully-archived bundles in the same run. No action needed there.)

### Root cause (verified against the committed archive JSON + live Steam pages, not guessed)

`archives/greenmangaming/bundle/2k-collection/metadata.json` and `.../destiny-2-expansion-bundle-2025/metadata.json` each contain one or more GMG products whose `resolution.splits` list has **two entries sharing the exact same display name** (with different Steam ids):

- `2k-collection`, product `25` "BioShock: The Collection" → 4 splits, ALL literally named `"BioShock: The Collection"`. Only `steam:sub/127635` is a real, title-matching Steam package (verified live); `steam:sub/127633` and `steam:bundle/1417` (used twice) both redirect to the Steam homepage, i.e. they don't exist.
- `destiny-2-expansion-bundle-2025`, product `16` "Bungie 30th Anniversary" → 2 splits both named `"Destiny 2: Bungie 30th Anniversary"` (`steam:1656370` and `steam:sub/588604` — both real, just the same content sold as an app and as a package).
- `destiny-2-expansion-bundle-2025`, product `14` "Year of Prophecy Edition" → 4 splits, two of them both named `"Destiny 2: Year of Prophecy Edition"` (`steam:3186500` "Year of Prophecy Ultimate Edition", `steam:3205620` "...Ultimate Edition Upgrade"), one named `"Destiny 2: The Edge of Fate"` (`steam:3186490`, which is a duplicate of product `15` in the same tier), and one named `"Destiny 2: Renegades"` (`steam:3186540`, a genuinely distinct, correctly-resolved game).

`GameList.validate_games` (`src/game_collections/models.py:162-167`) correctly rejects duplicate `game.name` values — this is working as intended; the bad *data* is the problem, not the validator.

This is stale interactive-resolution data: `config/greenmangaming-store-ids.yml` only has the orphaned per-split cache keys (`14::1`..`14::4`, `16::1`, `16::2`, `25::1`, `25::2::1`, `25::2::2::1`, `25::2::2::2`) — the *top-level* keys `14`, `16`, `25` were never persisted (by design: `StorefrontResolver._resolve_title` in `src/game_collections/sources/greenmangaming/resolver.py:231-238` only caches leaf, non-split resolutions). That top-level cache miss means a `--refresh` run re-resolves these 3 products from scratch using today's `StorefrontResolver`, which already guards interactive "Multiple…" splits against reusing an in-flight name via `known_names` (`resolver.py:192-198`) — protection that plainly wasn't in place (or wasn't honored) when this old split data was created. Since the whole-archive on-disk cache (`archives/greenmangaming/bundle/<slug>/{metadata,source}.json`) is what's actually replayed on every non-`--refresh` run (`crawl_gmg_offers`, `crawler.py:183-199`), the corruption keeps reproducing every scrape until that cache is bypassed.

No source code is at fault, so **no code changes** are planned — this is a data-correction operation using the existing CLI.

## Fix

Re-run the scrape for just these two bundles with `--refresh` (bypasses the stale whole-archive cache) and `--non-interactive` (no human present in this session to answer disambiguation prompts):

```console
env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections scrape --git greenmangaming \
  --url https://www.greenmangamingbundles.com/bundles/2k-collection/ \
  --url https://www.greenmangamingbundles.com/bundles/destiny-2-expansion-bundle-2025/ \
  --refresh --non-interactive
```

Expected effect:
- Every already-cleanly-resolved product in these two bundles (`The Quarry`, `Rollerdrome`, `Topspin 2K25`, `LEGO® 2K Drive`, `Risk of Rain Returns`, `Tiny Tina's Wonderlands`, `XCOM: Ultimate Collection`, `Destiny 2: The Final Shape/Shadowkeep/Beyond Light/Witch Queen/Forsaken/Lightfall/Edge of Fate`) is re-used unchanged from `config/greenmangaming-store-ids.yml`'s existing top-level cache entries.
- Products `14`, `16`, `25` get freshly re-resolved. In `--non-interactive` mode, an exact single title match resolves directly; anything ambiguous becomes a single `unresolved:source:greenmangaming:<id>` marker (no splits), which cannot collide on name. Either outcome fixes the crash.
- `write_gmg_offer` succeeds for all tiers of both bundles, replacing the current partial output (`lists/greenmangaming/bundle/2k-collection/tier-1.yml` only, `lists/greenmangaming/bundle/destiny-2-expansion-bundle-2025/tier-1.yml` only) with the full, correct set of tier files, and the `--git` session autostashes/commits the result the same way the original run did.

### Verification

1. Confirm the command exits 0 and prints no `error:` lines for these two bundles.
2. Read the regenerated `lists/greenmangaming/bundle/2k-collection/tier-*.yml` and `.../destiny-2-expansion-bundle-2025/tier-*.yml` and confirm: no duplicate `name:` entries, `BioShock: The Collection`/`Bungie 30th Anniversary`/`Year of Prophecy Edition` each appear once (either resolved or as a single `unresolved:` marker).
3. Run `env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections validate` to confirm the whole `lists/` tree still loads cleanly.
4. Report which (if any) of the 3 products landed as `unresolved:` so the user can follow up later with `game-collections complete <file> --mode unresolved --provider ...` — deliberately not hand-picking Steam ids myself for the ambiguous ones (esp. "Year of Prophecy Edition" vs "...Ultimate Edition" vs "...Ultimate Edition Upgrade"), since that's a real judgment call for the user/reviewer, not something to silently guess into the resolution map.

## Out of scope (flagged, not touched)

- The already-staged, unrelated working-tree changes to `src/game_collections/launchers/{base,steam/adapter,steam/io}.py` and `tests/test_steam_io.py` (stale-Steam-pipe confirmation handling) are pre-existing uncommitted work, untouched by this fix.
- `humblebundle/crawler.py` has the structurally identical `_games_for_item`/`seen_ids`-only dedup pattern and could in theory hit the same class of bug, but there's no evidence it has — not touching it speculatively.
