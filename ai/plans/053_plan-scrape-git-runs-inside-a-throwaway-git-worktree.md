# Plan: `scrape --git` runs inside a throwaway git worktree

**Commit style:** Skill `/commit-with-lplp-style` is active — auto-commit following it for this implementation.

## Context

Todo `6ef5b7c0`: `scrape --git` (on by default) currently autostashes the root checkout, scrapes in place, commits and pops the stash.
That blocks using the checkout for the whole (long) scrape and relies on a stash-restore fallback.
Instead, `--git` should run the scrape in its own worktree and cherry-pick the result back.
Lifecycle: create and `cd`, run, commit, cherry-pick into the root, remove branch and worktree dir.

Decisions from the user:

- Refuse to start when the root checkout is dirty (no stash, no copying of dirty state).
- The worktree lives in the repo at `scripts/.worktrees/scrape/<subcommand>/<YYYY-MM-DD_HH-MM-SS_+ZZZZ>/`, where `<subcommand>` is `all`, `humblebundle`, `isthereanydeal`, etc.

My defaults for the unanswered parts:

- On a cherry-pick conflict: `cherry-pick --abort`, keep the branch and worktree, print their paths and exit non-zero, so no work is lost.
- Scope is `scrape` only. `migrate --git` keeps the autostash path (its flow is unchanged).

## Design

New module `src/game_collections/git_worktree.py` (own concern, per the "split modules" preference), all git calls through the existing `git_ops._run`-style subprocess helper (expose it as a public `run_git` in `git_ops.py` rather than importing a private name).

- `create_scrape_worktree(repository_root, subcommand, now) -> ScrapeWorktree`:
  - Refuse if `git status --porcelain -- . :!ai/errors` is non-empty (same pathspec exclusion as `autostash`), raising `GitAutocommitError` with a hint to commit or use `--no-git-worktree`.
  - `git worktree add -b scrape/<subcommand>/<timestamp> <path> HEAD`.
  - `ScrapeWorktree` dataclass: `root`, `path`, `branch`, `base_head`.
- `integrate_scrape_worktree(worktree)`:
  - No commits in `base_head..branch`: remove worktree and branch.
  - Otherwise `git cherry-pick base_head..branch` in the root.
  - On success: `git worktree remove --force`, `git branch -D`.
  - On conflict: abort the pick, keep everything, raise `GitAutocommitError` naming path and branch.

Changes in `git_ops.py`:

- `ScrapeGitSession` gets `worktree: ScrapeWorktree | None` and `defer_close: bool`. `repository_root` is the worktree path while one is active, so every existing `git_session.repository_root` use (all `scrape_*` commands, `commit_changed_paths`) works unchanged.
- `begin_scrape_git_session(..., worktree: bool, subcommand: str)`:
  - worktree mode: create the worktree, `os.chdir` into it (the relative defaults `lists/`, `archives/`, `config/...` resolve against the cwd), and skip the autostash;
  - otherwise the current autostash behaviour.
- New `close_scrape_git_session(session)`: chdir back to the root, then `integrate_scrape_worktree` or `restore_autostash`.
- `finish_scrape_git_session` commits, then calls `close_scrape_git_session` unless `defer_close`.

Changes in `cli.py`:

- `scrape_callback` gains `--git-worktree/--no-git-worktree` (default on, only effective with `--git`). It needs the invoked subcommand name: use `ctx.invoked_subcommand`, since the callback runs before it.
- The callback captures the original root with `git_ops.repository_root(Path.cwd())` before the chdir.

Changes in `scrape_all.py`:

- `run_scrapers` already swaps in `stashed=False` per source so only the very end restores. Replace that with `defer_close=True` and call `close_scrape_git_session(session)` in the `finally`, which also covers the worktree. Each source's commit lands as its own commit on the one `scrape/all/...` branch, and all of them are cherry-picked at the end.

Other:

- `.gitignore`: add `scripts/.worktrees/` (otherwise the in-repo worktree makes the root look dirty).
- Workflows in `.github/` pass `--no-git-worktree` (clean CI checkout, no benefit), keeping `--git-style auto`.
- Docs: root `README.md` (the `--git` paragraph near line 68), the CLI table in `CLAUDE.md`, `sources/README.md` if it mentions the stash flow.
- Known limitation, documented: the worktree only has tracked files, so gitignored local state (e.g. the DailyIndieGame browser profile) is absent. If that bites, `--no-git-worktree` is the escape hatch.

## Tests

`tests/test_git_worktree.py` and additions to `tests/test_scrape_all.py` / `tests/test_cli.py`, on temporary repos like `tests/test_git_ops.py`:

- refuses a dirty root, ignores a dirty `ai/errors/`;
- creates the worktree at the expected path and branch from HEAD;
- commit in the worktree, integrate: the commit appears on the root branch, the worktree dir and the branch are gone, the root working tree is clean;
- no-change run removes worktree and branch without a commit;
- cherry-pick conflict keeps worktree and branch, leaves the root with no pick in progress, and raises;
- `scrape all` produces several commits and integrates once, at the end;
- the CLI flag combinations: `--no-git`, `--no-git-worktree` (old autostash path unchanged).

Then the full suite (`uv run pytest`), `game-collections validate` and `schema` (no model change, so no drift expected).

## Commits

1. `git_worktree.py` plus `git_ops` session changes plus tests.
2. CLI flag, `scrape_all`, `.gitignore`, workflow flag, docs.
