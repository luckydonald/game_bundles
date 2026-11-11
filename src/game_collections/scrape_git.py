"""The `--git` session `scrape` threads through its subcommands: autostash pending changes, run,
commit the scrape's own output, then restore the stash afterward."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from game_collections import git_ops


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

# end class ScrapeGitSession


def begin_scrape_git_session(repository_root: Path, enabled: bool, style: str) -> ScrapeGitSession:
    """Capture `HEAD` and autostash pending changes, only when `--git` is enabled."""
    if not enabled:
        return ScrapeGitSession(
            enabled=False, style=style, repository_root=repository_root, pre_crawl_head=None, stashed=False
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


def finish_scrape_git_session(session: ScrapeGitSession, paths: Sequence[str], message: str) -> None:
    """Commit the scrape's own output and restore the autostash, only when `--git` is enabled."""
    if not session.enabled:
        return
    # end if
    git_ops.commit_changed_paths(session.repository_root, paths, message)
    if session.stashed:
        assert session.pre_crawl_head is not None
        git_ops.restore_autostash(session.repository_root, session.pre_crawl_head)
    # end if
# end def finish_scrape_git_session
