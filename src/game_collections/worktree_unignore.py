"""`.worktree_unignore`: gitignored local state a scrape worktree still needs.

A fresh worktree only holds tracked files, so anything the scrape reads that is gitignored
(for example a local `.env`) has to be brought over explicitly. The tracked `.worktree_unignore`
file at the repository root lists those paths, one per line, `#` starts a comment, and an optional
second word picks how the path is brought over: `symlink` (the default), `hardlink` or `copy`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath

from game_collections.git_ops import GitAutocommitError

UNIGNORE_FILE_NAME = ".worktree_unignore"


class UnignoreMode(StrEnum):
    SYMLINK = "symlink"
    HARDLINK = "hardlink"
    COPY = "copy"

# end class UnignoreMode


@dataclass(frozen=True)
class UnignoreEntry:
    """One gitignored path, relative to the repository root, and how to bring it over."""

    path: Path
    mode: UnignoreMode

# end class UnignoreEntry


class WorktreeConfigError(GitAutocommitError):
    """`.worktree_unignore` is malformed or names something it must not; the run is aborted."""

# end class WorktreeConfigError


def parse_unignore(text: str) -> list[UnignoreEntry]:
    """Parse the file's text, checking everything that does not need the filesystem."""
    entries: list[UnignoreEntry] = []
    seen: set[Path] = set()
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        # end if
        words = line.rsplit(maxsplit=1)
        mode = UnignoreMode.SYMLINK
        path_text = line
        # The mode is the last word; paths with spaces stay possible as long as they do not end in a mode name.
        if len(words) == 2 and words[1] in {member.value for member in UnignoreMode}:
            path_text, mode = words[0].strip(), UnignoreMode(words[1])
        # end if
        posix = PurePosixPath(path_text)
        if posix.is_absolute() or ".." in posix.parts:
            raise WorktreeConfigError(
                f"{UNIGNORE_FILE_NAME}:{number}: {path_text!r} must be relative and stay inside the repository"
            )
        # end if
        path = Path(*posix.parts)
        if path in seen:
            raise WorktreeConfigError(f"{UNIGNORE_FILE_NAME}:{number}: {path_text!r} is listed twice")
        # end if
        seen.add(path)
        entries.append(UnignoreEntry(path=path, mode=mode))
    # end for
    return entries
# end def parse_unignore


def load_unignore(root: Path) -> list[UnignoreEntry]:
    """Read and validate `<root>/.worktree_unignore`; a missing file means no entries.

    Every entry must exist and be gitignored. Anything else is a configuration problem that
    aborts the run, rather than a scrape quietly running without the state it needs.
    """
    file = root / UNIGNORE_FILE_NAME
    if not file.exists():
        return []
    # end if
    entries = parse_unignore(file.read_text(encoding="utf-8"))
    for entry in entries:
        source = root / entry.path
        if not source.exists() and not source.is_symlink():
            raise WorktreeConfigError(f"{UNIGNORE_FILE_NAME}: {entry.path} does not exist in {root}")
        # end if
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", "--", str(entry.path)], cwd=root, capture_output=True
        )
        if ignored.returncode != 0:
            raise WorktreeConfigError(f"{UNIGNORE_FILE_NAME}: {entry.path} is not gitignored (tracked files need no entry)")
        # end if
        if entry.mode is UnignoreMode.HARDLINK and source.is_dir():
            raise WorktreeConfigError(f"{UNIGNORE_FILE_NAME}: {entry.path} is a directory, which cannot be hardlinked")
        # end if
    # end for
    return entries
# end def load_unignore


def link_local_state(root: Path, worktree_path: Path, entries: list[UnignoreEntry]) -> None:
    """Bring every entry over into the fresh worktree."""
    for entry in entries:
        source = root / entry.path
        target = worktree_path / entry.path
        target.parent.mkdir(parents=True, exist_ok=True)
        if entry.mode is UnignoreMode.SYMLINK:
            target.symlink_to(source.resolve(), target_is_directory=source.is_dir())
            continue
        # end if
        if entry.mode is UnignoreMode.HARDLINK:
            os.link(source, target)
            continue
        # end if
        if source.is_dir():
            shutil.copytree(source, target, symlinks=True)
            continue
        # end if
        shutil.copy2(source, target)
    # end for
# end def link_local_state


def unlink_local_state(worktree_path: Path, entries: list[UnignoreEntry]) -> None:
    """Remove what `link_local_state` brought over, so `git worktree remove` needs no `--force`.

    Links are unlinked and never followed, so the root's real files are untouched; only
    a genuine copied directory is deleted recursively.
    """
    for entry in entries:
        target = worktree_path / entry.path
        if target.is_symlink() or target.is_file():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
        # end if
        # Drop the parent directories link_local_state may have had to create, as far as they are empty.
        for parent in target.parents:
            if parent == worktree_path or not parent.is_relative_to(worktree_path):
                break
            # end if
            try:
                parent.rmdir()
            except OSError:
                break
            # end try
        # end for
    # end for
# end def unlink_local_state
