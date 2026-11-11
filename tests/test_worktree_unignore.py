from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from game_collections import git_worktree
from game_collections.worktree_unignore import (
    UnignoreEntry,
    UnignoreMode,
    WorktreeConfigError,
    link_local_state,
    load_unignore,
    parse_unignore,
    unlink_local_state,
)

NOW = datetime(2026, 11, 12, 9, 30, 5, tzinfo=timezone(timedelta(hours=1)))


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, text=True, capture_output=True).stdout


def init_repo(tmp_path: Path, unignore: str) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.com")
    (root / ".gitignore").write_text(".env\nlocal/\nscripts/.worktrees/\n", encoding="utf-8")
    (root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    (root / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (root / "local").mkdir()
    (root / "local" / "profile.txt").write_text("profile\n", encoding="utf-8")
    (root / ".worktree_unignore").write_text(unignore, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "initial commit")
    return root
# end def init_repo


def test_parse_reads_paths_modes_and_skips_comments() -> None:
    entries = parse_unignore("# header\n.env\nlocal/profile hardlink  # why\n\ncache copy\n")
    assert entries == [
        UnignoreEntry(Path(".env"), UnignoreMode.SYMLINK),
        UnignoreEntry(Path("local/profile"), UnignoreMode.HARDLINK),
        UnignoreEntry(Path("cache"), UnignoreMode.COPY),
    ]
# end def test_parse_reads_paths_modes_and_skips_comments


@pytest.mark.parametrize("text", ["/etc/passwd\n", "../outside\n", "a/../../b\n", ".env\n.env symlink\n"])
def test_parse_rejects_absolute_escaping_and_duplicate_entries(text: str) -> None:
    with pytest.raises(WorktreeConfigError):
        parse_unignore(text)
    # end with
# end def test_parse_rejects_absolute_escaping_and_duplicate_entries


def test_load_without_a_file_means_no_entries(tmp_path: Path) -> None:
    root = init_repo(tmp_path, "")
    (root / ".worktree_unignore").unlink()
    assert load_unignore(root) == []
# end def test_load_without_a_file_means_no_entries


def test_load_rejects_missing_tracked_and_directory_hardlink_entries(tmp_path: Path) -> None:
    root = init_repo(tmp_path, "")
    for text, message in [
        ("nothing-here\n", "does not exist"),
        ("tracked.txt\n", "not gitignored"),
        ("local hardlink\n", "cannot be hardlinked"),
    ]:
        (root / ".worktree_unignore").write_text(text, encoding="utf-8")
        with pytest.raises(WorktreeConfigError, match=message):
            load_unignore(root)
        # end with
    # end for
# end def test_load_rejects_missing_tracked_and_directory_hardlink_entries


def test_invalid_config_aborts_before_a_worktree_is_created(tmp_path: Path) -> None:
    root = init_repo(tmp_path, "nothing-here\n")

    with pytest.raises(WorktreeConfigError):
        git_worktree.create_scrape_worktree(root, "all", NOW)
    # end with

    assert not (root / "scripts" / ".worktrees").exists()
    assert "scrape/" not in git(root, "branch", "--list")
# end def test_invalid_config_aborts_before_a_worktree_is_created


def test_link_modes_bring_state_over_and_unlink_leaves_the_root_intact(tmp_path: Path) -> None:
    root = init_repo(tmp_path, ".env\nlocal copy\n")
    worktree = git_worktree.create_scrape_worktree(root, "all", NOW)

    assert (worktree.path / ".env").is_symlink()
    assert (worktree.path / ".env").read_text(encoding="utf-8") == "SECRET=1\n"
    assert not (worktree.path / "local").is_symlink()
    assert (worktree.path / "local" / "profile.txt").read_text(encoding="utf-8") == "profile\n"

    unlink_local_state(worktree.path, list(worktree.linked))

    assert not (worktree.path / ".env").exists()
    assert not (worktree.path / "local").exists()
    assert (root / ".env").read_text(encoding="utf-8") == "SECRET=1\n"
    assert (root / "local" / "profile.txt").exists()
# end def test_link_modes_bring_state_over_and_unlink_leaves_the_root_intact


def test_hardlink_shares_the_inode_and_directory_symlinks_are_not_followed(tmp_path: Path) -> None:
    root = init_repo(tmp_path, ".env hardlink\nlocal symlink\n")
    worktree = git_worktree.create_scrape_worktree(root, "all", NOW)

    assert os.stat(worktree.path / ".env").st_ino == os.stat(root / ".env").st_ino
    assert (worktree.path / "local").is_symlink()

    unlink_local_state(worktree.path, list(worktree.linked))

    assert (root / "local" / "profile.txt").exists()
    assert (root / ".env").exists()
# end def test_hardlink_shares_the_inode_and_directory_symlinks_are_not_followed


def test_integrate_unlinks_state_so_plain_worktree_remove_succeeds(tmp_path: Path) -> None:
    root = init_repo(tmp_path, ".env\nlocal copy\n")
    worktree = git_worktree.create_scrape_worktree(root, "all", NOW)

    git_worktree.integrate_scrape_worktree(worktree)

    assert not worktree.path.exists()
    assert (root / ".env").exists()
    assert (root / "local" / "profile.txt").exists()
# end def test_integrate_unlinks_state_so_plain_worktree_remove_succeeds


def test_link_creates_missing_parent_directories_and_unlink_drops_them(tmp_path: Path) -> None:
    root = tmp_path / "root"
    nested = root / "deep" / "dir"
    nested.mkdir(parents=True)
    (nested / "state.txt").write_text("s\n", encoding="utf-8")
    worktree_path = tmp_path / "wt"
    worktree_path.mkdir()
    entries = [UnignoreEntry(Path("deep/dir/state.txt"), UnignoreMode.COPY)]

    link_local_state(root, worktree_path, entries)
    assert (worktree_path / "deep" / "dir" / "state.txt").exists()

    unlink_local_state(worktree_path, entries)
    assert list(worktree_path.iterdir()) == []
# end def test_link_creates_missing_parent_directories_and_unlink_drops_them
