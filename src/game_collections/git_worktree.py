"""Throwaway git worktrees for `scrape --git`: the scrape runs on its own branch in its own
directory, and its commits are cherry-picked back into the invoking checkout afterwards, so the
checkout stays usable (and unstashed) for the whole run."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from game_collections import git_ops
from game_collections.git_ops import GitAutocommitError
from game_collections.worktree_unignore import UnignoreEntry, link_local_state, load_unignore, unlink_local_state

DEFAULT_WORKTREE_BASE = Path("scripts/.worktrees/scrape")
"""Where worktrees go relative to the repository root, below `<subcommand>/<timestamp>/`."""

BRANCH_PREFIX = "scrape"
"""Branch namespace; the full branch is `scrape/<subcommand>/<timestamp>`."""


@dataclass(frozen=True)
class ScrapeWorktree:
    """One scrape's worktree, branched from `base_head` of the checkout at `root`."""

    root: Path
    path: Path
    branch: str
    base_head: str
    linked: tuple[UnignoreEntry, ...] = ()
    """Gitignored local state brought over from the root, removed again before the worktree is."""

# end class ScrapeWorktree


def worktree_stamp(now: datetime) -> str:
    """Format `now` as `YYYY-MM-DD_HH-MM-SS_+ZZZZ`, the folder and branch suffix; needs an aware datetime."""
    if now.tzinfo is None:
        raise ValueError("worktree_stamp needs a timezone-aware datetime")
    # end if
    return now.strftime("%Y-%m-%d_%H-%M-%S_%z")
# end def worktree_stamp


def worktree_branch(subcommand: str, stamp: str) -> str:
    """Return the branch name `scrape/<subcommand>/<stamp>`."""
    return f"{BRANCH_PREFIX}/{subcommand}/{stamp}"
# end def worktree_branch


def worktree_directory(root: Path, base: Path | None, subcommand: str, stamp: str) -> Path:
    """Return `<base>/<subcommand>/<stamp>`; `base` defaults to `DEFAULT_WORKTREE_BASE` and a relative `base` is taken from `root`."""
    chosen = base or DEFAULT_WORKTREE_BASE
    return (root / chosen / subcommand / stamp) if not chosen.is_absolute() else (chosen / subcommand / stamp)
# end def worktree_directory


def root_is_dirty(root: Path) -> bool:
    """Return whether the checkout has uncommitted or untracked changes.

    `ai/errors/` is excluded, matching `git_ops.autostash`: it is where a user may be `tee`-ing
    this very invocation's output, so a log file growing there must not count as pending work.
    """
    status = git_ops.run_git(root, "status", "--porcelain", "--", ".", ":!ai/errors").stdout
    return bool(status.strip())
# end def root_is_dirty


def create_scrape_worktree(
    root: Path, subcommand: str, now: datetime, base: Path | None = None, allow_dirty: bool = False
) -> ScrapeWorktree:
    """Create the worktree and its branch from the checkout's current `HEAD`.

    The worktree cannot see the checkout's uncommitted changes, and the final cherry-pick could
    collide with them, so a dirty checkout is refused unless `allow_dirty` is given (in which
    case `integrate_scrape_worktree` autostashes it around the cherry-pick).
    """
    if not allow_dirty and root_is_dirty(root):
        raise GitAutocommitError(
            f"{root} has uncommitted changes, which a scrape worktree cannot see. "
            "Commit or stash them, pass --git-worktree-allow-dirty to stash them around the final cherry-pick, "
            "or --no-git-worktree to scrape in place."
        )
    # end if
    # Validate `.worktree_unignore` first so a configuration problem aborts before anything is created.
    entries = load_unignore(root)
    stamp = worktree_stamp(now)
    branch = worktree_branch(subcommand, stamp)
    path = worktree_directory(root, base, subcommand, stamp)
    path.parent.mkdir(parents=True, exist_ok=True)
    base_head = git_ops.head(root)
    git_ops.run_git(root, "worktree", "add", "-q", "-b", branch, str(path), base_head)
    link_local_state(root, path, entries)
    return ScrapeWorktree(root=root, path=path, branch=branch, base_head=base_head, linked=tuple(entries))
# end def create_scrape_worktree


def commits_to_integrate(worktree: ScrapeWorktree) -> list[str]:
    """Return the commits the scrape made on its branch, oldest first."""
    output = git_ops.run_git(
        worktree.root, "rev-list", "--reverse", f"{worktree.base_head}..{worktree.branch}"
    ).stdout
    return output.split()
# end def commits_to_integrate


def remove_scrape_worktree(worktree: ScrapeWorktree) -> None:
    """Remove the worktree directory with plain `git worktree remove` (never `--force`).

    Git refuses while the worktree still has modified or untracked files. After a successful
    commit that means the scrape wrote something outside the committed paths, and force-removing
    it would silently lose that file, so the refusal is surfaced and the directory is kept.
    """
    unlink_local_state(worktree.path, list(worktree.linked))
    result = subprocess.run(
        ["git", "worktree", "remove", str(worktree.path)],
        cwd=worktree.root,
        text=True,
        capture_output=True,
    )
    if result.returncode == 0:
        return
    # end if
    status = subprocess.run(
        ["git", "status", "--short"], cwd=worktree.path, text=True, capture_output=True
    ).stdout.strip()
    raise GitAutocommitError(
        f"Could not remove the scrape worktree {worktree.path}: {result.stderr.strip()}\n"
        f"It still holds files the scrape did not commit:\n{status}\n"
        "Move what you need, then remove it manually."
    )
# end def remove_scrape_worktree


def is_interactive() -> bool:
    """Return whether both stdin and stdout are terminals, i.e. a human can answer a prompt."""
    return sys.stdin.isatty() and sys.stdout.isatty()
# end def is_interactive


def echo_stderr(message: str) -> None:
    """Default output channel for failure details."""
    print(message, file=sys.stderr)
# end def echo_stderr


DISCARD_PROMPT = "Cherry pick failed (details above). Already discard no longer needed worktree? [Y/n] "


def confirm_discard(interactive: bool, ask: Callable[[str], str] = input) -> bool:
    """Ask whether the leftover worktree directory may go; discarding is the default.

    Enter, `y` and `Y` discard, `n` and `N` keep, anything else repeats the question.
    Without a human to ask (or when stdin closes) the default applies and the worktree is discarded.
    """
    if not interactive:
        return True
    # end if
    while True:
        try:
            answer = ask(DISCARD_PROMPT).strip()
        except EOFError:
            return True
        # end try
        if answer in {"", "y", "Y"}:
            return True
        # end if
        if answer in {"n", "N"}:
            return False
        # end if
    # end while
# end def confirm_discard


def failure_details(worktree: ScrapeWorktree) -> str:
    """Describe what a failed cherry-pick leaves behind, to inform the keep-or-discard decision.

    The diff is the scrape branch against the root's current `HEAD`, summarised per directory
    rather than per file (so it stays short however many lists changed); the status is the
    worktree's own, which shows uncommitted leftovers.
    """
    shortstat = git_ops.run_git(worktree.root, "diff", "--shortstat", "HEAD", worktree.branch).stdout.strip()
    dirstat = git_ops.run_git(worktree.root, "diff", "--dirstat=files,0", "HEAD", worktree.branch).stdout.rstrip()
    status = git_ops.run_git(worktree.path, "status", "--short").stdout.rstrip()
    return (
        f"Diff of {worktree.branch} against the root HEAD:\n{shortstat or '(no difference)'}\n{dirstat}\n"
        f"Status of {worktree.path}:\n{status or '(clean)'}"
    )
# end def failure_details


def tag_branch_tip(worktree: ScrapeWorktree) -> str:
    """Tag the scrape branch's tip as `bak/<sha>` (like `scripts/tag_backup.py`) and return the tag name."""
    tip = git_ops.run_git(worktree.root, "rev-parse", worktree.branch).stdout.strip()
    tag = f"bak/{tip}"
    # Re-tagging an already tagged tip is fine, so only a failure other than "already exists" matters.
    result = subprocess.run(["git", "tag", tag, tip], cwd=worktree.root, text=True, capture_output=True)
    if result.returncode != 0 and "already exists" not in result.stderr:
        raise GitAutocommitError(f"Could not tag {tip} as {tag}: {result.stderr.strip()}")
    # end if
    return tag
# end def tag_branch_tip


def handle_failed_integration(
    worktree: ScrapeWorktree,
    interactive: bool,
    ask: Callable[[str], str] = input,
    echo: Callable[[str], None] = echo_stderr,
) -> None:
    """Preserve a scrape whose cherry-pick failed, and discard the worktree directory unless the user keeps it.

    The commits always survive: the branch stays and its tip is tagged `bak/<sha>`.
    Only the directory, which is the annoying part to clean up by hand, is up for discarding.
    """
    tag = tag_branch_tip(worktree)
    echo(failure_details(worktree))
    echo(f"The scrape's commits are kept on branch {worktree.branch}, tagged {tag}.")
    if not confirm_discard(interactive, ask):
        echo(f"Kept worktree {worktree.path}.")
        return
    # end if
    try:
        remove_scrape_worktree(worktree)
    except GitAutocommitError as error:
        echo(str(error))
    # end try
# end def handle_failed_integration


def cherry_pick_commits(
    worktree: ScrapeWorktree,
    commits: list[str],
    allow_dirty: bool,
    interactive: bool,
    ask: Callable[[str], str],
    echo: Callable[[str], None],
) -> None:
    """Cherry-pick `commits` into the root, stashing the root's pending changes around it when `allow_dirty`.

    The stash is restored whether or not the pick succeeds, so the user's pending changes always
    come back; `restore_autostash` reverts a path to its pre-pick content only when the pick
    itself changed it, which keeps the changes the scrape's commits made.
    """
    pre_pick_head = git_ops.head(worktree.root)
    stashed = git_ops.autostash(worktree.root) if allow_dirty else False
    try:
        pick = subprocess.run(
            ["git", "cherry-pick", *commits], cwd=worktree.root, text=True, capture_output=True
        )
        if pick.returncode == 0:
            return
        # end if
        subprocess.run(["git", "cherry-pick", "--abort"], cwd=worktree.root, capture_output=True)
        handle_failed_integration(worktree, interactive, ask, echo)
        raise GitAutocommitError(
            f"Cherry-picking {worktree.branch} into {worktree.root} failed: {pick.stderr.strip()}\n"
            f"Retry by hand with `git cherry-pick {worktree.base_head}..{worktree.branch}`."
        )
    finally:
        if stashed:
            git_ops.restore_autostash(worktree.root, pre_pick_head)
        # end if
    # end try
# end def cherry_pick_commits


def integrate_scrape_worktree(
    worktree: ScrapeWorktree,
    allow_dirty: bool = False,
    interactive: bool = False,
    ask: Callable[[str], str] = input,
    echo: Callable[[str], None] = echo_stderr,
) -> None:
    """Cherry-pick the scrape's commits into the root checkout, then remove worktree and branch."""
    commits = commits_to_integrate(worktree)
    if commits:
        cherry_pick_commits(worktree, commits, allow_dirty, interactive, ask, echo)
    # end if
    remove_scrape_worktree(worktree)
    # `-D`, not `-d`: the cherry-picked commits are copies, so git does not consider the branch merged.
    git_ops.run_git(worktree.root, "branch", "-D", worktree.branch)
# end def integrate_scrape_worktree
