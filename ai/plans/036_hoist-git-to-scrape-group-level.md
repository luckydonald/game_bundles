# Hoist `--git` to `scrape` group level

## Context

`--git`/`--git-style` (autostash → run → commit the scrape's own output → restore stash) currently exist only on `scrape humblebundle` and `scrape isthereanydeal`, each duplicating the same head/autostash/commit/restore wiring inline. The user wants `--git` to become a flag on `scrape` itself, so every scraper (`humblebundle`, `greenmangaming`, `dailyindiegame`, `isthereanydeal`) inherits it instead of reimplementing it, or simply lacking it.

Because Click/Typer parse group options before the subcommand name, `--git` moves from `scrape humblebundle --git` to `scrape --git humblebundle`. This is a user-facing CLI syntax change, so docs, the two weekly GitHub Actions workflows, and existing tests need updating alongside the code.

## Implementation

### 1. `src/game_collections/git_ops.py` — shared session helpers
Add a small dataclass + two functions so the autostash/commit/restore sequencing lives in one place instead of being copy-pasted per subcommand:

```python
@dataclass
class ScrapeGitSession:
    enabled: bool
    style: str
    repository_root: Path
    pre_crawl_head: str | None
    stashed: bool
# end class ScrapeGitSession

def begin_scrape_git_session(repository_root: Path, enabled: bool, style: str) -> ScrapeGitSession:
    # captures head() + autostash() only when enabled; returns a disabled/no-op session otherwise
    ...

def finish_scrape_git_session(session: ScrapeGitSession, paths: Sequence[str], message: str) -> None:
    # no-op unless session.enabled; else commit_changed_paths(...) then restore_autostash(...) if stashed
    ...
```

### 2. `src/game_collections/cli.py` — group-level flag
- Add `@scrape_app.callback()` (`scrape_callback`) taking `git`/`git_style` (moved verbatim from the humblebundle/isthereanydeal signatures, same help text), validating `git_style` (existing echo+`Exit(2)` behavior), computing `repository_root = Path.cwd().resolve()`, and storing `ctx.obj = git_ops.begin_scrape_git_session(repository_root, git, git_style)`.
- Every `scrape_app.command(...)` function (`scrape_humblebundle_command`, `scrape_dailyindiegame_command`, `scrape_greenmangaming_command`, `scrape_isthereanydeal_command`) gains a `ctx: typer.Context` parameter, drops its own `git`/`git_style` params, local validation, and local `repository_root`/`pre_crawl_head`/`stashed` computation — reading `ctx.obj` (a `ScrapeGitSession`) instead.
- humblebundle and isthereanydeal: replace their existing `finally`-block git logic with `git_ops.finish_scrape_git_session(ctx.obj, paths, message)`, built from `_git_commit_message(...)` as today. Update the hardcoded invocation string from `"game-collections scrape humblebundle --git"` to `"game-collections scrape --git humblebundle"` (and the isthereanydeal equivalent).
- greenmangaming and dailyindiegame: **newly** add the same `finally`-block pattern.
  - greenmangaming: paths `["lists", "archives/greenmangaming", str(resolution_map)]`, summary "Archived this week's Green Man Gaming bundles", invocation `"game-collections scrape --git greenmangaming"`, unresolved-line built the same way as humblebundle's (it already tracks `unresolved` product IDs).
  - dailyindiegame: paths `["lists", "archives/dailyindiegame"]`, summary "Archived this week's DailyIndieGame bundles", invocation `"game-collections scrape --git dailyindiegame"`; this source has no resolver/unresolved concept, so the unresolved-line is a fixed string, e.g. `"No storefront resolution needed for this source."`.

### 3. Docs
- `CLAUDE.md`: rewrite the sentence `` `scrape humblebundle`/`scrape isthereanydeal` additionally take `--git` `` to state that `scrape` itself takes `--git`/`--git-style`, applying to all four scrape subcommands.

### 4. GitHub Actions workflows
- `.github/workflows/weekly-humblebundle-scrape.yml`: change `scrape humblebundle --non-interactive --git --git-style auto` → `scrape --git --git-style auto humblebundle --non-interactive`.
- `.github/workflows/weekly-isthereanydeal-scrape.yml`: change `scrape isthereanydeal --tab=live --git --git-style auto` → `scrape --git --git-style auto isthereanydeal --tab=live`.

### 5. Tests (`tests/test_cli.py`)
- `test_scrape_humblebundle_help_lists_git_flag` / `test_scrape_isthereanydeal_help_lists_git_flag`: repoint at `["scrape", "--help"]` (rename to something like `test_scrape_help_lists_git_flag`), since `--git` no longer shows in subcommand help.
- All `CliRunner().invoke(app, ["scrape", "humblebundle", "--git", ...])`-style calls: move `--git`/`--git-style ...` before the subcommand name, e.g. `["scrape", "--git", "humblebundle", "--non-interactive"]`.
- `test_scrape_humblebundle_git_style_rejects_invalid_value`: becomes `["scrape", "--git", "--git-style", "bogus", "humblebundle"]`.
- Update the literal invocation strings asserted in `test_git_commit_message_*` and `test_scrape_humblebundle_git_style_defaults_to_manual_wording` from `scrape humblebundle --git` to `scrape --git humblebundle`.
- Add equivalent git-flag coverage for `greenmangaming` and `dailyindiegame` (stash/scrape/commit/restore happy path is enough; mirror the existing humblebundle test's monkeypatch style).

### 6. `tests/test_git_ops.py`
- Add unit coverage for the new `begin_scrape_git_session`/`finish_scrape_git_session` helpers (enabled vs. disabled session, commit+restore sequencing) alongside the existing lower-level `head`/`autostash`/`commit_changed_paths`/`restore_autostash` tests.

## Verification
- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_cli.py tests/test_git_ops.py -q`
- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q` (full suite, since `cli.py` is central)
- Manually: `uv run game-collections scrape --help` shows `--git`/`--git-style` once at the group level; `uv run game-collections scrape humblebundle --help` no longer lists them; `uv run game-collections scrape --git greenmangaming --non-interactive` (against a scratch git repo/branch) exercises the new autostash/commit/restore path for a source that never had it before.
