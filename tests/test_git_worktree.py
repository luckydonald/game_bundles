from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from game_collections import git_ops, git_worktree
from game_collections.git_ops import GitAutocommitError

NOW = datetime(2026, 11, 12, 9, 30, 5, tzinfo=timezone(timedelta(hours=1)))


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, text=True, capture_output=True).stdout


def init_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.com")
    (root / "lists").mkdir()
    (root / "lists" / "keep.txt").write_text("initial\n", encoding="utf-8")
    (root / ".gitignore").write_text("scripts/.worktrees/\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "initial commit")
    return root
# end def init_repo


def test_worktree_stamp_formats_date_time_and_offset() -> None:
    assert git_worktree.worktree_stamp(NOW) == "2026-11-12_09-30-05_+0100"
# end def test_worktree_stamp_formats_date_time_and_offset


def test_worktree_stamp_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError):
        git_worktree.worktree_stamp(datetime(2026, 11, 12, 9, 30, 5))
    # end with
# end def test_worktree_stamp_rejects_naive_datetime


def test_worktree_directory_defaults_below_the_root_and_honours_a_custom_base(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    default = git_worktree.worktree_directory(root, None, "all", "stamp")
    assert default == root / "scripts/.worktrees/scrape/all/stamp"
    relative = git_worktree.worktree_directory(root, Path("elsewhere"), "all", "stamp")
    assert relative == root / "elsewhere/all/stamp"
    absolute = git_worktree.worktree_directory(root, tmp_path / "abs", "all", "stamp")
    assert absolute == tmp_path / "abs/all/stamp"
# end def test_worktree_directory_defaults_below_the_root_and_honours_a_custom_base


def test_create_makes_branch_and_directory_from_head(tmp_path: Path) -> None:
    root = init_repo(tmp_path)

    worktree = git_worktree.create_scrape_worktree(root, "humblebundle", NOW)

    assert worktree.path == root / "scripts/.worktrees/scrape/humblebundle/2026-11-12_09-30-05_+0100"
    assert worktree.branch == "scrape/humblebundle/2026-11-12_09-30-05_+0100"
    assert worktree.base_head == git_ops.head(root)
    assert (worktree.path / "lists" / "keep.txt").read_text(encoding="utf-8") == "initial\n"
    assert git(worktree.path, "rev-parse", "--abbrev-ref", "HEAD").strip() == worktree.branch
# end def test_create_makes_branch_and_directory_from_head


def test_integrate_cherry_picks_commits_and_removes_worktree_and_branch(tmp_path: Path) -> None:
    root = init_repo(tmp_path)
    worktree = git_worktree.create_scrape_worktree(root, "all", NOW)
    (worktree.path / "lists" / "first.txt").write_text("1\n", encoding="utf-8")
    git_ops.commit_changed_paths(worktree.path, ["lists"], "first scrape")
    (worktree.path / "lists" / "second.txt").write_text("2\n", encoding="utf-8")
    git_ops.commit_changed_paths(worktree.path, ["lists"], "second scrape")

    git_worktree.integrate_scrape_worktree(worktree)

    assert git(root, "log", "--format=%s", "-2").splitlines() == ["second scrape", "first scrape"]
    assert (root / "lists" / "second.txt").read_text(encoding="utf-8") == "2\n"
    assert not worktree.path.exists()
    assert git(root, "branch", "--list", worktree.branch).strip() == ""
    assert git(root, "status", "--porcelain").strip() == ""
# end def test_integrate_cherry_picks_commits_and_removes_worktree_and_branch


def test_integrate_without_commits_just_cleans_up(tmp_path: Path) -> None:
    root = init_repo(tmp_path)
    before = git_ops.head(root)
    worktree = git_worktree.create_scrape_worktree(root, "all", NOW)

    git_worktree.integrate_scrape_worktree(worktree)

    assert git_ops.head(root) == before
    assert not worktree.path.exists()
    assert git(root, "branch", "--list", worktree.branch).strip() == ""
# end def test_integrate_without_commits_just_cleans_up


def test_integrate_refuses_to_remove_a_worktree_with_stray_files(tmp_path: Path) -> None:
    root = init_repo(tmp_path)
    worktree = git_worktree.create_scrape_worktree(root, "all", NOW)
    (worktree.path / "lists" / "committed.txt").write_text("c\n", encoding="utf-8")
    git_ops.commit_changed_paths(worktree.path, ["lists"], "scrape output")
    (worktree.path / "stray.txt").write_text("not committed\n", encoding="utf-8")

    with pytest.raises(GitAutocommitError, match="stray"):
        git_worktree.integrate_scrape_worktree(worktree)
    # end with

    assert (worktree.path / "stray.txt").exists()
    assert (root / "lists" / "committed.txt").exists()
# end def test_integrate_refuses_to_remove_a_worktree_with_stray_files


def test_integrate_aborts_the_pick_and_keeps_the_branch_on_conflict(tmp_path: Path) -> None:
    root = init_repo(tmp_path)
    worktree = git_worktree.create_scrape_worktree(root, "all", NOW)
    (worktree.path / "lists" / "keep.txt").write_text("from scrape\n", encoding="utf-8")
    git_ops.commit_changed_paths(worktree.path, ["lists"], "scrape output")
    (root / "lists" / "keep.txt").write_text("from root\n", encoding="utf-8")
    git(root, "commit", "-q", "-am", "conflicting root change")

    with pytest.raises(GitAutocommitError, match="Cherry-picking"):
        git_worktree.integrate_scrape_worktree(worktree)
    # end with

    assert (root / "lists" / "keep.txt").read_text(encoding="utf-8") == "from root\n"
    assert git(root, "status", "--porcelain").strip() == ""
    assert git(root, "branch", "--list", worktree.branch).strip() != ""
# end def test_integrate_aborts_the_pick_and_keeps_the_branch_on_conflict
