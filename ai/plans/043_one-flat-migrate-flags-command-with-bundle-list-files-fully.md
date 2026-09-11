# One flat `migrate --<flags>` command, with `bundle` list files fully versioned too

## Context

`game-collections` currently has three separate migration verbs: `migrate tiers` and `migrate bundle-variations` (pre-existing, renaming/merging `lists/**/*.yml` bundle files onto their current layout) and `migrate schema` (this session's new version-envelope wavefront engine for `archives/**/{metadata,source}.json`). The user wants exactly **one** `game-collections migrate --<flags>` command, no subcommand names left.

Merging the CLI surface alone would be easy, but `tiers`/`bundle-variations` aren't really two independent migration *kinds* — per the user's own framing, they're two historical **versions** of one `bundle` list-file family (today's `GameList` shape is the second version; the legacy per-tier-file, `tier:`-scalar-carrying shape is the first). Unlike `metadata.json`/`source.json` (machine-only caches nobody reads except the crawler that wrote them), list files are read back constantly by nearly every command (`load_game_list`, `discover_game_lists`, `sync`, `apply`, ...), so - per the user's explicit direction - each version deserves a *real, typed* Pydantic model, not just an untyped dict transform validated only against the latest shape (the approach used for `metadata.json`/`source.json`, which are never re-read as anything but "current"). The version marker itself stays a **plain int** (`schema: 1`/`schema: 2`, matching what's already on disk in every file today) rather than a `SchemaDateVersion` tuple, since rewriting every hand-authored file's version to a 7-element array would be needlessly disruptive for files people actually look at.

## What `tiers`/`bundle-variations` actually do today (must be preserved exactly)

- `migrations/tiers.py`: for every `<provider>/bundle/<key>/` directory (choice/ pick-option directories are **not** touched here), renames its `.yml` files onto `bundle.yml` (single file) or `tier-N.yml` (multiple), ranking by: existing `tier-N`/`N-item-bundle` filename patterns first, falling back to reading the linked archive's own `tiers` order (`_identifier_order_from_metadata`) for arbitrary scraped names (e.g. GreenManGaming's `bronze.yml`/`gold.yml`). Pure path rename; strips a legacy `tier` scalar the current model no longer accepts.
- `migrations/bundle_variations.py`: for every `<provider>/{bundle,choice}/<key>/` directory (this one **does** cover `choice/`), merges all its `.yml` files into one `<key>.yml` one level up, populating `GameList.tiers`/`Game.tiers`. Ranks by each file's legacy `tier` scalar, falling back to the files' own already-renamed-by-`tiers.py` alphabetical order (a stable-sort trick: when every `tier` is absent, `tier-1.yml < tier-2.yml < ...` alphabetically already gives the right order). Recovers the shared bundle name and per-tier display name from the `f"{bundle} — {tier}"` naming convention writers use (`_bundle_name`/`_tier_name`).
- **Both must keep their exact detection/fallback logic** - this plan re-homes them under the versioned wavefront engine, it does not rewrite the migration algorithms themselves.

## Design

### 1. Generalize the trajectory engine to any comparable VERSION type (`versioning.py`)

- Add rich comparison to `SchemaDateVersion` (`__lt__`/`__le__` via its existing `sort_key()`), so both it and plain `int` support `<`/`>=` directly.
- Change `trajectory()`'s signature from hard-coded `SchemaDateVersion` to generic `VERSION` (PEP 695 type param, like `Versioned` already is), comparing with `<`/`>=` instead of calling `.sort_key()` explicitly. `migrations/schema_versions.py`'s existing `MigrationStep`/`plan_migrations` (for metadata/source) keep working unchanged - they just become one concrete instantiation (`VERSION = SchemaDateVersion`) of the now-generic engine.
- Add `SchemaIntVersion` (a plain `int` type alias) as the sibling VERSION type for list files.

### 2. Versioned list-file models (`models.py` or a new `lists_versions.py`)

- `GAMELIST_V1: SchemaIntVersion = 1`, `GAMELIST_V2: SchemaIntVersion = 2`; `GameListVersions = Literal[GAMELIST_V1, GAMELIST_V2]`; `GameListCurrentVersion = Literal[GAMELIST_V2]`; `CURRENT_GAMELIST_VERSION = GAMELIST_V2`.
- `GameList` drops its embedded `schema_version`/`schema`-aliased field entirely (mirrors every archive model from this session's earlier work) - it *is* the V2/current shape. `VersionedGameList = Versioned[GameListCurrentVersion, GameList]`.
- New `GameListV1` (StrictModel): the legacy shape of **one** pre-merge tier/pick-variation file - the same fields `GameList` has today minus `tiers`/`pick_quota` (a not-yet-merged file is never itself multi-tier) plus the legacy `tier: int | None = None` scalar. This is what a single file inside an unmigrated bundle/choice directory actually validates as.
- On-disk shape stays flat (`schema: 1`/`schema: 2` alongside `name:`/`games:`/etc., exactly like today) - **no** `{version, data}` JSON-style envelope for YAML files; only `versioning.peek_version`'s *concept* (read the version, hand back the rest as `data`) is reused, via a small YAML-flavored variant that pops `schema` out of the loaded mapping instead of expecting a nested `data` key.

### 3. The migration unit is a whole bundle/choice directory, not one file (`migrations/list_versions.py`, new)

Unlike `metadata.json`/`source.json` (one file = one independent unit), a not-yet-merged bundle directory is *several* V1 files that become *one* V2 file - so the trajectory `DATA` for this family is the directory's full raw-file map, not a single file's dict:

- `discover_list_units(lists_root) -> list[Path]` - one entry per bundle/choice variation directory (reusing `bundle_variations.discover_variation_directories`, which already covers both `bundle/` and `choice/`) **plus** one entry per flat, non-directory list file that has no variation directory at all (e.g. `dailyindiegame/bundle/<key>.yml`, `choice/YYYY-MM.yml`) - these still need their `schema:` bumped to 2 even though nothing structural changes.
- The single `V1 -> V2` step's `migrate_fn`, for a directory unit: reuse `tiers.plan_bundle_directory`/`apply`-equivalent logic **only when the unit is under a `bundle/` parent** (preserving the existing bundle-vs-choice asymmetry - `tiers.py` never touches `choice/`), producing the renamed/ranked file set, then feed that into `bundle_variations.plan_variation_directory`'s merge logic to produce the final merged `GameList` content + target path + old paths to remove. For a flat non-directory unit, the step is a no-op content-wise, just a version bump. Every unit ends at V2 in exactly one step (no meaningful "renamed but not yet merged" version ever existed independently, matching today's behavior where `tiers.py` and `bundle_variations.py` are always run back-to-back).
- Commit-batching: this migration involves real renames/merges/deletions, so it's a **Path-kind migration** per the existing commit-shape rules - batched ≤100 units per commit, `(NN/N)` counter, e.g. `(1/4) [lists] bundle: Migrated 100 bundle list unit(s) from schema 1 to 2.` - reusing the wavefront grouping machinery from `migrations/schema_versions.py` (generalized per §1), not a new bespoke batching implementation.

### 4. CLI: one flat `game-collections migrate` command

Replace `migrate_app` (the Typer sub-group) and all three `@migrate_app.command(...)` functions with a single `@app.command("migrate")`:

```python
def migrate_command(
    lists_root_path: Annotated[Path | None, typer.Option("--lists-root")] = None,
    path: Annotated[list[Path] | None, typer.Option("--path")] = None,          # archives root(s), default ./archives
    kind: Annotated[list[Literal["metadata", "source", "bundle"]] | None, typer.Option("--type")] = None,  # default: all three
    source: Annotated[list[SourceName] | None, typer.Option("--source")] = None,  # narrows metadata/source only
    apply: Annotated[bool, typer.Option("--apply")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    git: Annotated[bool, typer.Option("--git")] = False,
    git_style: Annotated[str, typer.Option("--git-style")] = "manual",
) -> None:
```

One `git_ops.begin_scrape_git_session`/autostash covers the whole invocation; `bundle` runs its own batched wavefront (§3) using `lists_root_path`, while `metadata`/`source` keep running today's `migrate schema` wavefront (unbatched, one commit per version-step group) against `path`/`source`-filtered archives. Same `--apply`/`--dry-run`/`--git` semantics already established (`--git` implies `--apply`; `--dry-run` explicit, invalid with the other two). Default `kind` (all three) reproduces what running all of today's three commands back-to-back would have done, `bundle` before `metadata`/`source` (arbitrary but matches today's ordering).

### 5. Mechanical cleanup this forces

Every `GameList(schema=1, ...)` construction across every crawler/resolver/migration module (and their tests) needs the `schema=1,` line dropped, exactly like the earlier `DekuArchive(schema=1, ...)` etc. cleanup this session already did for archive models - same mechanical pattern, larger surface (every source's `write_*_offer`, plus `migrations/bundle_variations.py`'s own `GameList(...)` construction, plus test fixtures). `render_game_list_yaml` (`sources/common.py`) needs no change itself (it already just calls `model_dump(by_alias=True, ...)`), but its *output* stops including a `schema:` line unless callers wrap through the new `Versioned`-aware writer - so a new `render_versioned_game_list_yaml(game_list, version, path, repository_root)` (or an updated `render_game_list_yaml` taking an explicit `version` parameter) is needed everywhere a list file is written, to put the flat `schema: <int>` key back at the top of the YAML alongside the rest of `GameList`'s fields.

## Verification

- `uv run game-collections migrate --help` - one flat command, no subcommands.
- `uv run game-collections migrate --type bundle` (dry-run) against the real `lists/` tree reproduces the counts `migrate tiers`/`migrate bundle-variations` used to report, combined, and shows every currently-`schema: 1` file (structurally already-merged or not) as needing the version bump.
- New tests: `GameListV1`/`GameList` round-trip through the combined V1->V2 step for (a) a single already-conventional `bundle.yml`, (b) a multi-tier directory needing both rename and merge, (c) a `choice/<key>/` directory (no `tiers.py` rename step involved), (d) a flat non-directory list file (schema-bump-only) - each against real fixture content mirroring `tests/test_migrations_tiers.py`/`test_migrations_bundle_variations.py`'s existing cases, not synthetic new shapes.
- `uv run pytest -q` stays green; existing `tests/test_migrations_tiers.py`/`test_migrations_bundle_variations.py` either keep passing against the preserved internal functions or get folded into the new combined-unit tests without losing any covered case.
- As with the earlier `metadata`/`source` migration: build and verify the tooling (dry-run against the real repo), but do **not** run `--apply`/`--git` to bulk-rewrite the thousands of real `lists/**/*.yml` files' `schema:` value without explicit separate go-ahead.
