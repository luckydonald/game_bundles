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
- Conflicting flags are an error: `--no-git` together with any explicitly given `--git-*` option (`--git-style`, `--git-worktree`, `--no-git-worktree`, `--git-worktree-allow-dirty`) exits 2 with a message.
  Typer can tell explicit from default: `ctx.get_parameter_source(name)` (verified present in the vendored click) is `COMMANDLINE` or `ENVIRONMENT` versus `DEFAULT`, so defaults never trigger it.
  Likewise `--no-git-worktree` with `--git-worktree PATH` or `--git-worktree-allow-dirty` is an error.
  This makes `--no-git --git-style x` newly invalid; the workflows only combine `--git` with `--git-style auto`, so they are unaffected.

Local state that is gitignored:

- A tracked `.worktree_unignore` in the root lists gitignored files or directories the scrape needs, one per line, `#` comments, optional mode suffix: `path`, `path symlink` (default), `path hardlink`, `path copy`.
- Validated before the worktree is created, and any problem aborts the whole run as a configuration error: every entry must exist in the root and must actually be gitignored (`git check-ignore -q`); tracked, absolute, `..`-escaping, unknown-mode, or duplicate entries are errors too.
- After creating the worktree, each entry is linked or copied to the same relative path in the worktree.
- Shipped with only comments documenting the format and no entries: because a missing entry now aborts, listing `.env` would break machines and CI without one. `.env` (ignored via `.gitignore` line 776) is the natural first candidate to add locally.
  I checked the DailyIndieGame example from the todo: its browser profile is a `tempfile.mkdtemp` dir (`sources/dailyindiegame/crawler.py:70`), not repo-local state, so nothing to list for it.

Finish, on success:

1. Commit in the worktree (existing `commit_changed_paths`), `chdir` back to the root.
2. Cherry-pick `base..branch` into the root.
3. Remove the linked or copied unignore entries from the worktree (symlinks and hardlinks are unlinked, never followed; copies are deleted).
4. `git worktree remove` **without** `--force`.
5. `git branch -D` the branch.
Zero commits: skip step 2.

No `--force`, deliberately: with the unignore entries gone, git's own refusal protects us.
After the commit, a worktree that is still dirty or has untracked files means the scrape wrote something outside the committed paths (for example a config file not in the `finish_scrape_git_session` path list).
Under the old autostash flow such files simply stayed in the root; here silently deleting them would lose them, so git's refusal is the safety net.
If removal is refused, raise `GitAutocommitError` after the cherry-pick succeeded, keep the worktree, and print `git status --short` from it plus its path.
The branch is not removed by `git worktree remove` (it only deletes the directory and its admin data), hence the explicit `branch -D` in step 5; `-D` rather than `-d` because the cherry-picked commits are copies, so git does not consider the branch merged.

Finish, on cherry-pick conflict (`cherry-pick --abort` first, so the root is left untouched):

- The tip is always preserved: tag `bak/<full-sha>` (same naming as `scripts/tag_backup.py`) and the branch `scrape/<sub>/<date>` stays, no renaming.
- Print the details first: non-recursive diff of the branch against the root `HEAD` (`git diff --shortstat` plus `--dirstat=files,0`, per directory rather than per file) and `git status --short` inside the worktree.
- If stdin and stdout are TTYs, ask `Cherry pick failed (details above). Already discard no longer needed worktree? [Y/n]`.
  Enter, `y`, `Y` discard the worktree directory; `n`, `N` keep it; anything else repeats the question.
- Non-interactive: discard without asking, after printing the details, the tag and the branch name.
- Discarding the worktree also removes the unignore entries first and uses plain `git worktree remove`; if untracked or modified files still make git refuse, that is reported (they are in the printed status) and the directory is kept.
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
- `.gitignore`: `scripts/.worktrees/`. Workflows in `.github/` pass `--no-git-worktree` (also keeps their "Commit any files --git missed" safety-net step working, which could not see files left in a worktree).
- Docs: root `README.md` (`--git` paragraph, new options, `.worktree_unignore`), the CLI paragraph of `CLAUDE.md`, `sources/README.md` if it mentions the stash flow.

## Commits (each with its tests, suite green)

1. `[git] git_ops: ai: Run: Exposed `run_git` publicly.` — pure rename, no behaviour change (move-first rule).
2. `[git] worktrees: …` — `git_worktree.py` naming, create, integrate (success path, zero-commit path), tests.
3. `[git] worktrees: …` — conflict handling: abort, `bak/` tag, details, confirm prompt, discard or keep, tests.
4. `[git] worktrees: …` — `.worktree_unignore` loader, validation (exists and is ignored), linking and cleanup (symlink, hardlink, copy), tests.
5. `[git] worktrees: …` — dirty-root refusal and `--git-worktree-allow-dirty` autostash around the cherry-pick, tests.
6. `[cli] scrape: …` — session integration, `scrape_callback` options and the `--no-git` vs `--git-*` conflict check, `scrape_all` deferred close, `.gitignore`, workflow flags, tests in `test_cli.py` / `test_scrape_all.py`.
7. `[docs] …` — README, `CLAUDE.md`, sources README.

## Verification

All tests on temporary repos like `tests/test_git_ops.py`, covering: dirty refusal and `ai/errors` exemption; naming; success integrate leaves a clean root with no worktree or branch; zero-commit; conflict non-interactive (tag, branch kept, dir gone); conflict interactive Y / n / invalid-then-Y; unignore validation failures abort before anything is created; symlink cleanup leaves the target intact; removal without force is refused and reported when the worktree has stray files; `--no-git` plus each `--git-*` flag errors while defaults do not; allow-dirty restores the root's changes; `scrape all` integrates once at the end; `--no-git`, `--no-git-worktree`, `--git-worktree ''`, `--git-worktree PATH`.
Then `uv run pytest`, `game-collections validate`, `game-collections schema` (no model change, no drift expected), and one real `scrape` dry exercise with a stubbed source in a temp repo.
