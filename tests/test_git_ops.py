from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from game_collections import git_ops


def _git(repository_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repository_root, check=True, text=True, capture_output=True
    )
# end def _git


def _init_repo(tmp_path: Path) -> Path:
    repository_root = tmp_path / "repo"
    repository_root.mkdir()
    _git(repository_root, "init", "-q")
    _git(repository_root, "config", "user.name", "Test")
    _git(repository_root, "config", "user.email", "test@example.com")
    (repository_root / "lists").mkdir()
    (repository_root / "lists" / "keep.txt").write_text("initial\n", encoding="utf-8")
    (repository_root / "unrelated.txt").write_text("initial\n", encoding="utf-8")
    _git(repository_root, "add", "-A")
    _git(repository_root, "commit", "-q", "-m", "initial commit")
    return repository_root
# end def _init_repo


def test_head_returns_current_commit(tmp_path: Path) -> None:
    repository_root = _init_repo(tmp_path)
    assert git_ops.head(repository_root) == _git(repository_root, "rev-parse", "HEAD").stdout.strip()
# end def test_head_returns_current_commit


def test_autostash_returns_false_when_tree_is_clean(tmp_path: Path) -> None:
    repository_root = _init_repo(tmp_path)
    assert git_ops.autostash(repository_root) is False
# end def test_autostash_returns_false_when_tree_is_clean


def test_autostash_stashes_tracked_and_untracked_changes(tmp_path: Path) -> None:
    repository_root = _init_repo(tmp_path)
    (repository_root / "unrelated.txt").write_text("edited\n", encoding="utf-8")
    (repository_root / "new-untracked.txt").write_text("new\n", encoding="utf-8")

    assert git_ops.autostash(repository_root) is True
    assert (repository_root / "unrelated.txt").read_text(encoding="utf-8") == "initial\n"
    assert not (repository_root / "new-untracked.txt").exists()
# end def test_autostash_stashes_tracked_and_untracked_changes


def test_commit_changed_paths_returns_false_when_nothing_changed(tmp_path: Path) -> None:
    repository_root = _init_repo(tmp_path)
    assert git_ops.commit_changed_paths(repository_root, ["lists"], "message") is False
# end def test_commit_changed_paths_returns_false_when_nothing_changed


def test_commit_changed_paths_commits_only_the_given_paths(tmp_path: Path) -> None:
    repository_root = _init_repo(tmp_path)
    before_head = git_ops.head(repository_root)
    (repository_root / "lists" / "keep.txt").write_text("scraped\n", encoding="utf-8")
    (repository_root / "unrelated.txt").write_text("also changed\n", encoding="utf-8")

    committed = git_ops.commit_changed_paths(repository_root, ["lists"], "scrape output")

    assert committed is True
    assert git_ops.head(repository_root) != before_head
    status = _git(repository_root, "status", "--porcelain").stdout
    assert "unrelated.txt" in status
    assert "lists/keep.txt" not in status
# end def test_commit_changed_paths_commits_only_the_given_paths


def test_restore_autostash_pops_cleanly_when_no_conflict(tmp_path: Path) -> None:
    repository_root = _init_repo(tmp_path)
    pre_crawl_head = git_ops.head(repository_root)
    (repository_root / "unrelated.txt").write_text("local edit\n", encoding="utf-8")
    assert git_ops.autostash(repository_root) is True

    (repository_root / "lists" / "keep.txt").write_text("scraped\n", encoding="utf-8")
    git_ops.commit_changed_paths(repository_root, ["lists"], "scrape output")

    git_ops.restore_autostash(repository_root, pre_crawl_head)

    assert (repository_root / "unrelated.txt").read_text(encoding="utf-8") == "local edit\n"
    assert _git(repository_root, "stash", "list").stdout.strip() == ""
# end def test_restore_autostash_pops_cleanly_when_no_conflict


def test_restore_autostash_falls_back_to_pre_crawl_content_on_conflict(tmp_path: Path) -> None:
    repository_root = _init_repo(tmp_path)
    pre_crawl_head = git_ops.head(repository_root)
    # A local edit to the same file the "scrape" below will also touch.
    (repository_root / "lists" / "keep.txt").write_text("local edit\n", encoding="utf-8")
    assert git_ops.autostash(repository_root) is True

    (repository_root / "lists" / "keep.txt").write_text("scraped\n", encoding="utf-8")
    git_ops.commit_changed_paths(repository_root, ["lists"], "scrape output")

    git_ops.restore_autostash(repository_root, pre_crawl_head)

    # The user's pre-existing local edit must survive; the scrape's own commit
    # is still safe in history even though the working tree lost it here.
    assert (repository_root / "lists" / "keep.txt").read_text(encoding="utf-8") == "local edit\n"
    assert _git(repository_root, "stash", "list").stdout.strip() == ""
# end def test_restore_autostash_falls_back_to_pre_crawl_content_on_conflict


def test_restore_autostash_raises_when_nothing_was_stashed(tmp_path: Path) -> None:
    repository_root = _init_repo(tmp_path)
    pre_crawl_head = git_ops.head(repository_root)

    with pytest.raises(git_ops.GitAutocommitError):
        git_ops.restore_autostash(repository_root, pre_crawl_head)
    # end with
# end def test_restore_autostash_raises_when_nothing_was_stashed
