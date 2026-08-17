from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner
from pytest import CaptureFixture, MonkeyPatch

from game_collections.apply.config import ApplySelection, save_selection
from game_collections.cli import _print_plan, app
from game_collections.launchers.base import CollectionEligibility, PlannedCollectionChange, SyncPlan
from game_collections.lists import discover_game_lists
from test_steam_io import STEAM_ID, build_fake_steam


def _plan_with_eligible_and_skipped_lists() -> SyncPlan:
    return SyncPlan(
        launcher="steam",
        account="123",
        eligibility=[
            CollectionEligibility(
                list_id="valve/the-orange-box",
                name="The Orange Box",
                eligible=True,
                owned_ids=["steam:440"],
                missing_ids=[],
                unsupported_ids=[],
            ),
            CollectionEligibility(
                list_id="example/skipped",
                name="Skipped",
                eligible=False,
                owned_ids=[],
                missing_ids=["steam:10"],
                unsupported_ids=["Unknown game"],
            ),
        ],
        changes=[
            PlannedCollectionChange(
                list_id="valve/the-orange-box",
                target_id="uc-9Dldt76YmGbo",
                name="🗃️ The Orange Box",
                action="create-or-update",
                added_ids=["steam:440"],
            )
        ],
    )
# end def _plan_with_eligible_and_skipped_lists


def test_print_plan_hides_skipped_lists_by_default(capsys: CaptureFixture[str]) -> None:
    _print_plan(_plan_with_eligible_and_skipped_lists())

    output = capsys.readouterr().out
    assert output == (
        "eligible: valve/the-orange-box (The Orange Box)\n"
        "Planned collection changes: 1 (1 create/update, 0 delete)\n"
    )
# end def test_print_plan_hides_skipped_lists_by_default


def test_print_plan_logs_skipped_lists_when_requested(capsys: CaptureFixture[str]) -> None:
    _print_plan(_plan_with_eligible_and_skipped_lists(), log_skips=True)

    output = capsys.readouterr().out
    assert output == (
        "eligible: valve/the-orange-box (The Orange Box)\n"
        "skipped: example/skipped (Skipped)\n"
        "  missing: steam:10\n"
        "  no Steam ID: Unknown game\n"
        "Planned collection changes: 1 (1 create/update, 0 delete)\n"
    )
# end def test_print_plan_logs_skipped_lists_when_requested


def test_print_plan_always_reports_managed_deletions(capsys: CaptureFixture[str]) -> None:
    plan = SyncPlan(
        launcher="steam",
        account="123",
        eligibility=[],
        changes=[
            PlannedCollectionChange(
                target_id="uc-orphan123",
                name="🗃️ Orphan",
                action="delete",
            )
        ],
    )

    _print_plan(plan)

    assert capsys.readouterr().out == (
        "delete: uc-orphan123 (🗃️ Orphan)\n"
        "Planned collection changes: 1 (0 create/update, 1 delete)\n"
    )
# end def test_print_plan_always_reports_managed_deletions


def test_sync_help_lists_matching_and_tier_choices() -> None:
    result = CliRunner().invoke(app, ["sync", "--help"])

    assert result.exit_code == 0
    assert "--min-owned" in result.output
    assert "--max-owned" in result.output
    assert "--min-missing" in result.output
    assert "--max-missing" in result.output
    assert "--unresolved-handling" in result.output
    assert "--unsupported-store-h" in result.output  # truncated by rich's help table at this column width
    assert "--tiers" in result.output
    assert "highest" in result.output
# end def test_sync_help_lists_matching_and_tier_choices


def test_sync_rejects_invalid_matching_mode_before_steam_discovery() -> None:
    result = CliRunner().invoke(app, ["sync", "--min-owned", "not-a-number"])

    assert result.exit_code == 2
    assert "Invalid value for '--min-owned'" in result.output
# end def test_sync_rejects_invalid_matching_mode_before_steam_discovery


def test_sync_none_requires_confirmation_and_adds_every_listed_steam_id(tmp_path: Path) -> None:
    steam_root = build_fake_steam(tmp_path)
    lists_root = tmp_path / "lists"
    _write_list(lists_root / "vendor/one.yml", "One")

    result = CliRunner().invoke(
        app,
        [
            "sync",
            "--source",
            "none",
            "--steam-root",
            str(steam_root),
            "--steam-id",
            STEAM_ID,
            "--lists-root",
            str(lists_root),
            "--selection-config",
            str(tmp_path / "missing-selection.yml"),
        ],
        input="y\n",
    )

    assert result.exit_code == 0, result.output
    assert "does not verify Steam ownership" in result.output
    assert "eligible: vendor/one (One)" in result.output
    assert "Planned collection changes: 1 (1 create/update, 0 delete)" in result.output
# end def test_sync_none_requires_confirmation_and_adds_every_listed_steam_id


def test_sync_auto_errors_after_every_automatic_source_fails(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    steam_root = build_fake_steam(tmp_path)
    attempted: list[str] = []

    def unavailable(name: str):
        def source(*_args: object) -> object:
            def read() -> set[int]:
                attempted.append(name)
                raise RuntimeError(f"{name} unavailable")
            # end def read
            return read
        # end def source
        return source
    # end def unavailable

    monkeypatch.setattr("game_collections.cli.owned_app_ids_from_api", unavailable("api"))
    monkeypatch.setattr("game_collections.cli.owned_app_ids_from_collection", unavailable("collection"))
    monkeypatch.setattr("game_collections.cli.owned_app_ids_from_installed", unavailable("installed"))

    result = CliRunner().invoke(
        app,
        ["sync", "--steam-root", str(steam_root), "--steam-id", STEAM_ID, "--api-key", "test-key"],
    )

    assert result.exit_code == 1, result.output
    assert attempted == ["api", "collection", "installed"]
    assert "could not determine Steam ownership automatically" in result.output
# end def test_sync_auto_errors_after_every_automatic_source_fails


def test_scrape_humblebundle_help_lists_git_flag() -> None:
    result = CliRunner().invoke(app, ["scrape", "humblebundle", "--help"])

    assert result.exit_code == 0
    assert "--git" in result.output
# end def test_scrape_humblebundle_help_lists_git_flag


def test_scrape_isthereanydeal_help_lists_git_flag() -> None:
    result = CliRunner().invoke(app, ["scrape", "isthereanydeal", "--help"])

    assert result.exit_code == 0
    assert "--git" in result.output
# end def test_scrape_isthereanydeal_help_lists_git_flag


def test_scrape_humblebundle_git_flag_stashes_scrapes_commits_then_restores(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from game_collections.sources.humblebundle.crawler import HumbleCrawlReport
    from game_collections.sources.humblebundle.resolver import HumbleResolutionMap

    calls: list[str] = []
    monkeypatch.setattr("game_collections.cli.git_ops.head", lambda root: calls.append("head") or "deadbeef")
    monkeypatch.setattr(
        "game_collections.cli.git_ops.autostash", lambda root: calls.append("autostash") or True
    )
    monkeypatch.setattr(
        "game_collections.cli.git_ops.commit_changed_paths",
        lambda root, paths, message: calls.append("commit") or True,
    )
    monkeypatch.setattr(
        "game_collections.cli.git_ops.restore_autostash", lambda root, head: calls.append("restore")
    )
    monkeypatch.setattr(
        "game_collections.cli.HumbleHttpClient",
        lambda: SimpleNamespace(close=lambda: None, fetch=lambda url: ""),
    )
    monkeypatch.setattr(
        "game_collections.cli.load_resolution_map", lambda path: HumbleResolutionMap(schema=1, games={})
    )
    monkeypatch.setattr("game_collections.cli.StorefrontResolver", lambda fetch, choose: object())
    monkeypatch.setattr(
        "game_collections.cli.crawl_humble_offers",
        lambda *args, **kwargs: calls.append("scrape") or HumbleCrawlReport(offers=(), errors=()),
    )

    result = CliRunner().invoke(app, ["scrape", "humblebundle", "--git", "--non-interactive"])

    assert result.exit_code == 0, result.output
    assert calls == ["head", "autostash", "scrape", "commit", "restore"]
# end def test_scrape_humblebundle_git_flag_stashes_scrapes_commits_then_restores


def test_scrape_humblebundle_git_flag_restores_even_when_scrape_raises(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from game_collections.sources.humblebundle.resolver import HumbleResolutionMap

    calls: list[str] = []
    monkeypatch.setattr("game_collections.cli.git_ops.head", lambda root: calls.append("head") or "deadbeef")
    monkeypatch.setattr(
        "game_collections.cli.git_ops.autostash", lambda root: calls.append("autostash") or True
    )
    monkeypatch.setattr(
        "game_collections.cli.git_ops.commit_changed_paths",
        lambda root, paths, message: calls.append("commit") or True,
    )
    monkeypatch.setattr(
        "game_collections.cli.git_ops.restore_autostash", lambda root, head: calls.append("restore")
    )
    monkeypatch.setattr(
        "game_collections.cli.HumbleHttpClient",
        lambda: SimpleNamespace(close=lambda: None, fetch=lambda url: ""),
    )
    monkeypatch.setattr(
        "game_collections.cli.load_resolution_map", lambda path: HumbleResolutionMap(schema=1, games={})
    )
    monkeypatch.setattr("game_collections.cli.StorefrontResolver", lambda fetch, choose: object())

    def raising_crawl(*args: object, **kwargs: object) -> object:
        calls.append("scrape")
        raise RuntimeError("network exploded")
    # end def raising_crawl

    monkeypatch.setattr("game_collections.cli.crawl_humble_offers", raising_crawl)

    result = CliRunner().invoke(app, ["scrape", "humblebundle", "--git", "--non-interactive"])

    assert result.exit_code == 1, result.output
    assert calls == ["head", "autostash", "scrape", "commit", "restore"]
# end def test_scrape_humblebundle_git_flag_restores_even_when_scrape_raises


def test_apply_help_lists_options() -> None:
    result = CliRunner().invoke(app, ["apply", "--help"])

    assert result.exit_code == 0
    assert "--selection-config" in result.output
    assert "--min-missing" in result.output
    assert "--max-missing" in result.output
    assert "--tiers" in result.output
# end def test_apply_help_lists_options


def _write_list(path: Path, name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"schema: 1\nname: {name}\ngames:\n  - name: One\n    ids: [steam:440]\n", encoding="utf-8")
# end def _write_list


def test_apply_filters_excluded_list_before_planning(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    steam_root = build_fake_steam(tmp_path)
    lists_root = tmp_path / "lists"
    _write_list(lists_root / "vendor/one.yml", "One")
    _write_list(lists_root / "vendor/two.yml", "Two")
    selection_config = tmp_path / "config/apply-selection.yml"

    fixed_selection = ApplySelection(
        schema=1,
        selected=["vendor/one"],
        excluded=["vendor/two"],
        updated_at=datetime(2026, 7, 13, tzinfo=UTC),
    )

    captured_owned_app_ids: list[object] = []

    class _StubPickerApp:
        def __init__(
            self,
            lists_root: Path,
            excluded: object,
            min_missing: int | None = None,
            max_missing: int | None = 0,
            unresolved_handling: str = "ignore",
            unsupported_store_handling: str = "ignore",
            tier_mode: str = "highest",
            min_items: int | None = None,
            max_items: int | None = None,
            date_after: str | None = None,
            date_before: str | None = None,
            show_filtered: bool = False,
            owned_app_ids: object = None,
            ownership_resolver: object = None,
            confirm_unverified_ownership: bool = False,
            initial_selection: ApplySelection | None = None,
        ) -> None:
            self.all_game_lists = discover_game_lists(lists_root)
            self.min_missing = min_missing
            self.max_missing = max_missing
            self.tier_mode = tier_mode
            captured_owned_app_ids.append(owned_app_ids)
        # end def __init__

        def run(self) -> ApplySelection:
            return fixed_selection
        # end def run
    # end class _StubPickerApp

    monkeypatch.setattr("game_collections.apply.tui.ApplyPickerApp", _StubPickerApp)

    result = CliRunner().invoke(
        app,
        [
            "apply",
            "--lists-root",
            str(lists_root),
            "--steam-root",
            str(steam_root),
            "--steam-id",
            STEAM_ID,
            "--source",
            "collection",
            "--collection",
            "Favorites",
            "--selection-config",
            str(selection_config),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "eligible: vendor/one (One)" in result.output
    assert "vendor/two" not in result.output
    assert selection_config.exists()
    # valid Steam access (a real collection source here) resolves ownership up front for the picker
    assert captured_owned_app_ids == [frozenset({440})]
# end def test_apply_filters_excluded_list_before_planning


def test_apply_filter_flags_fall_back_to_saved_selection_then_default(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    steam_root = build_fake_steam(tmp_path)
    lists_root = tmp_path / "lists"
    _write_list(lists_root / "vendor/one.yml", "One")
    selection_config = tmp_path / "config/apply-selection.yml"
    save_selection(
        ApplySelection(
            schema=1,
            selected=["vendor/one"],
            excluded=[],
            updated_at=datetime(2026, 7, 13, tzinfo=UTC),
            min_items=2,
            max_missing=5,
            unresolved_handling="hide",
            unsupported_store_handling="enforce",
            tier_mode="all",
            show_filtered=True,
        ),
        selection_config,
    )

    captured_kwargs: list[dict[str, object]] = []

    class _StubPickerApp:
        def __init__(self, lists_root: Path, excluded: object, **kwargs: object) -> None:
            self.all_game_lists = discover_game_lists(lists_root)
            self.min_missing = kwargs.get("min_missing")
            self.max_missing = kwargs.get("max_missing")
            self.tier_mode = kwargs.get("tier_mode")
            captured_kwargs.append(kwargs)
        # end def __init__

        def run(self) -> None:
            return None
        # end def run
    # end class _StubPickerApp

    monkeypatch.setattr("game_collections.apply.tui.ApplyPickerApp", _StubPickerApp)

    # No filter flags passed: everything should come from the saved selection.
    result = CliRunner().invoke(
        app,
        [
            "apply",
            "--lists-root",
            str(lists_root),
            "--steam-root",
            str(steam_root),
            "--steam-id",
            STEAM_ID,
            "--source",
            "collection",
            "--collection",
            "Favorites",
            "--selection-config",
            str(selection_config),
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured_kwargs[-1]["min_items"] == 2
    assert captured_kwargs[-1]["max_missing"] == 5
    assert captured_kwargs[-1]["unresolved_handling"] == "hide"
    assert captured_kwargs[-1]["unsupported_store_handling"] == "enforce"
    assert captured_kwargs[-1]["tier_mode"] == "all"
    assert captured_kwargs[-1]["show_filtered"] is True

    # An explicit CLI flag overrides the saved selection's value for that field only.
    result = CliRunner().invoke(
        app,
        [
            "apply",
            "--lists-root",
            str(lists_root),
            "--steam-root",
            str(steam_root),
            "--steam-id",
            STEAM_ID,
            "--source",
            "collection",
            "--collection",
            "Favorites",
            "--selection-config",
            str(selection_config),
            "--max-missing",
            "9",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured_kwargs[-1]["max_missing"] == 9
    assert captured_kwargs[-1]["unresolved_handling"] == "hide"
# end def test_apply_filter_flags_fall_back_to_saved_selection_then_default


def test_apply_dry_run_reopens_the_saved_selection_action_menu(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    steam_root = build_fake_steam(tmp_path)
    lists_root = tmp_path / "lists"
    _write_list(lists_root / "vendor/one.yml", "One")
    selection_config = tmp_path / "config/apply-selection.yml"
    fixed_selection = ApplySelection(
        schema=1,
        selected=["vendor/one"],
        excluded=[],
        updated_at=datetime(2026, 7, 16, tzinfo=UTC),
    )
    initial_selections: list[ApplySelection | None] = []

    class _PickerResult:
        def __init__(self, action: str) -> None:
            self.selection = fixed_selection
            self.action = action
        # end def __init__
    # end class _PickerResult

    class _StubPickerApp:
        def __init__(self, lists_root: Path, excluded: object, **kwargs: object) -> None:
            self.all_game_lists = discover_game_lists(lists_root)
            self.min_missing = None
            self.max_missing = 0
            self.unresolved_handling = "ignore"
            self.unsupported_store_handling = "ignore"
            self.tier_mode = "highest"
            self.row_filters = SimpleNamespace(min_items=None, max_items=None, date_after=None, date_before=None)
            self.show_filtered = False
            initial_selections.append(kwargs.get("initial_selection"))
        # end def __init__

        def run(self) -> _PickerResult:
            return _PickerResult("dry-run" if len(initial_selections) == 1 else "close")
        # end def run
    # end class _StubPickerApp

    monkeypatch.setattr("game_collections.apply.tui.ApplyPickerApp", _StubPickerApp)

    result = CliRunner().invoke(
        app,
        [
            "apply",
            "--lists-root",
            str(lists_root),
            "--steam-root",
            str(steam_root),
            "--steam-id",
            STEAM_ID,
            "--source",
            "collection",
            "--collection",
            "Favorites",
            "--selection-config",
            str(selection_config),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Dry run only. Returning to the picker action menu." in result.output
    assert initial_selections == [None, fixed_selection]
# end def test_apply_dry_run_reopens_the_saved_selection_action_menu


def test_apply_cancelled_selection_makes_no_changes(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    lists_root = tmp_path / "lists"
    _write_list(lists_root / "vendor/one.yml", "One")
    selection_config = tmp_path / "config/apply-selection.yml"

    captured_owned_app_ids: list[object] = []

    class _StubPickerApp:
        def __init__(
            self,
            lists_root: Path,
            excluded: object,
            min_missing: int | None = None,
            max_missing: int | None = 0,
            unresolved_handling: str = "ignore",
            unsupported_store_handling: str = "ignore",
            tier_mode: str = "highest",
            min_items: int | None = None,
            max_items: int | None = None,
            date_after: str | None = None,
            date_before: str | None = None,
            show_filtered: bool = False,
            owned_app_ids: object = None,
            ownership_resolver: object = None,
            confirm_unverified_ownership: bool = False,
            initial_selection: ApplySelection | None = None,
        ) -> None:
            self.all_game_lists = discover_game_lists(lists_root)
            self.min_missing = min_missing
            self.max_missing = max_missing
            self.tier_mode = tier_mode
            captured_owned_app_ids.append(owned_app_ids)
        # end def __init__

        def run(self) -> None:
            return None
        # end def run
    # end class _StubPickerApp

    monkeypatch.setattr("game_collections.apply.tui.ApplyPickerApp", _StubPickerApp)

    result = CliRunner().invoke(
        app,
        ["apply", "--lists-root", str(lists_root), "--selection-config", str(selection_config)],
    )

    assert result.exit_code == 0, result.output
    assert "Cancelled" in result.output
    assert len(captured_owned_app_ids) == 1
    assert not selection_config.exists()
# end def test_apply_cancelled_selection_makes_no_changes
