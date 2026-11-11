from __future__ import annotations

from pytest import MonkeyPatch
from typer.testing import CliRunner

from game_collections import cli
from game_collections.cli import app
from game_collections.scrape_all import ScrapeKind, ScraperSpec


def install_fake_registry(
    monkeypatch: MonkeyPatch, calls: list[str], failing: dict[str, BaseException] | None = None
) -> None:
    failing = failing or {}

    def make(name: str, kind: ScrapeKind) -> ScraperSpec:
        def run(ctx, refresh: bool, non_interactive: bool) -> None:  # noqa: ANN001
            calls.append(f"{name}:refresh={refresh}:ni={non_interactive}:stashed={ctx.obj.stashed}")
            if name in failing:
                raise failing[name]
            # end if
        # end def run

        return ScraperSpec(name, kind, run)
    # end def make

    monkeypatch.setattr(
        cli,
        "SCRAPERS",
        (
            make("agg", ScrapeKind.AGGREGATE),
            make("one", ScrapeKind.DIRECT),
            make("two", ScrapeKind.DIRECT),
        ),
    )
# end def install_fake_registry


def test_all_runs_direct_before_aggregate_and_passes_options(monkeypatch: MonkeyPatch) -> None:
    calls: list[str] = []
    install_fake_registry(monkeypatch, calls)

    result = CliRunner().invoke(app, ["scrape", "--no-git", "all", "--refresh", "--non-interactive"])

    assert result.exit_code == 0, result.output
    assert calls == [
        "one:refresh=True:ni=True:stashed=False",
        "two:refresh=True:ni=True:stashed=False",
        "agg:refresh=True:ni=True:stashed=False",
    ]
# end def test_all_runs_direct_before_aggregate_and_passes_options


def test_all_direct_and_all_aggregate_select_their_kind(monkeypatch: MonkeyPatch) -> None:
    calls: list[str] = []
    install_fake_registry(monkeypatch, calls)

    assert CliRunner().invoke(app, ["scrape", "--no-git", "all-direct"]).exit_code == 0
    assert [call.split(":")[0] for call in calls] == ["one", "two"]
    calls.clear()
    assert CliRunner().invoke(app, ["scrape", "--no-git", "all-aggregate"]).exit_code == 0
    assert [call.split(":")[0] for call in calls] == ["agg"]
# end def test_all_direct_and_all_aggregate_select_their_kind


def test_failure_does_not_stop_the_run_and_is_reported_at_the_end(monkeypatch: MonkeyPatch) -> None:
    import typer

    calls: list[str] = []
    install_fake_registry(monkeypatch, calls, {"one": typer.Exit(1), "agg": RuntimeError("boom")})

    result = CliRunner().invoke(app, ["scrape", "--no-git", "all"])

    assert result.exit_code == 1
    assert [call.split(":")[0] for call in calls] == ["one", "two", "agg"]
    assert "1/3 source(s) succeeded." in result.output
    assert "one: exited with code 1" in result.output
    assert "agg: RuntimeError: boom" in result.output
# end def test_failure_does_not_stop_the_run_and_is_reported_at_the_end


def test_skip_leaves_a_source_out_and_rejects_unknown_names(monkeypatch: MonkeyPatch) -> None:
    calls: list[str] = []
    install_fake_registry(monkeypatch, calls)

    assert CliRunner().invoke(app, ["scrape", "--no-git", "all", "--skip", "two"]).exit_code == 0
    assert [call.split(":")[0] for call in calls] == ["one", "agg"]
    assert CliRunner().invoke(app, ["scrape", "--no-git", "all", "--skip", "nope"]).exit_code != 0
# end def test_skip_leaves_a_source_out_and_rejects_unknown_names


def test_git_flag_restores_the_stash_once_after_all_sources(monkeypatch: MonkeyPatch) -> None:
    calls: list[str] = []
    install_fake_registry(monkeypatch, calls)
    git_calls: list[str] = []
    monkeypatch.setattr("game_collections.cli.git_ops.head", lambda root: git_calls.append("head") or "deadbeef")
    monkeypatch.setattr("game_collections.cli.git_ops.autostash", lambda root: git_calls.append("autostash") or True)
    monkeypatch.setattr(
        "game_collections.git_ops.restore_autostash", lambda root, head: git_calls.append("restore")
    )

    result = CliRunner().invoke(app, ["scrape", "--git", "--no-git-worktree", "all-direct"])

    assert result.exit_code == 0, result.output
    # Sources see `stashed=False` (they must not restore) and the restore happens exactly once, last.
    assert calls == ["one:refresh=False:ni=False:stashed=False", "two:refresh=False:ni=False:stashed=False"]
    assert git_calls == ["head", "autostash", "restore"]
# end def test_git_flag_restores_the_stash_once_after_all_sources


def test_scrape_help_groups_sources_by_kind() -> None:
    result = CliRunner().invoke(app, ["scrape", "--help"])

    assert result.exit_code == 0, result.output
    assert "Direct sources" in result.output
    assert "Aggregate sources" in result.output
    assert "(direct)" in result.output
    assert "(aggregate)" in result.output
# end def test_scrape_help_groups_sources_by_kind
