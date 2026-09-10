"""Git plumbing backing the `--git` scrape flag: autostash pending changes,
commit a scrape's own output, then reliably restore the stash afterward."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


class GitAutocommitError(RuntimeError):
    """A `--git` git operation failed in a way that needs a human to look."""

# end class GitAutocommitError


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
    pre_crawl_head = head(repository_root)
    stashed = autostash(repository_root)
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
    commit_changed_paths(session.repository_root, paths, message)
    if session.stashed:
        assert session.pre_crawl_head is not None
        restore_autostash(session.repository_root, session.pre_crawl_head)
    # end if
# end def finish_scrape_git_session


_UNMERGED_STATUS = re.compile(r"^(?:DD|AU|UD|UA|DU|AA|UU) ")
_UNTRACKED_COLLISION = "could not restore untracked files from stash"


def _run(repository_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repository_root,
        check=True,
        text=True,
        capture_output=True,
    )
# end def _run


def head(repository_root: Path) -> str:
    """Return the current `HEAD` commit hash."""
    return _run(repository_root, "rev-parse", "HEAD").stdout.strip()
# end def head


def repository_root(start: Path) -> Path:
    """Return the top-level directory of the git repository containing `start`."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=start,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise GitAutocommitError(
            f"not inside a git repository ({start}): {(result.stderr or result.stdout).strip()}"
        )
    # end if
    return Path(result.stdout.strip())
# end def repository_root


def autostash(repository_root: Path) -> bool:
    """Stash pending changes, including untracked files, before a scrape.

    Excludes `ai/errors/` from the pathspec: it's the convention directory for
    error/session logs a user may be actively `tee`-ing a running `--git`
    invocation's own output into. `--include-untracked` unlinks any untracked
    path it stashes, so a log file being written there would keep its
    already-open file descriptor pointed at a now-detached inode - restoring
    the stash afterward then recreates the path with only the handful of
    bytes captured at stash time, silently discarding the rest of the log.
    Leaving the directory out of the pathspec means the stash never touches
    it, so a concurrently written log survives untouched.

    Returns whether anything was actually stashed, so a later restore step
    knows whether to bother.
    """
    result = _run(
        repository_root,
        "stash", "push", "--include-untracked", "-m", "pre-scrape autostash",
        "--", ".", ":!ai/errors",
    )
    return "No local changes to save" not in result.stdout
# end def autostash


def commit_changed_paths(repository_root: Path, paths: Sequence[str], message: str) -> bool:
    """Commit `paths` if any of them changed. Returns whether a commit was made."""
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", *paths],
        cwd=repository_root,
        check=True,
        text=True,
        capture_output=True,
    )
    if not status.stdout.strip():
        return False
    # end if
    _run(repository_root, "add", "--", *paths)
    _run(repository_root, "commit", "-m", message)
    return True
# end def commit_changed_paths


def _unmerged_paths(repository_root: Path) -> list[str]:
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repository_root,
        text=True,
        capture_output=True,
    )
    return [line[3:] for line in status.stdout.splitlines() if _UNMERGED_STATUS.match(line)]
# end def _unmerged_paths


def restore_autostash(repository_root: Path, pre_crawl_head: str) -> None:
    """Restore a stash created by `autostash`, guaranteeing it succeeds.

    A plain `git stash pop` can conflict with paths the scrape's own commit
    just changed. If it does, fall back to reverting only the conflicting
    paths to their pre-crawl content - already safe in the crawl commit's
    history, so losing the working-tree copy of just those edits is fine -
    and reapplying the stash on top of that. What must not be lost is the
    user's pre-existing local changes.
    """
    pop = subprocess.run(["git", "stash", "pop"], cwd=repository_root, text=True, capture_output=True)
    if pop.returncode == 0:
        return
    # end if
    conflicting = _unmerged_paths(repository_root)
    if not conflicting and _UNTRACKED_COLLISION in pop.stderr:
        # All tracked changes already merged cleanly; git only bailed because
        # untracked files from the stash collide with untracked files already
        # sitting in the working tree (unrelated to this stash). Nothing was
        # lost, so the stash is redundant now.
        _run(repository_root, "stash", "drop")
        return
    # end if
    if conflicting:
        _run(repository_root, "checkout", pre_crawl_head, "--", *conflicting)
        apply_result = subprocess.run(
            ["git", "stash", "apply"], cwd=repository_root, text=True, capture_output=True
        )
        if apply_result.returncode == 0 or (
            not _unmerged_paths(repository_root) and _UNTRACKED_COLLISION in apply_result.stderr
        ):
            _run(repository_root, "stash", "drop")
            return
        # end if
    # end if
    raise GitAutocommitError(
        "Could not automatically restore the pre-scrape stash. "
        "Resolve manually via `git stash list` / `git stash show -p`, then `git stash drop`."
    )
# end def restore_autostash
