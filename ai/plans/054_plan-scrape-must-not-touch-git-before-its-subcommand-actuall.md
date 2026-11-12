# Plan: `scrape` must not touch git before its subcommand actually runs

**Commit style:** Skill `/commit-with-lplp-style` is active — auto-commit following it for this implementation.

## Context

While testing the worktree feature I ran `scrape --no-git-worktree humblebundle --non-interactive --git --git-style auto --help`.
`--git` after the subcommand is an unknown option, so Click failed with `No such option`, but the `scrape` group callback had already run `begin_scrape_git_session`, which autostashed the real checkout (all uncommitted work plus untracked files).
Nothing restored it, because only the subcommand bodies' `finally` blocks call `finish_scrape_git_session`.
I recovered with `git stash pop`; nothing was lost.

Root causes, all in the same design flaw: the group callback has git side effects, and the restore lives in a `finally` that only exists later.

1. The `scrape` group callback (`cli.py` `scrape_callback`) starts the session, i.e. stashes or creates the worktree, before Click has parsed the subcommand's own options.
   So any parse error, and `scrape <subcommand> --help` too, does the side effect and then exits with nothing to undo it.
   `--help` on a dirty checkout currently even fails with the dirty-worktree error instead of printing help (seen in the same session).
2. Each subcommand calls `_migrate_source_archives(...)` between reading `ctx.obj` and entering its `try`/`finally`, so an exception there also strands the stash.
3. The `call_on_close` safety net added for worktrees covers worktree sessions only, not the autostash flow.

## Design

Make the group callback side-effect free and start the session lazily, inside the subcommand body, with a safety net for both modes.

`scrape_git.py`:

- New `ScrapeGitConfig` dataclass: `enabled`, `style`, `repository_root`, `worktree_subcommand`, `worktree_base`, `allow_dirty`.
  It is what `scrape_callback` stores in `ctx.obj` after validating the options (all the existing exit-2 checks stay in the callback, since they are pure).
- New `start_scrape_git_session(ctx) -> ScrapeGitSession`, called as the first statement of every `scrape` subcommand body:
  - if `ctx.obj` already is a `ScrapeGitSession` (the `scrape all` per-source copies), return it unchanged;
  - otherwise call `begin_scrape_git_session` from the config, store the session in `ctx.obj`, and register `ctx.call_on_close(lambda: close_scrape_git_session(session))` for both modes;
  - convert `GitAutocommitError` to `error: …` and `typer.Exit(1)`, the handling that now sits in the callback.
- Generalise the shared close guard: `WorktreeHandle.closed` becomes a small shared `SessionGuard` (mutable, shared by the `dataclasses.replace` copies) that also covers the stash path, so the restore runs exactly once whether `finish_scrape_git_session` or the close net gets there first.
  The existing `defer_close` behaviour of `scrape all` is unchanged.

`cli.py` and `scrape_all.py`:

- `scrape_callback` no longer calls `begin_scrape_git_session`; it builds and stores the `ScrapeGitConfig`.
- The seven subcommands replace `git_session = ctx.obj` with `git_session = scrape_git.start_scrape_git_session(ctx)`; `scrape all`, `all-direct` and `all-aggregate` start the session at the top of their own bodies the same way, before `run_scrapers` swaps the per-source copies in.
- `migrate` is not affected: it begins its session after all argument checks and its `try`/`finally` follows immediately.

Why this fixes each cause: help and parse errors never reach the body, so no side effect happens at all; an exception between start and the `try` is caught by the close net; Ctrl-C and unexpected exceptions also close the Click context.

## Commits

1. `[git] scrape session: …` — `ScrapeGitConfig`, `start_scrape_git_session`, the shared guard, and the close net for the stash path, with unit tests in `tests/test_scrape_worktree.py` or a new `tests/test_scrape_git.py`.
2. `[cli] scrape: …` — callback stores the config only; subcommands and `scrape all` start the session lazily; updates to existing tests where they relied on the callback side effect.
3. `[docs] …` — one sentence in the README and `CLAUDE.md` that git is only touched once the subcommand runs, so `--help` and option errors are side-effect free.

Also after the work: save a feedback memory that the CLI must not be exercised against the user's real checkout for experiments (use a temporary repository), since this incident came from doing exactly that.

## Verification

New tests on temporary repositories (cwd inside the repo, real git, no network), each for both the worktree mode and `--no-git-worktree`:

- `scrape <subcommand> --help` on a dirty checkout exits 0 and leaves it untouched: no stash, no worktree, cwd unchanged.
- An unknown option after the subcommand (the exact failing command from the incident) exits 2 with the working tree and untracked files intact and `git stash list` unchanged.
- `_migrate_source_archives` raising before the `try` still restores the stash, or removes the worktree.
- The normal path restores exactly once (close net after `finish` is a no-op, no `stash pop` error).
- `scrape all` still integrates or restores exactly once at the end.

Then the full `uv run pytest` and `game-collections validate`.
Manual checks only in a throwaway clone, never in this checkout.
