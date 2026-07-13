from __future__ import annotations

from typer.testing import CliRunner
from pytest import CaptureFixture

from game_collections.cli import _print_plan, app
from game_collections.launchers.base import CollectionEligibility, PlannedCollectionChange, SyncPlan


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
    assert "--mode" in result.output
    assert "any" in result.output
    assert "all" in result.output
    assert "--tiers" in result.output
    assert "highest" in result.output
# end def test_sync_help_lists_matching_and_tier_choices


def test_sync_rejects_invalid_matching_mode_before_steam_discovery() -> None:
    result = CliRunner().invoke(app, ["sync", "--mode", "some"])

    assert result.exit_code == 2
    assert "Invalid value for '--mode'" in result.output
# end def test_sync_rejects_invalid_matching_mode_before_steam_discovery
