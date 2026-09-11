# Merge `migrate tiers`/`migrate bundle-variations`/`migrate schema` into one flat `migrate --<flags>`

## Context

The previous session split migrations across three separate Typer subcommands: `migrate tiers`, `migrate bundle-variations` (both pre-existing, operating on `lists/`), and the newly-added `migrate schema` (operating on `archives/`, driving the version-envelope wavefront engine). The user's explicit ask, repeated across several recent messages culminating in this `/plan`, is that there should be **no subcommand names left at all** — just one `game-collections migrate --<flags>` invocation that runs whichever migrations apply, controlled entirely by flags. This finishes the "no dedicated migration command" spirit of the earlier work: instead of three verbs to remember, there's one command whose flags narrow scope.

## Current shapes (what's being merged)

- `migrate tiers` (`cli.py:259-300`) — `migrations/tiers.py`'s `plan_migration(lists_root)`/`apply_migration_step`/`step_would_change`; renames legacy tier-shaped bundle lists onto `bundle.yml`/`tier-N.yml`. Only `--lists-root`/`--apply` today; no `--git` support at all.
- `migrate bundle-variations` (`cli.py:303-343`) — `migrations/bundle_variations.py`'s equivalent trio; merges per-tier directories into one flattened `<key>.yml`. Same `--lists-root`/`--apply` only, no `--git`. **Must run after `tiers`** — `bundle_variations.py`'s own docstring says it "treats every bundle uniformly" only once `tiers` has already normalized the legacy naming, so order matters when both run together.
- `migrate schema` (`cli.py:346-423`) — the version-envelope wavefront engine (`migrations/schema_versions.py`), already flag-driven: `--path` (repeatable), `--type {metadata,source,bundle}` (repeatable AND, `bundle` currently a no-op placeholder), `--source SourceName` (repeatable), `--apply`/`--dry-run`/`--git`/`--git-style`. This is the shape the other two need to be pulled toward.

No existing CLI-level test (`tests/test_cli.py`) invokes any of the three subcommands directly (only `cli._migrate_source_archives`, the per-scrape auto-migration helper, is mocked there) — so this refactor has no test call sites to rename, only the command definition itself and docs.

## Design

Replace `migrate_app` (the `typer.Typer` sub-group) and its three `@migrate_app.command(...)` functions with one `@app.command("migrate")`:

```python
def migrate_command(
    lists_root_path: Annotated[Path | None, typer.Option("--lists-root")] = None,
    path: Annotated[list[Path] | None, typer.Option("--path", help="Archive dir/file to migrate; repeatable. Defaults to ./archives.")] = None,
    kind: Annotated[
        list[Literal["tiers", "bundle-variations", "metadata", "source"]] | None,
        typer.Option("--type", help="Which migration(s) to run; repeatable. Defaults to all four."),
    ] = None,
    source: Annotated[list[SourceName] | None, typer.Option("--source", help="Restrict metadata/source scanning to these crawlers.")] = None,
    apply: Annotated[bool, typer.Option("--apply")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    git: Annotated[bool, typer.Option("--git")] = False,
    git_style: Annotated[str, typer.Option("--git-style")] = "manual",
) -> None:
```

`--type`'s `bundle` value goes away (it was only ever a placeholder for this exact merge); `tiers`/`bundle-variations` take its place as real, wired-up values. Default (`kind` omitted) = run all four, in this fixed order regardless of the flags' order on the command line: **tiers → bundle-variations → metadata → source** (the tiers-before-bundle-variations dependency above; metadata/source order is arbitrary but keeping it last matches today's `migrate schema` behavior).

One `git_ops.begin_scrape_git_session`/autostash covers the whole invocation (not one per kind) — mirroring how a `scrape --git` run does a single autostash/restore around however many internal commits it produces — restored once in a `finally` regardless of how many kinds ran or failed partway.

**Commit shape, unified across all four kinds** (reusing the existing rules from the schema engine, extended to cover tiers/bundle-variations for the first time):
- `tiers`/`bundle-variations` are *rename/merge* operations → batched **≤100 changed lists per commit**, counter padded to the width of the total (`(1/3)`, `(03/22)` — never `(01/3)`): e.g. `(1/2) [lists] tiers: Renamed 143 legacy tier-shaped bundle list(s) onto the bundle.yml/tier-N.yml convention.` / `(1/1) [lists] bundle-variations: Merged 12 bundle director(y/ies) into flattened files.` New shared helper (`cli.py` or `git_ops.py`): `commit_in_batches(repository_root, changed_paths, subject, batch_size=100) -> None`, extracting the `(i/total)` zero-padding logic already written once for `migrate schema`'s rename case (that case didn't actually exist as code yet for tiers/bundle-variations — this is where it's introduced for real).
- `metadata`/`source` keep exactly what `migrate schema` already does: one unbatched commit per `(source, file_kind, version)` group via `migrations.schema_versions.plan_migrations`/`commit_message`.

**Dry-run output**: keep each kind's existing per-item line format (`would migrate: <old> -> <new> (tier=...)`, `would merge: <old(s)> -> <new>`, `would migrate (N file(s)): <schema message>`), followed by one summary line per kind that ran, then an overall total. `--apply`/`--git` semantics stay exactly as `migrate schema` already established: default dry-run, `--apply` writes without committing, `--git` implies `--apply` and commits (batched per the rule above), `--dry-run` explicit and invalid combined with `--apply`/`--git`.

## Files to change

- `src/game_collections/cli.py` — remove `migrate_app`/`app.add_typer(migrate_app, ...)` and the three `@migrate_app.command` functions; add the single `@app.command("migrate")` `migrate_command`, a shared `commit_in_batches` helper, and thread `git_ops` through the `tiers`/`bundle-variations` branches (they never touched `git_ops` before). Reuse `migrations.tiers.plan_migration`/`apply_migration_step`/`step_would_change`, `migrations.bundle_variations`'s equivalents, and `migrations.schema_versions.{discover_archive_paths,plan_migrations,apply_migration_group,commit_message,classify_path}` exactly as today's three commands already do — no changes needed inside `migrations/tiers.py`/`migrations/bundle_variations.py`/`migrations/schema_versions.py` themselves.
- `CLAUDE.md` — update the verb list (currently documents `migrate tiers`/`migrate bundle-variations` as separate verbs, predates `migrate schema` entirely) to describe the single `migrate --type ...` command and its default-all-four behavior; update the `src/game_collections/migrations/` bullet similarly.
- `src/game_collections/sources/README.md` — its "Confidence-scored dates and the version envelope" section currently says "The standalone `game-collections migrate schema` command..." — update to the new flat `migrate --type metadata --type source ...` form.

## Verification

- `uv run game-collections migrate --help` shows one flat command with `--lists-root`/`--path`/`--type`/`--source`/`--apply`/`--dry-run`/`--git`/`--git-style`, no `tiers`/`bundle-variations`/`schema` subcommands left.
- `uv run game-collections migrate` (no flags, dry-run default) against the real repo runs all four kinds in order and reports a per-kind count, matching what running the three old commands separately would have reported combined.
- `uv run game-collections migrate --type tiers --type bundle-variations` and `uv run game-collections migrate --type metadata --type source` each reproduce exactly their old single-purpose command's dry-run output.
- `uv run pytest -q` stays green (no existing test references the removed subcommand names).
