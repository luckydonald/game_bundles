"""Git plumbing backing the `--git` scrape flag: autostash pending changes,
commit a scrape's own output, then reliably restore the stash afterward."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Sequence
from pathlib import Path


class GitAutocommitError(RuntimeError):
    """A `--git` git operation failed in a way that needs a human to look."""

# end class GitAutocommitError


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

    Returns whether anything was actually stashed, so a later restore step
    knows whether to bother.
    """
    result = _run(repository_root, "stash", "push", "--include-untracked", "-m", "pre-scrape autostash")
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
