# Add `scrape all`, `scrape all-direct` and `scrape all-aggregate`

**Commit style:** Skill `/commit-with-lplp-style` is active — auto-commit following it for this implementation.

## Context

Todo `c3fbbd36-6809-4af7-b2a6-7633d839c37a`.
Today every source needs its own `game-collections scrape <source>` invocation.
We want one command that runs them one after another, keeps going when a source fails, and reports all errors at the end.
A second commit then makes `scrape --help` show which kind each source is and removes the option boilerplate repeated across the seven scrape commands.

## Findings

- All scrape commands live in `src/game_collections/cli.py` (`scrape_*_command`, lines ~831-1447) and read their git session from `ctx.obj`, which `scrape_callback` builds once per invocation.
- Every command ends in `git_ops.finish_scrape_git_session`, which commits its own paths and then restores the autostash.
  Calling several commands in a row with one shared session would restore the stash after the first source, so the stash must be handed over to the end of the whole run.
- Commands signal failure with `raise typer.Exit(1)` (or `click` equivalent) and use defaults on every option, so they can be called directly as `scrape_x_command(ctx)`.
- Sources split cleanly in two:
  - **direct** (the store's own site): `humblebundle`, `greenmangaming`, `dailyindiegame`, `fanatical`, `digiphile`.
  - **aggregate** (third-party listings, skip bundles a direct scraper already covers): `isthereanydeal`, `dekudeals`.
- `dailyindiegame` opens a real browser window, so it is part of `all-direct` but gets a `--skip` escape hatch.
- Naming: `direct` / `aggregate`, since the CLAUDE.md and README already call them "dedicated scraper" and "aggregator".

## Commit 1: the `all` commands

New module `src/game_collections/scrape_all.py` (no private prefixes, own concern):

- `ScrapeKind` enum (`DIRECT`, `AGGREGATE`) and a frozen `ScraperSpec(name, kind, run)` dataclass.
- `SCRAPERS` registry in the order above, each `run(ctx, refresh, non_interactive)` calling the existing command function with only the options it supports.
- `run_scrapers(ctx, specs, refresh, non_interactive, skip) -> list[ScraperFailure]`:
  - For each spec, give the command a copy of the session via `dataclasses.replace(session, stashed=False)` so it still commits its own output separately (one commit per source, like manual runs) but does not restore the stash.
  - Catch `typer.Exit` with non-zero code and `(OSError, ValueError, RuntimeError)`, record `ScraperFailure(name, reason)`, log it, continue.
  - Do not catch `KeyboardInterrupt`; the stash restore below sits in a `finally`.
  - After the loop restore the autostash once via `git_ops.restore_autostash`, using the original session.
- In `cli.py` add `all`, `all-direct`, `all-aggregate` commands with `--refresh`, `--non-interactive` (passed to sources that prompt), and repeatable `--skip NAME`.
  `all` runs direct first, then aggregate.
- Final summary lists each failed source with its reason, prints to stderr, and exits 1 if any failed.

Tests in `tests/test_scrape_all.py`, in the style of `tests/test_cli.py`:

- order (direct before aggregate for `all`), one failing source does not stop the rest, exit code 1 plus summary at the end.
- with `--git`: a single autostash and a single restore around the whole run, one commit call per source.
- `--skip` and option passthrough.

## Commit 2: help text and deduplicated options

- New module `src/game_collections/scrape_options.py` with shared `Annotated` aliases: `ListsRootOption`, `ArchiveRootOption`, `RefreshOption(help=…)`, `NonInteractiveOption`, and a `url_option(help)` factory; replace the copies in the seven commands.
- Tag each command with `rich_help_panel="Direct sources"` / `"Aggregate sources"` (rich is a typer dependency) and prefix its first docstring line with `(direct)` / `(aggregate)` so shell completion shows it too.
- Document the kinds in the `scrape_app` help.
- Existing `tests/test_cli.py` and `tests/test_shell_completion.py` must stay green; add a help test for the panels.

## Docs

Root `README.md`: new "Scrape everything" paragraph.
`CLAUDE.md` CLI surface: mention `scrape all|all-direct|all-aggregate`.
`src/game_collections/sources/README.md`: the direct/aggregate split.

## Verification

- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest` (full suite) and `uv run game-collections validate`.
- `uv run game-collections scrape --help` and `scrape all --help` for the panels.
- Dry sanity run of `scrape all-aggregate --skip isthereanydeal --skip dekudeals` (no network, no-op) to check summary and exit code.
- No live scrape against real sites without asking.
