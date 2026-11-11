# Plan: `scrape --git` runs inside a throwaway git worktree

**Commit style:** Skill `/commit-with-lplp-style` is active — auto-commit following it for this implementation.

## Context

Todo `6ef5b7c0`: `scrape --git` (on by default) currently autostashes the root checkout, scrapes in place, commits and pops the stash.
That blocks using the checkout for the whole (long) scrape and relies on a stash-restore fallback.
Instead, `--git` runs the scrape in its own worktree and cherry-picks the result back.
Lifecycle: create and `cd`, run, commit, cherry-pick into the root, remove branch and worktree dir.
Scope is `scrape` only; `migrate --git` keeps its autostash flow.

## Behaviour

Naming, with `<sub>` = `all`, `humblebundle`, `isthereanydeal`, … and `<date>` = `YYYY-MM-DD_HH-MM-SS_+ZZZZ`:

- Worktree directory: `scripts/.worktrees/scrape/<sub>/<date>/` (gitignored).
- Branch: `scrape/<sub>/<date>`.
  The user wrote `.scrape/…` with a leading dot, which git rejects (a ref path component cannot start with `.`), so I use `scrape/…`, matching the directory.

Starting state:

- The root must be clean (`git status --porcelain -- . :!ai/errors`), otherwise abort with a hint naming `--git-worktree-allow-dirty` and `--no-git-worktree`.
- `--git-worktree-allow-dirty` lets it start anyway.
  The worktree still starts from `HEAD`; the root's pending changes are autostashed (existing `autostash`) right before the cherry-pick and restored afterwards (existing `restore_autostash` with its conflict fallback).

Options on the `scrape` group (Typer 0.26 cannot do an optional-value flag, see memory `reference_typer_optional_value_flag_limitation`, so no bare `--git-worktree`):

- `--git-worktree PATH` (default `''`): the base directory the `<sub>/<date>` folders are created under. `''` keeps the default `scripts/.worktrees/scrape`. Relative paths resolve against the root.
- `--no-git-worktree`: separate boolean, turns worktrees off and gives the old autostash flow.
- `--git-worktree-allow-dirty`.
- Only effective together with `--git` (as before, `--no-git` wins).

Local state that is gitignored:

- A tracked `.worktree_unignore` in the root lists gitignored files or directories the scrape needs, one per line, `#` comments, optional mode suffix: `path`, `path symlink` (default), `path hardlink`, `path copy`.
- After creating the worktree, each existing entry is linked or copied to the same relative path in the worktree. Missing entries are skipped with a note. Entries that are tracked by git, absolute, or escape the root via `..` are an error.
- Seed content: `.env` (the only repo-local ignored state I could verify, via `.gitignore` line 776).
  I checked the DailyIndieGame example from the todo: its browser profile is a `tempfile.mkdtemp` dir (`sources/dailyindiegame/crawler.py:70`), not repo-local state, so nothing to list for it.

Finish, on success: commit in the worktree (existing `commit_changed_paths`), `chdir` back, cherry-pick `base..branch` into the root, `git worktree remove --force`, `git branch -D`.
Zero commits: just remove worktree and branch.

Why `--force` on removal: `git worktree remove` refuses any worktree that has untracked or ignored files, and ours always does (the linked `.env`, scrape caches, a partly written offer).
It is only reached after the commits are safely integrated, or after the user or non-interactive default agreed to discard on failure, so there is nothing of value that force can destroy.
Symlinked entries are unlinked, not followed, so the root's real files are untouched (covered by a test).

Finish, on cherry-pick conflict (`cherry-pick --abort` first, so the root is left untouched):

- The tip is always preserved: tag `bak/<full-sha>` (same naming as `scripts/tag_backup.py`) and the branch `scrape/<sub>/<date>` stays, no renaming.
- Print the details first: non-recursive diff of the branch against the root `HEAD` (`git diff --shortstat` plus `--dirstat=files,0`, per directory rather than per file) and `git status --short` inside the worktree.
- If stdin and stdout are TTYs, ask `Cherry pick failed (details above). Already discard no longer needed worktree? [Y/n]`.
  Enter, `y`, `Y` discard the worktree directory (`worktree remove --force`); `n`, `N` keep it; anything else repeats the question.
- Non-interactive: discard without asking, after printing the details, the tag and the branch name.
- Either way exit non-zero with the `git cherry-pick <base>..<branch>` command to retry by hand.

## Design

New module `src/game_collections/git_worktree.py` (own concern), plus a public `run_git` in `git_ops.py` replacing the private `_run` for reuse.
Pieces, each small and separately testable:

- `worktree_paths`: path and branch naming from `<sub>`, timestamp and base directory.
- `unignore.py`-style loader: parse `.worktree_unignore` into `(path, mode)` entries and apply them (`link_local_state`).
- `create_scrape_worktree`, `integrate_scrape_worktree`, `preserve_failed_branch` (tag + details), `confirm_discard(input_fn, interactive)`.
- `ScrapeGitSession` gains `worktree: ScrapeWorktree | None`, `defer_close: bool`, `allow_dirty: bool`; `repository_root` is the worktree path while one is active, so every `git_session.repository_root` use in `cli.py` keeps working.
- `begin_scrape_git_session` creates the worktree and `os.chdir`s into it (relative defaults like `lists/` and `config/…` resolve against the cwd); `close_scrape_git_session` does chdir-back plus integrate (or the old `restore_autostash`); `finish_scrape_git_session` commits then closes unless `defer_close`.
- `scrape_callback` in `cli.py` takes the new options, finds the real root with `git_ops.repository_root(Path.cwd())` before the chdir, and gets `<sub>` from `ctx.invoked_subcommand`.
- `scrape_all.run_scrapers`: replace the per-source `stashed=False` trick with `defer_close=True` and call `close_scrape_git_session` in its `finally`; every source's commit lands on the one `scrape/all/<date>` branch and is cherry-picked at the end.
- `.gitignore`: `scripts/.worktrees/`. Workflows in `.github/` pass `--no-git-worktree`.
- Docs: root `README.md` (`--git` paragraph, new options, `.worktree_unignore`), the CLI paragraph of `CLAUDE.md`, `sources/README.md` if it mentions the stash flow.

## Commits (each with its tests, suite green)

1. `[git] git_ops: ai: Run: Exposed `run_git` publicly.` — pure rename, no behaviour change (move-first rule).
2. `[git] worktrees: …` — `git_worktree.py` naming, create, integrate (success path, zero-commit path), tests.
3. `[git] worktrees: …` — conflict handling: abort, `bak/` tag, details, confirm prompt, discard or keep, tests.
4. `[git] worktrees: …` — `.worktree_unignore` loader and linking (symlink, hardlink, copy), tests.
5. `[git] worktrees: …` — dirty-root refusal and `--git-worktree-allow-dirty` autostash around the cherry-pick, tests.
6. `[cli] scrape: …` — session integration, `scrape_callback` options, `scrape_all` deferred close, `.gitignore`, workflow flags, tests in `test_cli.py` / `test_scrape_all.py`.
7. `[docs] …` — README, `CLAUDE.md`, sources README.

## Verification

All tests on temporary repos like `tests/test_git_ops.py`, covering: dirty refusal and `ai/errors` exemption; naming; success integrate leaves a clean root with no worktree or branch; zero-commit; conflict non-interactive (tag, branch kept, dir gone); conflict interactive Y / n / invalid-then-Y; symlink removal leaves the target intact; allow-dirty restores the root's changes; `scrape all` integrates once at the end; `--no-git`, `--no-git-worktree`, `--git-worktree ''`, `--git-worktree PATH`.
Then `uv run pytest`, `game-collections validate`, `game-collections schema` (no model change, no drift expected), and one real `scrape` dry exercise with a stubbed source in a temp repo.
