# Game Collections

Game Collections is a Python resource for maintaining portable lists of games and synchronizing fully owned lists into launcher libraries. The initial launcher is Steam; the list format and synchronization contracts are designed for later GOG, Epic, or other integrations.

The original use case is keeping bundles such as **Humble Bundles** together in a Steam library.

## Install

Python 3.14 or newer and [uv](https://docs.astral.sh/uv/) are required.

## List format

Lists live below [`lists/`](lists/). Their ID is their path relative to that directory without `.yml`: `lists/valve/the-orange-box.yml` is `valve/the-orange-box`.

```yaml
# yaml-language-server: $schema=../../schemas/game-list.schema.json
schema: 1
name: The Orange Box
references:
  - name: Valve bundle page
    url: https://store.steampowered.com/bundle/232/Valve_Complete_Pack/
games:
  - name: Half-Life 2
    ids: [steam:220]
  - name: Portal
    ids: [steam:400]
```

Every file is validated by strict Pydantic models. The committed [JSON Schema](schemas/game-list.schema.json) is generated from those models and supplies IDE completion and diagnostics. See [`lists/README.md`](lists/README.md) for contribution details.


## Dev Setup

```console
uv sync --extra test
uv run game-collections validate
uv run pytes
```

Common commands:

```console
uv run game-collections list
uv run game-collections search "Portal"
uv run game-collections complete my-list.yml
uv run game-collections complete --store gog,epic --mode missing my-list.yml
uv run game-collections schema
uv run game-collections scrape humblebundle
uv run game-collections scrape dailyindiegame
uv run game-collections scrape greenmangaming
uv run game-collections eligible steam
uv run game-collections sync steam
uv run game-collections sync steam --mode any --tiers all
uv run game-collections sync steam --log-skips
uv run game-collections sync steam --apply
uv run game-collections restore steam ~/Desktop/game-collections-steam-<timestamp>
uv run game-collections apply steam
uv run game-collections migrate-tiers
```

Set `STEAM_WEB_API_KEY` for ownership lookup. By default, the most recently used account in Steam's `loginusers.vdf` is selected. `--steam-id`, `--steam-root`, `--lists-root`, and `--output-dir` provide explicit overrides.

`eligible steam` and `sync steam` print eligible lists and the planned-change count by default. Pass `--log-skips` to also print every skipped list with its missing or unsupported IDs. `sync steam` prints one progress line per list file while collecting `lists/**/*.yml`; `apply steam` shows a progress bar in its picker window while doing the same.

`sync steam` defaults to `--mode all --tiers highest`. `--mode all` requires every Steam ID in a list to be owned, while `--mode any` requires at least one and exports only the owned Steam IDs; games without Steam IDs do not affect either match mode. `--mode none` skips ownership matching entirely - every list that reaches planning (after selection-config filtering) is treated as eligible outright, even a `pick_quota` list that hasn't met its quota - so it only makes sense combined with a curated `--selection-config` (typically from `apply steam`'s picker) that already narrows things down to what you actually want synced. `--tiers highest` groups sibling lists by bundle directory using each list's `tier:` field (a single-tier bundle has no `tier:` field and is always included) and keeps only the numerically highest matching tier per directory. Use `--tiers all` to export every matching tier. Every bundle-writing scraper sets `tier:` itself; `game-collections migrate-tiers` (`--apply` to write, dry-run by default) brings already-generated `lists/**/*.yml` files onto this convention — a lone tier is renamed to `bundle.yml` with no `tier:` field, siblings become `tier-1.yml`, `tier-2.yml`, ... with the field set.

`eligible steam` and `sync steam` also accept `--source installed` to skip the Web API and `STEAM_WEB_API_KEY` entirely, approximating ownership from locally installed games (`steamapps/libraryfolders.vdf` + `appmanifest_*.acf`). This only sees what's currently installed, not everything the account owns, so owned-but-uninstalled games are reported as missing; there is no local file that exposes the full owned/licensed games list, and `STEAM_WEB_API_KEY` itself can never be read from local Steam files — it's an account secret from Valve's web dev portal.

`eligible steam` and `sync steam` also accept `--source collection` (or just `--collection NAME`, which implies it) to read ownership from a manually curated local Steam collection instead of the Web API. `--collection` defaults to a collection named `manual-all` when its value is omitted. Steam has no local file exposing the full owned/licensed games list (that's why `--source installed` only sees what's installed), and Steam's own "All Games" view isn't a stored collection either — it's computed by the client. So if you want a real local snapshot of everything you own, you maintain it yourself as a plain (non-dynamic/non-filter) collection and point `--collection` at it. To create one named `manual-all`:

1. Open your Steam Library.
2. Select every game on the left (click the first, scroll to the bottom, then shift-click the last).
3. Click and hold any of the now-highlighted tiles and drag it into the main pane.
4. If you're not already on the collections page, hover the "DRAG and HOLD HERE to view All Collections" area in the top-left.
5. Drop onto an existing `manual-all` collection, or onto the "+ DRAG HERE TO CREATE A NEW COLLECTION" tile.
6. In the **New Collection** dialog, enter the name `manual-all` and click **CREATE COLLECTION**.
7. Close Steam before running `game-collections` against it.

`game-collections apply steam` is a graphical, interactive variant of `sync steam`: it opens a full-screen [Textual](https://textual.textualize.io/) picker (needs the optional `tui` extra: `uv sync --extra tui`) over every discovered bundle, letting you filter by item-count range and date range and manually check/uncheck individual bundles or whole source/types at once, before continuing through the exact same plan/stage/confirm/apply flow as `sync steam --apply`. Bundles are grouped into a tree by source (e.g. `humblebundle`, `fanatical`, ...): each row shows an expand arrow first, then a `[ ]`/`[x]`/`[-]` (mixed) checkbox. `enter`, or a mouse click directly on the checkbox glyph, selects/deselects the node under it — on a source node this toggles every bundle in it at once (an easy way to drop, say, all of `dailyindiegame` in one keystroke), on a bundle it toggles just that one; clicking the arrow (or elsewhere on the row) only ever expands/collapses, never toggles the checkbox. `+`/`-` or `left`/`right` expand/collapse a source; `left` on an already-collapsed bundle jumps back up to its source, Finder-style. `shift+left`/`shift+right` expand/collapse the node under the cursor *and everything under it*; `ctrl+left`/`ctrl+right` do the same for the whole tree at once.

The item-count/date filters, `tiers: highest`, and `mode`'s ownership gate (`any` excludes a bundle with 0 owned games; `all` excludes any bundle that isn't *fully* owned) are all one "filtered out or not" concept, with no separate tracking of why a given bundle is excluded: a bundle failing any of them is deselected (one-way - widening a filter back doesn't re-select anything, you'd have to `enter` it again) and, by default, simply isn't in the list the tree is built from. A `show filtered (as unchecked)` checkbox adds them back to that list too, unchecked, so you can review and manually check any of them back in - but if you turn it back off, they're filtered out again, full stop; anything you'd checked among them just isn't part of the result anymore, exactly as if it'd never been checked. Bundles that don't fail any filter are always shown, checked or not. Switching `tiers` to `highest` immediately unchecks every non-highest sibling tier (and switching back to `all` rechecks them), so the picker's checkmarks preview the same "highest tier per bundle directory" grouping `--tiers` applies at plan time. `ctrl+a` selects or deselects every bundle currently passing the item-count/date filters in one keystroke (toggling: all-selected → none, anything else → all).

Expanding a bundle further reveals its individual games as a third tree level; expanding a game one level further shows a menu of `Store: <provider>` entries (one per storefront it's known on, e.g. Steam/GOG/Epic) and a `Launch on Steam` entry, greyed out and inert if the game has no Steam ID. `enter` on any of these opens it via the OS's default handler — a browser for store pages, the local Steam client for `steam://rungameid/<appid>`. The picker resolves your Steam ownership up front (via the same `--source`/`--collection`/`--api-key` as `sync steam`) so it can mark each bundle with an `(owned/total)` game count and grey out individual games you don't own yet, though the submenu (store links, launch) stays reachable either way; if Steam access isn't available (missing credentials, no local install, etc.) the picker still opens and can still be cancelled, just without those marks - a warning is printed instead of failing outright. The picker also exposes `--mode`/`--tiers` as its own dropdowns (`mode: off|any|all`, `tiers: highest|all`), pre-filled from those CLI flags but changeable without leaving the picker; whatever you leave them at is what's used for planning. `--mode none`/`mode: off` is a third matching mode (alongside `any`/`all`) that skips ownership matching entirely: every bundle you've checked in the picker (or pass via a saved `--selection-config`) is treated as eligible regardless of what you actually own, letting you deliberately sync bundles you don't have any games from yet - which is also why `mode: off` doesn't auto-hide 0-owned bundles the way `any`/`all` do; it needs to show everything (just greyed) to build that manual selection in the first place. Saving (`ctrl+s` or the Save button) writes your selection to `config/apply-selection.yml` (`--selection-config` to change the path) and, when combined with `--apply`, also copies it into the staged backup directory. `sync steam` and `eligible steam` also accept `--selection-config`, so a saved selection filters those too; a missing selection config is silently ignored (no filtering, matching prior behavior). A bundle absent from both the `selected` and `excluded` lists in the config is included by default.

`game-collections search NAME` prints ranked matches from every supported storefront. Limit it with `--provider steam` (or `gog`, `epic`, `ubisoft`, or `humble`).

`game-collections complete FILE` fills qualified IDs in a draft list in place and defaults to Steam. Use repeatable `--provider`/`--store` options or comma-separated values to select multiple storefronts; `all` selects every supported storefront. Unique exact title matches are accepted automatically, while ambiguous matches prompt for a result or a canonical URL/direct ID.

Completion defaults to `--mode blank`, which searches games with no proper ID (an empty list or only `unresolved:*` values). `missing` searches providers that have neither an ID nor an earlier `unresolved:store:<store>:*` failure. `unresolved` also retries those failures. `refetch_all` searches every game for every selected provider and replaces those providers' existing IDs while preserving IDs from unselected providers.

`--provider isthereanydeal` (combine with `--mode unresolved`) is a special provider: instead of a storefront title search, it solves `unresolved:source:isthereanydeal:<bundle-id>:<slug>` markers (left behind by `scrape isthereanydeal` — see below) by fetching that game's own [isthereanydeal.com](https://isthereanydeal.com/) detail page, reading its Steam AppID directly and cross-checking every other storefront it's sold on. It writes `archives/isthereanydeal/game/<slug>/{metadata.json,source.json}` for every slug it looks at (`--archive-root` to change where) and adds `isthereanydeal:<slug>` alongside whatever real storefront IDs it found; a game with no recognized storefront link at all keeps its `unresolved:` marker. A reviewed `config/isthereanydeal-game-aliases.yml` (`--game-alias-config`) lists ITAD slugs known to be the exact same game listed separately per platform (confirmed real: a Steam DLC and its Epic counterpart each got their own ITAD entry with no cross-reference) so resolving either one picks up the other's IDs too.

## Humble Bundle imports

`game-collections scrape humblebundle` discovers the current Humble Choice and every active Games bundle. Books and Software are ignored. Repeat `--url` to crawl only specific Choice or Games pages.

Humble embeds its catalog data in the public HTML. The importer converts descriptions to Markdown, resolves real games against the advertised storefronts, and writes:

- launcher-neutral tier lists below `lists/humblebundle/`;
- normalized metadata below `archives/humblebundle/`;
- a sorted two-space `source.json` containing the relevant embedded Humble payloads.

Generated lists link back to the Humble offer URL and to their normalized `metadata.json` and raw `source.json` crawl archives through the list's `references` field.

Bundle directories begin with their UTC start date and fall back to the end date when the listing is unavailable. Each advertised cumulative tier becomes a list; coupons and bonuses remain in metadata but are excluded from the standard game list. Choice uses `humblebundle/choice/YYYY-MM`.

Choice months are actually a "pick N of the pool" subscription, not an all-or-nothing bundle. Each subscription tier's real pick quota (verified live against the page's own `tierInfo`, e.g. `basic.choices=3`, `premium.choices=12`) is clamped to that month's actual game count when it would otherwise exceed it, and a tier with no real pick mechanic (`uses_choices: false`, or a non-positive count, both observed live) is skipped. When any pick options are found, `humblebundle/choice/YYYY-MM` becomes a directory of `pick_quota`-bearing lists (`bundle.yml` for a single option, `tier-N.yml` per option otherwise) over the full monthly pool instead of the previous single flat file; a month whose page has no parseable `tierInfo` still falls back to that single flat file, unmodified.

Only a unique normalized title match is accepted automatically. Ambiguous searches show the storefront's ranked candidates and allow a canonical store URL or direct ID to be pasted. Leaving the manual value blank stores `unresolved:source:humblebundle:<machine-name>`. Reviewed decisions are kept in `config/humblebundle-store-ids.yml`; remove or edit an entry to resolve it again. `--non-interactive` records unresolved identities without prompting.

The command prints its progress as it works ("Offer x/y", "  Game x/y" while resolving) and writes each offer's files to disk as soon as that offer is done, rather than waiting for the whole crawl to finish. Re-running it reuses already-archived offers (skipping the expensive per-game storefront resolution) instead of resolving them again, unless the archive schema changed; pass `--refresh` to force resolving everything again.

The normalized archive uses `schemas/humblebundle-archive.schema.json`. All committed schemas are regenerated by `game-collections schema`.

## DailyIndieGame imports

`game-collections scrape dailyindiegame` discovers every Steam bundle currently listed for sale on [dailyindiegame.com](https://www.dailyindiegame.com/site_content_bundles.html). Repeat `--url` to crawl only specific weekly bundle pages.

Every game on a bundle page already links straight to its Steam store page, so there's no title matching or resolution step — IDs are read directly and are always `steam:<appid>`. The importer writes:

- one launcher-neutral list per bundle below `lists/dailyindiegame/bundle/<N>.yml`;
- normalized metadata below `archives/dailyindiegame/bundle/<N>/`;
- a sorted two-space `source.json` with the extracted raw text used to parse the bundle.

Generated lists link back to the bundle's page URL and to their normalized `metadata.json`/`source.json` crawl archives through the list's `references` field. Each game's cover art, description, individual price, and region are fetched from its own listing page and included in the archive metadata (not in the standard game list, which only ever has a name and IDs).

The site sits behind a Cloudflare bot challenge that blocks plain HTTP clients and even headless browser automation; the scraper drives a real, non-headless Chromium session (via `patchright`) to get through it, so running this command opens a visible browser window. Because of that constraint there's currently no scheduled/CI version of this scraper — run it manually from an attended machine.

The command prints its progress as it works ("Bundle x/y", "  Game x/y" per per-game listing page) and writes each bundle's files to disk as soon as that bundle is done, rather than waiting for the whole crawl to finish. Bundle numbers already archived on disk are reused as-is — skipping their bundle-page fetch *and* every per-game listing-page fetch entirely — instead of being re-crawled, unless the archive schema changed; pass `--refresh` to force re-fetching everything. This matters in particular since discovery mode re-lists mostly-the-same bundles week to week as they roll off/on gradually.

The normalized archive uses `schemas/dailyindiegame-archive.schema.json`. All committed schemas are regenerated by `game-collections schema`.

## Green Man Gaming imports

`game-collections scrape greenmangaming` discovers every bundle currently listed on [greenmangaming.com/bundles](https://www.greenmangaming.com/bundles/) whose category is `video-games` (the site also lists Books/Comics and Software bundles, which are ignored the same way Humble's Books/Software categories are). Repeat `--url` to crawl only specific bundle detail pages (`https://www.greenmangamingbundles.com/bundles/<slug>/`, note the different `greenmangamingbundles.com` domain from the index page).

Bundle detail pages don't link directly to a storefront ID — only a free-text DRM label per game (e.g. "Steam", "GOG", "Uplay") — so, like Humble, games are resolved by searching the matching official storefront for an exact title match. The importer writes:

- one launcher-neutral list per cumulative tier below `lists/greenmangaming/bundle/<slug>/<tier-id>.yml`;
- normalized metadata below `archives/greenmangaming/bundle/<slug>/`;
- a sorted two-space `source.json` with the extracted raw page text used to parse the bundle.

Generated lists link back to the bundle's page URL and to their normalized `metadata.json`/`source.json` crawl archives through the list's `references` field. Every game's DRM/platform/developer/publisher/description is fetched from its own per-item detail fragment and included in the archive metadata; tiers are cumulative (a higher tier includes every game from the tiers below it), mirroring Humble's tier model.

Only a unique normalized title match is accepted automatically. Ambiguous searches show the storefront's ranked candidates and allow a canonical store URL or direct ID to be pasted. Leaving the manual value blank stores `unresolved:source:greenmangaming:<product-id>`; a DRM label that isn't recognized (only Steam, GOG, and Uplay/Ubisoft Connect are mapped today) also goes straight to unresolved rather than guessing a storefront. Reviewed decisions are kept in `config/greenmangaming-store-ids.yml`; remove or edit an entry to resolve it again. `--non-interactive` records unresolved identities without prompting.

The command prints its progress as it works ("Bundle x/y", "  Game x/y" while resolving) and writes each bundle's files to disk as soon as that bundle is done, rather than waiting for the whole crawl to finish. Re-running it reuses already-archived bundles (skipping the per-item detail fetches *and* storefront resolution) instead of re-crawling them, unless the archive schema changed; pass `--refresh` to force everything again.

The normalized archive uses `schemas/greenmangaming-archive.schema.json`. All committed schemas are regenerated by `game-collections schema`.

## isthereanydeal.com imports

`game-collections scrape isthereanydeal` discovers bundles via [isthereanydeal.com/bundles](https://isthereanydeal.com/bundles/), an aggregator that indexes bundles from many selling platforms (Humble Bundle, Fanatical, GreenManGaming, IndieGala, AllYouPlay, and others) rather than selling anything itself. Unlike Humble/GreenManGaming, its own bundle detail page usually links straight to a storefront (most often Steam) per game, so games are resolved directly from that page's links — no title-search resolver needed. `--tab` selects which discovery tab(s) to crawl (`live` by default; `expired`/`pending` are opt-in).

Discovery uses a small, plain anonymous session: a GET of `/bundles/` sets a session cookie and embeds a matching CSRF-style token in the page, which is then sent as the `itad-sessiontoken` header on the paginated `POST /bundles/api/list/` discovery calls — an ordinary anonymous bootstrap, not any kind of login. Each discovered bundle's list-API summary is validated through a strict model and stored verbatim (as JSON, not passed through unchecked) in its archive; the embedded ITAD-internal tier/game preview in that same response is intentionally not modeled, since the bundle's own detail page gives the same information with real storefront IDs instead of ITAD's internal ones.

Each bundle's own detail page also embeds its full tier/price/game data as JSON in an inline script — this is the primary parser, and it's unaffected by the page's client-side mature-content gate (that gate only hides the page's visual rendering, not this embedded data), so mature-rated bundles are fully archived like any other. A DOM-based fallback parser (BeautifulSoup-driven) covers the rare case where that embedded data is ever missing or malformed. A small reviewed `config/isthereanydeal-shops.yml` (ITAD's own shop table: name, numeric shop id where ITAD has one, and — for a growing subset — the qualified-id prefix used once its storefront URL shape has been verified) is used both as a human-facing reference for what's supported and to log a corroboration warning when a game's shop-key ids don't match any resolved storefront id; it never affects resolution by itself. Every game's `ids` also always includes its own `isthereanydeal:<slug>` id, resolved storefront ids or not — a stable anchor for the `complete --provider isthereanydeal` follow-up below.

Because this source aggregates bundles our dedicated Humble/GreenManGaming scrapers already cover, it writes into **every** provider's own `lists/<provider>/` directory (creating new ones — `fanatical/`, `indiegala/`, `allyouplay/`, etc. — for platforms without a dedicated scraper here), but skips writing a list for any bundle that's already covered by an existing scraper's output (matched by the provider's own slug, decoded from the bundle's affiliate redirect URL) — only the `archives/isthereanydeal/...` record is written for those, so the aggregator's own view stays complete without duplicating lists two different pipelines would otherwise both produce for the same real bundle. The provider-name-to-slug mapping is a small reviewed `config/isthereanydeal-providers.yml`; an unreviewed provider falls back to a slugified name with a logged warning. Games with no recognized storefront link on the detail page fall back to `unresolved:source:isthereanydeal:<bundle-id>:<game-slug>` for later `game-collections complete --provider isthereanydeal` follow-up (see above).

A "Build Your Own"/mix-and-match bundle (`byob` in the list API) embeds its real per-count purchase options as `liveData.byob: [{"count": N, "price": [...]}, ...]` on the same detail page, verified live against real bundles (e.g. "Build Your Own Best of Killer Bundle": pick 5/10/20 of a 24-game pool). Instead of the usual one-list-per-cumulative-tier output, these write one list per pick-count over the same full pool, each with `pick_quota: <count>` set; `sync steam` treats a `pick_quota` list as eligible once at least that many of its games are owned, regardless of `--mode any`/`all`.

The importer writes:

- one launcher-neutral list per cumulative tier below `lists/<provider>/bundle/<date>_<slug>/<tier-id>.yml` (day-precision date prefix by default, mirroring Humble's own bundle directories; a fixed monthly-cadence bundle like Humble Choice would use `YYYY-MM` instead, though that case is always deduped away here);
- normalized metadata below `archives/isthereanydeal/bundle/<id>/`;
- a sorted two-space `source.json` with the validated list-API summary.

The command prints its progress as it works ("Bundle x/y", plus a skip note for already-covered bundles or a fallback note when a bundle's embedded page data couldn't be parsed) and writes each bundle's files to disk as soon as that bundle is done. Re-running it reuses already-archived bundles instead of re-fetching their detail page, unless the archive schema changed; pass `--refresh` to force everything again.

The normalized archive uses `schemas/isthereanydeal-archive.schema.json`. All committed schemas are regenerated by `game-collections schema`.

## Steam behavior

Steam does not expose a public API for creating library collections. Current clients store them in account-scoped cloud configuration:

```text
userdata/<account-id>/config/cloudstorage/cloud-storage-namespace-1.json
userdata/<account-id>/config/cloudstorage/cloud-storage-namespace-1.modified.json
```

This is an internal Steam format. Game Collections therefore models the complete file envelopes and relevant nested payloads with strict Pydantic models. Unknown fields, changed types, duplicate keys, unsupported filter versions, inconsistent dirty keys, or account mismatches stop synchronization.

`sync steam` is a read-only dry run. `sync steam --apply` follows a guarded workflow:

1. Read Steam files through no-follow, descriptor-based checks and validate them completely.
2. Write candidates, byte-for-byte backups, hashes, a manifest, and an inspection report to a timestamped Desktop directory. Steam is not changed.
3. Print every source, candidate, backup, destination path, and managed collection deletion and pause for inspection.
4. Require Steam to be stopped, then reread and revalidate the originals. Any metadata or content change aborts.
5. Require the user to type `REPLACE`.
6. Replace the namespace and modified-key files with same-directory temporary files, `fsync`, atomic replacement, post-write verification, and rollback if the second file fails.
7. Preserve backups and print the verified restore command.

Restoration requires Steam to be stopped and the user to type `RESTORE`.

Steam-visible collection names beginning with `🗃️ ` are reserved for Game Collections and form its managed namespace. Each sync reconciles that namespace to the current `--mode`/`--tiers` selection: selected collections are created or updated, while stale, superseded, no-longer-matching, and orphaned managed collections are staged for deletion. The collection used by `--source collection` is always protected. Retained collections preserve manually added games, unrelated non-prefixed collections and opaque namespace values remain untouched, and dynamic managed collections, same-name collisions, and unsafe IDs fail closed. Every deletion uses the same inspectable candidates, backups, Steam-stopped check, typed confirmation, atomic replacement, verification, rollback, and restore path as an update.

# Architecture

The core loads qualified IDs such as `steam:440` without launcher knowledge. Launcher adapters separately implement ownership evaluation, semantic planning, staging, and guarded application. Steam-specific models and IO remain under `game_collections.launchers.steam`; adding GOG or Epic should implement the launcher contracts without changing list parsing.

Only the Steam file gateway may open or replace Steam configuration. Tests use sanitized temporary fixtures. Development and automated tests must never run real-account `--apply` or `restore` without explicit user permission.
