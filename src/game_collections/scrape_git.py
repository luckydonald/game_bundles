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
class WorktreeHandle:
    """The scrape's worktree plus the bookkeeping to close it exactly once.

    A mutable object shared by reference, so the per-source session copies `scrape all` makes
    with `dataclasses.replace` all see the same `closed` flag.
    """

    worktree: git_worktree.ScrapeWorktree
    allow_dirty: bool
    closed: bool = False

# end class WorktreeHandle


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

    Idempotent for worktrees, so it is safe both as the normal end of a run and as the
    safety net registered on the Click context for runs that exit before reaching it.
    """
    if not session.enabled:
        return
    # end if
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
    """Change back into the original checkout and cherry-pick the worktree's commits there, once."""
    if handle.closed:
        return
    # end if
    handle.closed = True
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
