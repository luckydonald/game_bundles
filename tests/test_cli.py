from __future__ import annotations

from pytest import CaptureFixture

from game_collections.cli import _print_plan
from game_collections.launchers.base import CollectionEligibility, SyncPlan


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
        changes=[],
    )
# end def _plan_with_eligible_and_skipped_lists


def test_print_plan_hides_skipped_lists_by_default(capsys: CaptureFixture[str]) -> None:
    _print_plan(_plan_with_eligible_and_skipped_lists())

    output = capsys.readouterr().out
    assert output == (
        "eligible: valve/the-orange-box (The Orange Box)\n"
        "Planned collection changes: 0\n"
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
        "Planned collection changes: 0\n"
    )
# end def test_print_plan_logs_skipped_lists_when_requested
