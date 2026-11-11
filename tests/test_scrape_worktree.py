from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from pytest import MonkeyPatch
from typer.testing import CliRunner

from game_collections import git_ops, git_worktree, scrape_git
from game_collections.cli import app


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, text=True, capture_output=True).stdout


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """A temporary checkout shaped like the real paths `scrape humblebundle` commits, with cwd inside it."""
    root = (tmp_path / "repo").resolve()
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.com")
    for directory in ("lists", "archives", "config"):
        (root / directory).mkdir()
        (root / directory / ".gitkeep").write_text("", encoding="utf-8")
    (root / "config" / "humblebundle-store-ids.yml").write_text("{}\n", encoding="utf-8")
    (root / ".gitignore").write_text("scripts/.worktrees/\n.env\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "initial commit")
    monkeypatch.chdir(root)
    return root
# end def repo


def install_fake_humble_crawl(monkeypatch: MonkeyPatch, seen_cwd: list[Path]) -> None:
    """Fake only the network side of `scrape humblebundle`; git runs for real. The fake crawl writes a list into the cwd."""
    from game_collections.sources.humblebundle.crawler import HumbleCrawlReport
    from game_collections.sources.humblebundle.resolver import HumbleResolutionMap

    def crawl(*args: object, **kwargs: object) -> HumbleCrawlReport:
        seen_cwd.append(Path.cwd())
        (Path.cwd() / "lists" / "scraped.txt").write_text("scraped\n", encoding="utf-8")
        return HumbleCrawlReport(offers=(), errors=())
    # end def crawl

    monkeypatch.setattr(
        "game_collections.cli.HumbleHttpClient", lambda: SimpleNamespace(close=lambda: None, fetch=lambda url: "")
    )
    monkeypatch.setattr(
        "game_collections.cli.load_resolution_map", lambda path: HumbleResolutionMap(schema=1, games={})
    )
    monkeypatch.setattr("game_collections.cli.StorefrontResolver", lambda fetch, choose, **_kwargs: object())
    monkeypatch.setattr("game_collections.cli._migrate_source_archives", lambda *args, **kwargs: None)
    monkeypatch.setattr("game_collections.cli.crawl_humble_offers", crawl)
# end def install_fake_humble_crawl


def test_scrape_runs_in_a_worktree_and_cherry_picks_the_commit_back(repo: Path, monkeypatch: MonkeyPatch) -> None:
    seen_cwd: list[Path] = []
    install_fake_humble_crawl(monkeypatch, seen_cwd)

    result = CliRunner().invoke(app, ["scrape", "humblebundle", "--non-interactive"])

    assert result.exit_code == 0, result.output
    assert len(seen_cwd) == 1
    assert seen_cwd[0].parent.parent == repo / "scripts/.worktrees/scrape"
    assert seen_cwd[0].parent.name == "humblebundle"
    assert Path.cwd() == repo
    assert (repo / "lists" / "scraped.txt").read_text(encoding="utf-8") == "scraped\n"
    assert "[crawl|humblebundle] manual scrape" in git(repo, "log", "-1", "--format=%s")
    assert not seen_cwd[0].exists()
    assert git(repo, "branch", "--list", "scrape/*").strip() == ""
    assert git(repo, "status", "--porcelain").strip() == ""
# end def test_scrape_runs_in_a_worktree_and_cherry_picks_the_commit_back


def test_custom_worktree_base_is_used(repo: Path, monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    seen_cwd: list[Path] = []
    install_fake_humble_crawl(monkeypatch, seen_cwd)
    base = (tmp_path / "elsewhere").resolve()

    result = CliRunner().invoke(app, ["scrape", "--git-worktree", str(base), "humblebundle", "--non-interactive"])

    assert result.exit_code == 0, result.output
    assert seen_cwd[0].parent.parent == base
# end def test_custom_worktree_base_is_used


def test_empty_git_worktree_value_keeps_the_default_location(repo: Path, monkeypatch: MonkeyPatch) -> None:
    seen_cwd: list[Path] = []
    install_fake_humble_crawl(monkeypatch, seen_cwd)

    result = CliRunner().invoke(app, ["scrape", "--git-worktree", "", "humblebundle", "--non-interactive"])

    assert result.exit_code == 0, result.output
    assert seen_cwd[0].parent.parent == repo / "scripts/.worktrees/scrape"
# end def test_empty_git_worktree_value_keeps_the_default_location


def test_dirty_checkout_is_refused_with_a_hint(repo: Path, monkeypatch: MonkeyPatch) -> None:
    seen_cwd: list[Path] = []
    install_fake_humble_crawl(monkeypatch, seen_cwd)
    (repo / "pending.txt").write_text("pending\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["scrape", "humblebundle", "--non-interactive"])

    assert result.exit_code == 1
    assert "--git-worktree-allow-dirty" in result.output
    assert seen_cwd == []
# end def test_dirty_checkout_is_refused_with_a_hint


def test_allow_dirty_scrapes_and_keeps_the_pending_changes(repo: Path, monkeypatch: MonkeyPatch) -> None:
    seen_cwd: list[Path] = []
    install_fake_humble_crawl(monkeypatch, seen_cwd)
    (repo / "pending.txt").write_text("pending\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["scrape", "--git-worktree-allow-dirty", "humblebundle", "--non-interactive"])

    assert result.exit_code == 0, result.output
    assert (repo / "pending.txt").read_text(encoding="utf-8") == "pending\n"
    assert (repo / "lists" / "scraped.txt").exists()
# end def test_allow_dirty_scrapes_and_keeps_the_pending_changes


def test_invalid_worktree_unignore_aborts_the_run(repo: Path, monkeypatch: MonkeyPatch) -> None:
    seen_cwd: list[Path] = []
    install_fake_humble_crawl(monkeypatch, seen_cwd)
    (repo / ".worktree_unignore").write_text("missing-file\n", encoding="utf-8")
    git(repo, "add", ".worktree_unignore")
    git(repo, "commit", "-q", "-m", "add unignore")

    result = CliRunner().invoke(app, ["scrape", "humblebundle", "--non-interactive"])

    assert result.exit_code == 1
    assert "does not exist" in result.output
    assert seen_cwd == []
# end def test_invalid_worktree_unignore_aborts_the_run


def test_no_git_worktree_flag_uses_the_in_place_flow(repo: Path, monkeypatch: MonkeyPatch) -> None:
    seen_cwd: list[Path] = []
    install_fake_humble_crawl(monkeypatch, seen_cwd)

    result = CliRunner().invoke(app, ["scrape", "--no-git-worktree", "humblebundle", "--non-interactive"])

    assert result.exit_code == 0, result.output
    assert seen_cwd == [repo]
    assert "[crawl|humblebundle] manual scrape" in git(repo, "log", "-1", "--format=%s")
# end def test_no_git_worktree_flag_uses_the_in_place_flow


@pytest.mark.parametrize(
    "flags",
    [
        ["--git-style", "auto"],
        ["--git-style", "manual"],
        ["--git-worktree", ""],
        ["--git-worktree", "/tmp/x"],
        ["--no-git-worktree"],
        ["--git-worktree-allow-dirty"],
    ],
)
def test_no_git_cannot_be_combined_with_explicit_git_flags(flags: list[str], repo: Path) -> None:
    result = CliRunner().invoke(app, ["scrape", "--no-git", *flags, "humblebundle"])

    assert result.exit_code == 2
    assert "cannot be combined with --no-git" in result.output
# end def test_no_git_cannot_be_combined_with_explicit_git_flags


@pytest.mark.parametrize("flags", [["--git-worktree", "/tmp/x"], ["--git-worktree-allow-dirty"]])
def test_no_git_worktree_cannot_be_combined_with_worktree_options(flags: list[str], repo: Path) -> None:
    result = CliRunner().invoke(app, ["scrape", "--no-git-worktree", *flags, "humblebundle"])

    assert result.exit_code == 2
    assert "--no-git-worktree cannot be combined" in result.output
# end def test_no_git_worktree_cannot_be_combined_with_worktree_options


def test_no_git_alone_still_works(repo: Path, monkeypatch: MonkeyPatch) -> None:
    seen_cwd: list[Path] = []
    install_fake_humble_crawl(monkeypatch, seen_cwd)

    result = CliRunner().invoke(app, ["scrape", "--no-git", "humblebundle", "--non-interactive"])

    assert result.exit_code == 0, result.output
    assert seen_cwd == [repo]
# end def test_no_git_alone_still_works


def test_deferred_close_integrates_once_for_a_whole_run(repo: Path) -> None:
    import dataclasses

    session = scrape_git.begin_scrape_git_session(repo, True, "manual", worktree_subcommand="all")
    for name in ("one", "two"):
        copy = dataclasses.replace(session, defer_close=True)
        (copy.repository_root / "lists" / f"{name}.txt").write_text(name, encoding="utf-8")
        scrape_git.finish_scrape_git_session(copy, ["lists"], f"scrape {name}")
        assert copy.repository_root.exists()
    # end for
    assert not (repo / "lists" / "one.txt").exists()

    scrape_git.close_scrape_git_session(session)
    scrape_git.close_scrape_git_session(session)

    assert git(repo, "log", "--format=%s", "-2").splitlines() == ["scrape two", "scrape one"]
    assert Path.cwd() == repo
    assert not session.repository_root.exists()
# end def test_deferred_close_integrates_once_for_a_whole_run
