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


def conflicting_worktree(tmp_path: Path) -> tuple[Path, git_worktree.ScrapeWorktree]:
    root = init_repo(tmp_path)
    worktree = git_worktree.create_scrape_worktree(root, "all", NOW)
    (worktree.path / "lists" / "keep.txt").write_text("from scrape\n", encoding="utf-8")
    git_ops.commit_changed_paths(worktree.path, ["lists"], "scrape output")
    (root / "lists" / "keep.txt").write_text("from root\n", encoding="utf-8")
    git(root, "commit", "-q", "-am", "conflicting root change")
    return root, worktree
# end def conflicting_worktree


def assert_commits_preserved(root: Path, worktree: git_worktree.ScrapeWorktree) -> None:
    assert (root / "lists" / "keep.txt").read_text(encoding="utf-8") == "from root\n"
    assert git(root, "status", "--porcelain").strip() == ""
    assert git(root, "branch", "--list", worktree.branch).strip() != ""
    tip = git(root, "rev-parse", worktree.branch).strip()
    assert git(root, "tag", "--list", f"bak/{tip}").strip() == f"bak/{tip}"
# end def assert_commits_preserved


def test_conflict_non_interactive_discards_the_directory_but_keeps_branch_and_tag(tmp_path: Path) -> None:
    root, worktree = conflicting_worktree(tmp_path)
    messages: list[str] = []

    with pytest.raises(GitAutocommitError, match="Cherry-picking"):
        git_worktree.integrate_scrape_worktree(worktree, interactive=False, echo=messages.append)
    # end with

    assert_commits_preserved(root, worktree)
    assert not worktree.path.exists()
    printed = "\n".join(messages)
    assert "lists" in printed and "1 file changed" in printed
    assert f"Status of {worktree.path}" in printed
# end def test_conflict_non_interactive_discards_the_directory_but_keeps_branch_and_tag


@pytest.mark.parametrize("answers", [["y"], ["Y"], [""], ["maybe", "", ]])
def test_conflict_interactive_discards_on_yes_enter_and_after_invalid_answers(
    tmp_path: Path, answers: list[str]
) -> None:
    root, worktree = conflicting_worktree(tmp_path)
    queue = list(answers)

    with pytest.raises(GitAutocommitError):
        git_worktree.integrate_scrape_worktree(
            worktree, interactive=True, ask=lambda _prompt: queue.pop(0), echo=lambda _message: None
        )
    # end with

    assert queue == []
    assert_commits_preserved(root, worktree)
    assert not worktree.path.exists()
# end def test_conflict_interactive_discards_on_yes_enter_and_after_invalid_answers


@pytest.mark.parametrize("answer", ["n", "N"])
def test_conflict_interactive_keeps_the_directory_on_no(tmp_path: Path, answer: str) -> None:
    root, worktree = conflicting_worktree(tmp_path)

    with pytest.raises(GitAutocommitError):
        git_worktree.integrate_scrape_worktree(
            worktree, interactive=True, ask=lambda _prompt: answer, echo=lambda _message: None
        )
    # end with

    assert_commits_preserved(root, worktree)
    assert worktree.path.exists()
# end def test_conflict_interactive_keeps_the_directory_on_no


def test_confirm_discard_repeats_until_a_valid_answer_and_defaults_on_eof() -> None:
    prompts: list[str] = []
    answers = iter(["what", "??", "N"])

    def ask(prompt: str) -> str:
        prompts.append(prompt)
        return next(answers)
    # end def ask

    assert git_worktree.confirm_discard(True, ask) is False
    assert prompts == [git_worktree.DISCARD_PROMPT] * 3

    def closed(_prompt: str) -> str:
        raise EOFError
    # end def closed

    assert git_worktree.confirm_discard(True, closed) is True
    assert git_worktree.confirm_discard(False, closed) is True
# end def test_confirm_discard_repeats_until_a_valid_answer_and_defaults_on_eof
