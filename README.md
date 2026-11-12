# Game Collections

Game Collections is a Python resource for maintaining portable lists of games and synchronizing fully owned lists into launcher libraries. The initial launcher is Steam; the list format and synchronization contracts are designed for later GOG, Epic, or other integrations.

The original use case is keeping bundles such as **The Orange Box** together in a Steam library.

## List format

Lists live below [`lists/`](lists/). Their ID is their path relative to that directory without `.yml`: `lists/valve/the-orange-box.yml` is `valve/the-orange-box`.

```yaml
# yaml-language-server: $schema=../../schemas/game-list.schema.json
schema: 1
name: The Orange Box
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

Run `uv run game-collections install` once to get a real `game-collections` binary on
your `PATH` (via `uv tool install`, editable against this checkout unless a newer
release exists on PyPI) plus working bash/zsh tab completion for both
`game-collections ...` and `uv run game-collections ...`. `game-collections uninstall`
(alias `deinstall`) removes the completion wiring and optionally the installed tool.

Common commands:

```console
uv run game-collections list
uv run game-collections schema
uv run game-collections scrape humblebundle
uv run game-collections eligible steam
uv run game-collections sync steam
uv run game-collections sync steam --apply
uv run game-collections restore steam ~/Desktop/game-collections-steam-<timestamp>
```

Set `STEAM_WEB_API_KEY` for ownership lookup. By default, the most recently used account in Steam's `loginusers.vdf` is selected. `--steam-id`, `--steam-root`, `--lists-root`, and `--output-dir` provide explicit overrides.

##### As tool
```shell
uv tool install .
uv tool run --from game-collections patchright install chromium
```

## Scraping everything

`game-collections scrape all` runs every source one after another and never aborts at the first failure: errors are collected and listed at the end, and the exit code is 1 if any source failed.
Sources come in two kinds.
Direct sources crawl a store's own site (`humblebundle`, `greenmangaming`, `dailyindiegame`, `fanatical`, `digiphile`) and give the cleanest results, so they run first.
Aggregate sources crawl third-party bundle listings and skip bundles a direct scraper already covers (`isthereanydeal`, `dekudeals`).
`scrape all-direct` and `scrape all-aggregate` run just one kind.
`--skip NAME` (repeatable) leaves a source out, e.g. `--skip dailyindiegame` for unattended runs since it opens a real browser window, and `--refresh` and `--non-interactive` are passed on to the sources that support them.
Scraping runs with `--git` by default: the scrape happens in a throwaway git worktree at `scripts/.worktrees/scrape/<subcommand>/<YYYY-MM-DD_HH-MM-SS_+ZZZZ>/` on the branch `scrape/<subcommand>/<same stamp>`, its output is committed there, and the commits are then cherry-picked into your checkout and the worktree and branch removed.
Your checkout stays usable while a long scrape runs, but it has to be clean when the scrape starts (`ai/errors/` is ignored for that check).
Git is only touched once the subcommand actually runs, so `--help` and option errors never stash, create a worktree or change anything.
The related options go before the subcommand:

- `--git-worktree PATH` changes the base directory the `<subcommand>/<stamp>` folders are created under; `--git-worktree ''` keeps the default.
- `--git-worktree-allow-dirty` starts anyway from a dirty checkout; the worktree starts from `HEAD` and cannot see those changes, and they are stashed around the final cherry-pick and restored afterwards.
- `--no-git-worktree` scrapes in place instead (autostash, scrape, commit, restore the stash), as CI does.
- `--no-git` leaves git alone, and is an error together with any explicit `--git-*` option.

A worktree only holds tracked files.
Gitignored local state a scrape needs is listed in the tracked `.worktree_unignore` at the repository root: one path per line, `#` comments, an optional last word `symlink` (default), `hardlink` or `copy`.
Every entry must exist and be gitignored, otherwise the scrape aborts before starting; the entries are removed from the worktree again before it is deleted.
If the final cherry-pick conflicts, the root is left untouched, the scrape branch is kept and its tip tagged `bak/<sha>`, and the diff plus the worktree status are printed.
On a terminal you are then asked whether to discard the no longer needed worktree directory (Enter or `y` does, `n` keeps it); without a terminal it is discarded.
`migrate` also has `--git/--no-git` on by default, but `--git` no longer implies `--apply`: it stays a read-only dry run until `--apply` is given, which then commits the migrated files (`--apply --no-git` only writes).
With `scrape all`, every source still commits its own output, and the worktree is cherry-picked back (or the autostash restored with `--no-git-worktree`) once after the last source.

## Humble Bundle imports

`game-collections scrape humblebundle` discovers the current Humble Choice and every active Games bundle. Books and Software are ignored. Repeat `--url` to crawl only specific Choice or Games pages. If building an offer fails, its extracted payload and the error details are parked in `archives/humblebundle/recovery/` and reused on the next run instead of re-fetching the page (`--refresh` discards them).

Humble embeds its catalog data in the public HTML. The importer converts descriptions to Markdown, resolves real games against the advertised storefronts, and writes:

- launcher-neutral tier lists below `lists/humblebundle/`;
- normalized metadata below `archives/humblebundle/`;
- a sorted two-space `source.json` containing the relevant embedded Humble payloads.

Bundle file names begin with their UTC start date and fall back to the end date when the listing is unavailable. Each advertised cumulative tier is recorded on the one merged bundle list (its `tiers`/`Game.tiers` fields, see `lists/README.md`); coupons and bonuses remain in metadata but are excluded from the standard game list. Choice uses `humblebundle/choice/YYYY-MM`.

Only a unique normalized title match is accepted automatically. Ambiguous searches show the storefront's ranked candidates and allow a canonical store URL or direct ID to be pasted. Leaving the manual value blank stores `unresolved:humblebundle:<machine-name>`. Reviewed decisions are kept in `config/humblebundle-store-ids.yml`; remove or edit an entry to resolve it again. `--non-interactive` records unresolved identities without prompting.

The normalized archive uses `schemas/humblebundle-archive.schema.json`. Both committed schemas are regenerated by `game-collections schema`.

## Fanatical imports

`game-collections scrape fanatical` archives every bundle currently listed on [fanatical.com](https://www.fanatical.com/en/bundle/games), regular and Build-Your-Own, from Fanatical's public JSON list. Repeat `--url` to crawl only specific bundle or pick-and-mix pages (the bundle must still be listed).

Games get their Steam id from Fanatical itself or, failing that, from an exact Steam title search (cached in `config/fanatical-store-ids.yml`); the rest is recorded as `unresolved:source:fanatical:<bundle>:<slug>` for `game-collections complete`. Tiers land on one `lists/fanatical/bundle/<date>_<slug>.yml` per bundle (`pick N` tiers with a `pick_quota` for Build-Your-Own), the normalized record and raw payload go to `archives/fanatical/`, and book, comic and course bundles are archived without a list. See `src/game_collections/sources/README.md` for the details.

## Digiphile imports

`game-collections scrape digiphile` archives every bundle on [digiphile.co](https://www.digiphile.co/collections), live and expired, from the data embedded in its pages. Repeat `--url` to crawl only specific bundle pages.

Every game already carries its Steam id, so nothing needs resolving. Tiers land on one `lists/digiphile/bundle/<date>_<slug>.yml` per bundle: the regular price tiers first, then the optional charity and upsell add-ons as dependent tiers (`kind`, `requires`, see `lists/README.md`). The normalized record and raw payload go to `archives/digiphile/`, comic bundles are archived without a list, and lists the aggregators already created for a bundle get the `digiphile:` ids backfilled. See `src/game_collections/sources/README.md` for the details.

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

`--tiers all` makes one collection per tier of a multi-tier bundle. `--tiers highest` (the default) makes one per bundle for the highest tier you own completely. Dependent add-on tiers (charity or upsell, see `lists/README.md`) of that bundle which you own as well are merged into that collection, and each one extends its name, e.g. `🗃️ Social Multiplayer — 16.00 USD + Charity: Venezuela Earthquake Relief`. The `apply steam` picker keeps add-on tiers checked under `highest`; they only end up in a collection if they are eligible.

Synchronization is additive in version 1. It creates deterministic static collections, preserves manually added games, and never removes games or collections. Same-name collisions, dynamic collections, and system collection names fail closed.

## Architecture

The core loads qualified IDs such as `steam:440` without launcher knowledge. Launcher adapters separately implement ownership evaluation, semantic planning, staging, and guarded application. Steam-specific models and IO remain under `game_collections.launchers.steam`; adding GOG or Epic should implement the launcher contracts without changing list parsing.

Only the Steam file gateway may open or replace Steam configuration. Tests use sanitized temporary fixtures. Development and automated tests must never run real-account `--apply` or `restore` without explicit user permission.
