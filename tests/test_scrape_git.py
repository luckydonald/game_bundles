from __future__ import annotations

from pathlib import Path

import pytest
from pytest import MonkeyPatch
from typer.testing import CliRunner

from game_collections.cli import app
from test_scrape_worktree import git, install_fake_humble_crawl, repo  # noqa: F401  (repo is a fixture)

MODES = pytest.mark.parametrize("mode", [["--no-git-worktree"], []], ids=["in-place", "worktree"])


def make_dirty(root: Path, mode: list[str]) -> list[str]:
    """Leave pending work in the checkout; only the in-place mode may start from a dirty one."""
    if mode == []:
        return mode
    # end if
    (root / "lists" / "keep.txt").parent.mkdir(exist_ok=True)
    (root / "pending.txt").write_text("pending\n", encoding="utf-8")
    (root / "lists" / ".gitkeep").write_text("edited\n", encoding="utf-8")
    return mode
# end def make_dirty


def assert_untouched(root: Path, dirty: bool) -> None:
    assert git(root, "stash", "list").strip() == ""
    # Empty `<subcommand>/` folders may remain; what matters is that no worktree directory does.
    assert list((root / "scripts" / ".worktrees" / "scrape").glob("*/*")) == []
    assert "scripts/.worktrees" not in git(root, "worktree", "list")
    assert Path.cwd() == root
    assert git(root, "branch", "--list", "scrape/*").strip() == ""
    if dirty:
        assert (root / "pending.txt").read_text(encoding="utf-8") == "pending\n"
        assert (root / "lists" / ".gitkeep").read_text(encoding="utf-8") == "edited\n"
    # end if
# end def assert_untouched


@MODES
def test_subcommand_help_has_no_side_effects_even_on_a_dirty_checkout(repo: Path, mode: list[str]) -> None:  # noqa: F811
    dirty = bool(make_dirty(repo, mode)) or mode != []

    result = CliRunner().invoke(app, ["scrape", *mode, "humblebundle", "--help"])

    assert result.exit_code == 0, result.output
    assert "Usage" in result.output
    assert_untouched(repo, dirty)
# end def test_subcommand_help_has_no_side_effects_even_on_a_dirty_checkout


@MODES
def test_unknown_subcommand_option_leaves_the_checkout_untouched(repo: Path, mode: list[str]) -> None:  # noqa: F811
    """The incident: `--git` written after the subcommand is rejected by Click after the group callback ran."""
    dirty = bool(make_dirty(repo, mode)) or mode != []

    result = CliRunner().invoke(app, ["scrape", *mode, "humblebundle", "--non-interactive", "--git", "--help"])

    assert result.exit_code == 2, result.output
    assert "No such option" in result.output
    assert_untouched(repo, dirty)
# end def test_unknown_subcommand_option_leaves_the_checkout_untouched


def test_failure_before_the_try_block_still_restores_the_stash(repo: Path, monkeypatch: MonkeyPatch) -> None:  # noqa: F811
    install_fake_humble_crawl(monkeypatch, [])

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("archive migration failed")
    # end def boom

    monkeypatch.setattr("game_collections.cli._migrate_source_archives", boom)
    (repo / "pending.txt").write_text("pending\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["scrape", "--no-git-worktree", "humblebundle", "--non-interactive"])

    assert result.exit_code != 0
    assert isinstance(result.exception, RuntimeError)
    assert (repo / "pending.txt").read_text(encoding="utf-8") == "pending\n"
    assert git(repo, "stash", "list").strip() == ""
# end def test_failure_before_the_try_block_still_restores_the_stash


def test_failure_before_the_try_block_still_removes_the_worktree(repo: Path, monkeypatch: MonkeyPatch) -> None:  # noqa: F811
    install_fake_humble_crawl(monkeypatch, [])

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("archive migration failed")
    # end def boom

    monkeypatch.setattr("game_collections.cli._migrate_source_archives", boom)

    result = CliRunner().invoke(app, ["scrape", "humblebundle", "--non-interactive"])

    assert result.exit_code != 0
    assert_untouched(repo, dirty=False)
# end def test_failure_before_the_try_block_still_removes_the_worktree


def test_in_place_run_restores_the_stash_exactly_once(repo: Path, monkeypatch: MonkeyPatch) -> None:  # noqa: F811
    install_fake_humble_crawl(monkeypatch, [])
    (repo / "pending.txt").write_text("pending\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["scrape", "--no-git-worktree", "humblebundle", "--non-interactive"])

    assert result.exit_code == 0, result.output
    assert (repo / "pending.txt").read_text(encoding="utf-8") == "pending\n"
    assert (repo / "lists" / "scraped.txt").exists()
    assert git(repo, "stash", "list").strip() == ""
    assert "error:" not in result.output.lower()
# end def test_in_place_run_restores_the_stash_exactly_once
