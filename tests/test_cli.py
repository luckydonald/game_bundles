from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner
from pytest import CaptureFixture, MonkeyPatch

from game_collections.apply.config import ApplySelection
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
    assert "--unconfigured-handling" in result.output
    assert "--tiers" in result.output
    assert "highest" in result.output
# end def test_sync_help_lists_matching_and_tier_choices


def test_sync_rejects_invalid_matching_mode_before_steam_discovery() -> None:
    result = CliRunner().invoke(app, ["sync", "--min-owned", "not-a-number"])

    assert result.exit_code == 2
    assert "Invalid value for '--min-owned'" in result.output
# end def test_sync_rejects_invalid_matching_mode_before_steam_discovery


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
            unconfigured_handling: str = "ignore",
            tier_mode: str = "highest",
            owned_app_ids: object = None,
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
            unconfigured_handling: str = "ignore",
            tier_mode: str = "highest",
            owned_app_ids: object = None,
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
    # no Steam access at all was given - the picker still opens (and can still be cancelled)
    # without it, just without ownership marks
    assert captured_owned_app_ids == [None]
    assert "could not determine Steam ownership" in result.output
    assert not selection_config.exists()
# end def test_apply_cancelled_selection_makes_no_changes
