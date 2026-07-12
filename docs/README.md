# Game Collections

Game Collections is a Python resource for maintaining portable lists of games and synchronizing fully owned lists into launcher libraries. The initial launcher is Steam; the list format and synchronization contracts are designed for later GOG, Epic, or other integrations.

The original use case is keeping bundles such as **The Orange Box** together in a Steam library.

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

## Setup

Python 3.14 or newer and [uv](https://docs.astral.sh/uv/) are required.

```console
uv sync --extra test
uv run game-collections validate
uv run pytest
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
uv run game-collections eligible steam
uv run game-collections sync steam
uv run game-collections sync steam --apply
uv run game-collections restore steam ~/Desktop/game-collections-steam-<timestamp>
```

Set `STEAM_WEB_API_KEY` for ownership lookup. By default, the most recently used account in Steam's `loginusers.vdf` is selected. `--steam-id`, `--steam-root`, `--lists-root`, and `--output-dir` provide explicit overrides.

`game-collections search NAME` prints ranked matches from every supported storefront. Limit it with `--provider steam` (or `gog`, `epic`, `ubisoft`, or `humble`).

`game-collections complete FILE` fills qualified IDs in a draft list in place and defaults to Steam. Use repeatable `--provider`/`--store` options or comma-separated values to select multiple storefronts; `all` selects every supported storefront. Unique exact title matches are accepted automatically, while ambiguous matches prompt for a result or a canonical URL/direct ID.

Completion defaults to `--mode blank`, which searches games with no proper ID (an empty list or only `unresolved:*` values). `missing` searches providers that have neither an ID nor an earlier `unresolved:store:<store>:*` failure. `unresolved` also retries those failures. `refetch_all` searches every game for every selected provider and replaces those providers' existing IDs while preserving IDs from unselected providers.

## Humble Bundle imports

`game-collections scrape humblebundle` discovers the current Humble Choice and every active Games bundle. Books and Software are ignored. Repeat `--url` to crawl only specific Choice or Games pages.

Humble embeds its catalog data in the public HTML. The importer converts descriptions to Markdown, resolves real games against the advertised storefronts, and writes:

- launcher-neutral tier lists below `lists/humblebundle/`;
- normalized metadata below `archives/humblebundle/`;
- a sorted two-space `source.json` containing the relevant embedded Humble payloads.

Generated lists link back to the Humble offer URL and to their normalized `metadata.json` and raw `source.json` crawl archives through the list's `references` field.

Bundle directories begin with their UTC start date and fall back to the end date when the listing is unavailable. Each advertised cumulative tier becomes a list; coupons and bonuses remain in metadata but are excluded from the standard game list. Choice uses `humblebundle/choice/YYYY-MM`.

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
3. Print every source, candidate, backup, and destination path and pause for inspection.
4. Require Steam to be stopped, then reread and revalidate the originals. Any metadata or content change aborts.
5. Require the user to type `REPLACE`.
6. Replace the namespace and modified-key files with same-directory temporary files, `fsync`, atomic replacement, post-write verification, and rollback if the second file fails.
7. Preserve backups and print the verified restore command.

Restoration requires Steam to be stopped and the user to type `RESTORE`.

Synchronization is additive in version 1. It creates deterministic static collections, preserves manually added games, and never removes games or collections. Same-name collisions, dynamic collections, and system collection names fail closed.

## Architecture

The core loads qualified IDs such as `steam:440` without launcher knowledge. Launcher adapters separately implement ownership evaluation, semantic planning, staging, and guarded application. Steam-specific models and IO remain under `game_collections.launchers.steam`; adding GOG or Epic should implement the launcher contracts without changing list parsing.

Only the Steam file gateway may open or replace Steam configuration. Tests use sanitized temporary fixtures. Development and automated tests must never run real-account `--apply` or `restore` without explicit user permission.
