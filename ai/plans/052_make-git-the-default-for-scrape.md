# Make `--git` the default for `scrape`

## Context

Todo `efd91050`: `game-collections scrape ...` should autostash, commit its own output and restore the stash by default.
Opting out is done with `--no-git`.
Today `--git` is a plain `bool` flag (default `False`) on `scrape_callback` in `src/game_collections/cli.py:195`, and every `scrape` subcommand reads the resulting `ScrapeGitSession` from `ctx.obj`.
So the change is isolated to that one option plus the callers and docs that rely on the old default.

Scope decision: only `scrape` changes.
`migrate` also has `--git`, but there `--git` implies `--apply` and the command is dry-run by default, so making it default would silently turn a safe dry-run into a write.
I leave `migrate` untouched and say so in the README.

## Changes

1. `src/game_collections/cli.py` `scrape_callback`: change the option to a boolean flag pair `"--git/--no-git"` with default `True`, and update the help text to say it is on by default and `--no-git` runs the scrape without touching git (no stash, no commit).
   `--git-style` stays as is; its help mentions `--git`, which still applies.
   Typer cannot take `--git=no` on a boolean flag, so `--no-git` is the one opt-out spelling.
2. `.github/workflows/weekly-humblebundle-scrape.yml` and `weekly-isthereanydeal-scrape.yml`: keep the explicit `--git --git-style auto` (harmless, self-documenting, and independent of the default).
   No change needed.
3. Tests (important: with `--git` on by default, a test that invokes `scrape` without the flag would run `git stash` in the real repo cwd):
   - `tests/test_cli.py:408` (`scrape greenmangaming --non-interactive`) and `tests/test_scrape_all.py` lines 43, 58, 61, 72, 86, 88: add `--no-git` after `scrape` so they never touch git.
   - Add a test in `tests/test_cli.py` that `scrape humblebundle` without any git flag runs the `head, autostash, scrape, commit, restore` sequence (same monkeypatch pattern as the existing test at line 281).
   - Add a test that `scrape --no-git humblebundle` makes no git calls at all.
   - Tests that already pass `--git` stay valid.
4. Docs: root `README.md` (the "Scraping everything" paragraph at line 68 and the scrape section) and `src/game_collections/sources/README.md` line 9 and 17 wording ("for a normal `scrape --git` run", "`--git`/CI"): state that git handling is on by default and `--no-git` disables it.
   Update `CLAUDE.md` CLI surface paragraph, where `--git` is described as an extra of `scrape humblebundle`/`scrape isthereanydeal`, to say it is the default for all scrape commands with `--no-git` to opt out.

## Verification

- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest` (full suite) and `uv run game-collections validate`.
- `uv run game-collections scrape --help` shows `--git / --no-git`.
- No schema regeneration needed (no model changes).
- No live scrape is run: the repo has a large uncommitted scrape output, and a default-on autostash would stash it.

## Out of scope

The next todo (`6ef5b7c0`, `--git-worktree`) builds on this default and is handled separately.
