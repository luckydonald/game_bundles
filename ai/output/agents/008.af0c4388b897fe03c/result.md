I now have a complete picture. Here is the map of the sync/eligible CLI flow.

## 1. `src/game_collections/cli.py` — `sync` and `eligible` commands

**`eligible_command`** (cli.py:763-787)
- Options: `launcher` (positional, defaults `"steam"`), `--lists-root`, `--steam-root`, `--steam-id`, `--api-key`, `--source` (`api`/`installed`/`collection`), `--collection` (implies source=collection), `--log-skips`.
- Flow: rejects any launcher other than `"steam"` (cli.py:775-777) → builds adapter via `_steam_adapter(...)` (cli.py:780, helper at cli.py:659-717) → `discover_game_lists(_lists_root(lists_root))` (lists.py) → `adapter.plan(...)` → `_print_plan(plan, log_skips=log_skips)` (cli.py:720-760). Read-only; never stages or applies.

**`sync_command`** (cli.py:790-847)
- Options: everything `eligible` has, plus `--apply` (bool), `--output-dir`, `--mode` (`any`/`all`, default `all` — steam match mode), `--tiers` (`all`/`highest`, default `highest`).
- Flow:
  1. Reject non-steam launcher (cli.py:806-808).
  2. `_steam_adapter(..., match_mode=mode, tier_mode=tiers, reconcile_managed=True)` (cli.py:811-820) — note `sync` always passes `reconcile_managed=True` (so deletions of previously-managed collections are computed), unlike `eligible`.
  3. `plan = adapter.plan(discover_game_lists(...))` (cli.py:821), `_print_plan(plan, log_skips=log_skips)` (cli.py:822).
  4. If not `--apply`: print "Dry run only..." and return (cli.py:823-826).
  5. If `--apply`: `staged = adapter.stage(plan, output_dir or default_staging_root())` (cli.py:827) → echoes staged dir, README path, and per-record source/candidate/backup paths read back out of `manifest.json` (cli.py:828-834).
  6. `typer.confirm("Have you inspected the candidates and closed Steam?")` (cli.py:835) — if declined, abort with no changes (cli.py:836-837).
  7. `adapter.apply(staged, lambda prompt: typer.prompt(prompt))` (cli.py:839) — this is where the gateway asks the user to literally type `REPLACE`.
  8. Prints confirmation + restore command hint (cli.py:840-842).

**`_steam_adapter`** helper (cli.py:659-717): resolves `source` (`api`|`installed`|`collection`, default `api`, or `collection` if `--collection` given), discovers Steam root/`SteamFileGateway`, builds an `owned_app_ids_source` callable, constructs `SteamOptions`, returns `(SteamAdapter, SteamFileGateway)`.

**`_print_plan`** (cli.py:720-760): local-imports `SyncPlan` to type-check the plan; prints per-list eligibility (`eligible: <id> (<name>)` / `skipped: ...` with missing/unsupported details if `--log-skips`), then prints planned `delete:` changes, then a summary line with create/update and delete counts.

**`restore_command`** (cli.py:850-871) is the counterpart used after `sync --apply`: `game-collections restore steam <staged-dir>` calls `gateway.restore(staged_dir, lambda prompt: typer.prompt(prompt))`.

## 2. `src/game_collections/launchers/base.py` — registry & plan types

- `CollectionEligibility` (base.py:16-26): `list_id`, `name`, `eligible: bool`, `owned_ids: list[str]`, `missing_ids: list[str]`, `unsupported_ids: list[str]`. No tier/date/bundle-size fields — purely ownership-derived.
- `PlannedCollectionChange` (base.py:29-50): `list_id: str | None`, `target_id: str` (launcher-native collection id), `name: str`, `action: Literal["create-or-update", "delete"]`, `added_ids: list[str]`, `preserved_ids: list[str]` (currently unused by Steam — always empty in practice). Validator enforces `list_id` required for create-or-update and no game IDs on delete.
- `SyncPlan` (base.py:53-61): `launcher: str`, `account: str`, `eligibility: list[CollectionEligibility]`, `changes: list[PlannedCollectionChange]`. This is the entire semantic plan — no bundle/tier/date metadata anywhere in it.
- `LauncherAdapter` ABC (base.py:64-89): `evaluate(game_lists) -> list[CollectionEligibility]`, `plan(game_lists) -> SyncPlan`, `stage(plan, output_dir) -> Path`, `apply(staged_dir, confirm: Callable[[str], str]) -> None`.
- `LauncherRegistry` (base.py:92-115): simple dict-backed `register`/`get`, not currently wired into cli.py (cli.py hardcodes steam directly, no registry lookup used).

## 3. `src/game_collections/launchers/steam/adapter.py` — plan construction

- `SteamOptions` (adapter.py:38-59): `steam_id`, `steam_root`, `api_key`, `match_mode` (`any`/`all`), `tier_mode` (`all`/`highest`), `reconcile_managed: bool`, `protected_collection_name`.
- `evaluate()` (adapter.py:113-156): pulls `owned_app_ids_source()`, for each `LoadedGameList` collects required Steam app IDs from `game.qualified_ids` where `provider == "steam"`; games without a steam id become `unsupported_ids`; computes `missing`/`owned`; eligibility is `bool(owned)` for `match_mode="any"` or `bool(required) and not missing` for `"all"`.
- `plan()` (adapter.py:158-181): calls `evaluate()`, then `_selected_list_ids()` to filter by tier mode, builds one `PlannedCollectionChange(action="create-or-update")` per selected list (`target_id=steam_collection_id(list_id)`, name prefixed with `🗃️ ` = `STEAM_COLLECTION_PREFIX`, `added_ids=result.owned_ids`). If `reconcile_managed`, appends deletions from `_managed_deletions()`.
- `_selected_list_ids()` (adapter.py:183-217): "highest tier" logic — parses list-id suffix via `TIER_STEM_PATTERN` (`tier-<n>`) or `ITEM_BUNDLE_STEM_PATTERN` (`(entire-)?<n>-item-bundle`) using `_tier_identity()` (adapter.py:299-309), groups by parent path, and for `tier_mode="highest"` keeps only the highest-rank eligible sibling per parent; non-tiered eligible lists are always included; raises on ambiguous duplicate ranks per parent.
- `_managed_deletions()` (adapter.py:219-280): reads all current Steam collections via `gateway.read_collections()`, matches which ones are "managed" (name equals a known list's plain name = legacy, or starts with the `🗃️ ` prefix), skips the currently protected manual collection (`protected_collection_name`), skips ones already in `selected_ids`, validates the collection isn't dynamic (`filterSpec`) and its id matches the safe user-collection pattern, else raises; builds `delete` `PlannedCollectionChange`s.
- `stage()`/`apply()` (adapter.py:282-294): thin delegation to `SteamFileGateway.stage`/`.apply` (requires a non-`None` gateway).
- `steam_collection_id()` (io.py:786-791): deterministic `uc-<base64(sha256(list_id)[:9])>` id, so list_id → Steam collection id is stable/derivable without any lookup table.

High-level `stage`/`apply` behavior (io.py): `stage()` (io.py:232-287) reads a locked snapshot of Steam's two cloud-storage JSON files, builds new candidate versions in memory (`_build_candidates`, io.py:425-533, which mutates collection entries per `plan.changes`), validates the candidate pair, then writes `candidate-*`, `backup-*`, `manifest.json`, and `README.txt` into a fresh timestamped directory under `output_dir` (never touching real Steam files). `apply()` (io.py:289-347) re-validates the manifest matches this Steam root/account, requires Steam stopped (`require_steam_stopped`, io.py:384-423, checks pid/pipe files), re-reads live Steam files and asserts their identity/hash still match what staging saw, re-reads and re-validates the staged candidate/backup bytes, then calls the passed-in `confirm(prompt)` callback expecting the literal string `"REPLACE"` before doing an atomic file replace with rollback-on-error and post-write verification.

## 4. `src/game_collections/lists.py` — list discovery/loading

- `LoadedGameList` (lists.py:21-29): only `id: str`, `path: Path`, `data: GameList`. `GameList` itself (models.py:101-123) has only `schema_version`, `name`, `references: list[Reference]`, `games: list[Game]`. **There is no bundle source/date/item-count/tier field on the loaded object at all.**
- `derive_list_id()` (lists.py:32-48) derives `vendor/name` purely from the file path relative to `lists_root` (e.g. `lists/humblebundle/bundle/20-item-bundle.yml` → id `humblebundle/bundle/20-item-bundle`). Tier/bundle-size info is only encoded positionally in this path — `SteamAdapter._tier_identity()` (adapter.py:299-309) is what parses `tier-<n>` or `(entire-)?<n>-item-bundle` back out of the tail segment.
- `discover_game_lists()` (lists.py:71-85): globs `*.yml` under lists_root, loads+validates each via Pydantic, rejects case-colliding IDs.
- Actual bundle metadata (dates, tier item counts, source URL) lives only in the separate archive JSON files written by the scrapers, e.g. `archives/humblebundle/bundle/<key>/metadata.json` (`HumbleArchive`, models.py:119-135, with `dates: HumbleDates{start,end,crawled}`, `tiers[].item_count`, etc. — see humblebundle/crawler.py:236-244 `_archive_paths`). The YAML list only carries a `Reference(name="Crawl metadata", path=...)` pointing at that JSON (crawler.py:291-298) — nothing is denormalized onto the list/game objects themselves. So any TUI wanting bundle date/source/tier-size would have to either parse the list_id path convention or separately load+parse the linked archive JSON via its `Reference.path`.

## 5. Existing TUI/interactive-prompt tooling

- `pyproject.toml` dependencies (pyproject.toml:11-19): `httpx`, `markdownify`, `patchright`, `pydantic`, `PyYAML`, `typer`, `vdf`. **No `questionary`, `InquirerPy`, `rich`, `prompt_toolkit`, `curses`/`textual`, or any other interactive/TUI library.** Only `typer` (which itself wraps `click`) is available for prompting.
- All existing interactivity is plain `typer.prompt(...)` / `typer.confirm(...)` calls, no rich menus:
  - `_choose_store_candidate` (cli.py:171-198) and `_choose_gmg_store_candidate` (cli.py:483-510): print a numbered list to stdout via `typer.echo`, then `typer.prompt("Select a result", default=str(other))` in a `while True` loop validating the input is a valid index or the "Other…" sentinel, falling back to a second `typer.prompt(...)` for a manual URL/ID (blank = unresolved). This is the closest existing pattern to a menu/selector, and it's manual (no library-provided arrow-key selection).
  - `sync_command`'s confirmation (cli.py:835, `typer.confirm(...)`) and the `REPLACE`/`RESTORE` literal-text confirmations threaded through `adapter.apply`/`gateway.restore` (cli.py:839, 865) via a `Callable[[str], str]` that's just `lambda prompt: typer.prompt(prompt)`.
- Implication for planning `game-collections apply`: there is no existing arrow-key/checkbox TUI dependency in the repo; any richer interactive picker (e.g. multi-select of pending sync changes) would need a new dependency (e.g. `questionary`/`InquirerPy`/`rich`) or would need to follow the existing numbered-`typer.prompt` loop convention used by `_choose_store_candidate`/`_choose_gmg_store_candidate` for consistency with current UX conventions.