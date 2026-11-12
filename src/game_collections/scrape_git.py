"""The `--git` session `scrape` threads through its subcommands: autostash pending changes, run,
commit the scrape's own output, then restore the stash afterward."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import typer

from game_collections import git_ops, git_worktree


@dataclass
class SessionGuard:
    """Closes a session exactly once, whichever of the normal finish step and the safety net gets there first.

    A mutable object shared by reference, so the per-source session copies `scrape all` makes
    with `dataclasses.replace` all see the same `closed` flag.
    """

    closed: bool = False

# end class SessionGuard


@dataclass(frozen=True)
class WorktreeHandle:
    """The scrape's worktree plus how to integrate it again."""

    worktree: git_worktree.ScrapeWorktree
    allow_dirty: bool

# end class WorktreeHandle


@dataclass(frozen=True)
class ScrapeGitConfig:
    """What `scrape`'s group options asked for; no git has been touched yet.

    The group callback only validates the options and stores this, because Click has not parsed
    the subcommand's own options (or `--help`) at that point. A subcommand turns it into a real
    session with `start_scrape_git_session` once it actually runs.
    """

    enabled: bool
    style: str
    repository_root: Path
    worktree_subcommand: str | None
    worktree_base: Path | None
    allow_dirty: bool

# end class ScrapeGitConfig


@dataclass
class ScrapeGitSession:
    """State threaded from `scrape`'s group-level `--git` flag through to each
    subcommand's `finally` block, so the autostash/commit/restore sequencing lives
    in one place instead of being copy-pasted per subcommand."""

    enabled: bool
    style: str
    repository_root: Path
    pre_crawl_head: str | None
    stashed: bool
    handle: WorktreeHandle | None = None
    """Set while the scrape runs in a worktree; `repository_root` is then the worktree's path."""
    defer_close: bool = False
    """`scrape all` sets this on its per-source copies so only the very end of the run integrates the worktree."""
    guard: SessionGuard = field(default_factory=SessionGuard)

# end class ScrapeGitSession


def begin_scrape_git_session(
    repository_root: Path,
    enabled: bool,
    style: str,
    worktree_subcommand: str | None = None,
    worktree_base: Path | None = None,
    allow_dirty: bool = False,
) -> ScrapeGitSession:
    """Prepare the `--git` session, only when `--git` is enabled.

    With a `worktree_subcommand` the scrape runs in a fresh worktree: the process changes into it
    (the relative `lists/`, `archives/` and `config/` defaults then resolve there) and
    `repository_root` points at it. Without one, `HEAD` is captured and pending changes are autostashed.
    """
    if not enabled:
        return ScrapeGitSession(
            enabled=False, style=style, repository_root=repository_root, pre_crawl_head=None, stashed=False
        )
    # end if
    if worktree_subcommand is not None:
        worktree = git_worktree.create_scrape_worktree(
            repository_root, worktree_subcommand, datetime.now().astimezone(), worktree_base, allow_dirty
        )
        os.chdir(worktree.path)
        return ScrapeGitSession(
            enabled=True,
            style=style,
            repository_root=worktree.path,
            pre_crawl_head=None,
            stashed=False,
            handle=WorktreeHandle(worktree=worktree, allow_dirty=allow_dirty),
        )
    # end if
    pre_crawl_head = git_ops.head(repository_root)
    stashed = git_ops.autostash(repository_root)
    return ScrapeGitSession(
        enabled=True,
        style=style,
        repository_root=repository_root,
        pre_crawl_head=pre_crawl_head,
        stashed=stashed,
    )
# end def begin_scrape_git_session


def close_scrape_git_session(session: ScrapeGitSession) -> None:
    """Hand the checkout back: integrate the worktree into the original checkout, or restore the autostash.

    Runs at most once per session (see `SessionGuard`), so it is safe both as the normal end of a
    run and as the safety net registered on the Click context for runs that exit before reaching it.
    """
    if not session.enabled or session.guard.closed:
        return
    # end if
    session.guard.closed = True
    if session.handle is not None:
        close_worktree(session.handle)
        return
    # end if
    if session.stashed:
        assert session.pre_crawl_head is not None
        git_ops.restore_autostash(session.repository_root, session.pre_crawl_head)
    # end if
# end def close_scrape_git_session


def close_worktree(handle: WorktreeHandle) -> None:
    """Change back into the original checkout and cherry-pick the worktree's commits there."""
    worktree = handle.worktree
    os.chdir(worktree.root)
    try:
        git_worktree.integrate_scrape_worktree(
            worktree, allow_dirty=handle.allow_dirty, interactive=git_worktree.is_interactive()
        )
    except git_ops.GitAutocommitError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(1) from error
    # end try
# end def close_worktree


def start_scrape_git_session(ctx: typer.Context) -> ScrapeGitSession:
    """Turn the group's `ScrapeGitConfig` into a live session; call this first in a subcommand body.

    Only here, after Click has parsed the subcommand's options and handled `--help`, does git get
    touched, so help and option errors have no side effects. The close hook is registered right
    away for both modes, so a failure before the subcommand's own `finally` (or Ctrl-C) still
    restores the stash or integrates the worktree.
    A `ScrapeGitSession` already in `ctx.obj` (the per-source copies of `scrape all`) is returned as is.
    """
    if isinstance(ctx.obj, ScrapeGitSession):
        return ctx.obj
    # end if
    config: ScrapeGitConfig = ctx.obj
    try:
        session = begin_scrape_git_session(
            config.repository_root,
            config.enabled,
            config.style,
            worktree_subcommand=config.worktree_subcommand,
            worktree_base=config.worktree_base,
            allow_dirty=config.allow_dirty,
        )
    except git_ops.GitAutocommitError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(1) from error
    # end try
    ctx.obj = session
    ctx.call_on_close(lambda: close_scrape_git_session(session))
    return session
# end def start_scrape_git_session


def finish_scrape_git_session(session: ScrapeGitSession, paths: Sequence[str], message: str) -> None:
    """Commit the scrape's own output and restore the autostash, only when `--git` is enabled."""
    if not session.enabled:
        return
    # end if
    git_ops.commit_changed_paths(session.repository_root, paths, message)
    if session.defer_close:
        return
    # end if
    close_scrape_git_session(session)
# end def finish_scrape_git_session
