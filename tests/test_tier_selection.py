from __future__ import annotations

from game_collections.launchers.base import CollectionEligibility
from game_collections.launchers.tier_selection import select_tiers
from game_collections.models import TierKind


def _result(
    rank: int | None,
    owned: list[str],
    *,
    eligible: bool = True,
    kind: TierKind = "base",
    requires: list[int] | None = None,
    tier_name: str | None = None,
    parent: str = "example/bundle",
) -> CollectionEligibility:
    list_id = parent if rank is None else f"{parent}#tier-{rank}"
    return CollectionEligibility(
        list_id=list_id,
        name=f"Bundle — {tier_name}" if tier_name is not None else "Bundle",
        tier=rank,
        tier_name=tier_name,
        tier_kind=kind,
        tier_requires=requires or [],
        eligible=eligible,
        owned_ids=owned,
        missing_ids=[],
        unsupported_ids=[],
    )
# end def _result


def _social_multiplayer(*, charity_eligible: bool = True, upsell_eligible: bool = True) -> list[CollectionEligibility]:
    return [
        _result(1, ["steam:1"], tier_name="4.00 USD"),
        _result(2, ["steam:1", "steam:2"], tier_name="16.00 USD"),
        _result(
            3, ["steam:1", "steam:3"], eligible=charity_eligible, kind="charity", requires=[1],
            tier_name="Venezuela Earthquake Relief",
        ),
        _result(4, ["steam:1", "steam:4"], eligible=upsell_eligible, kind="upsell", requires=[1], tier_name="Map DLC"),
    ]
# end def _social_multiplayer


def test_highest_merges_eligible_add_ons_into_the_highest_base_tier() -> None:
    selected = select_tiers(_social_multiplayer(), "highest")

    assert len(selected) == 1
    assert selected[0].primary.list_id == "example/bundle#tier-2"
    assert selected[0].name == "Bundle — 16.00 USD + Charity: Venezuela Earthquake Relief + Upsell: Map DLC"
    assert selected[0].owned_ids == ["steam:1", "steam:2", "steam:3", "steam:4"]
# end def test_highest_merges_eligible_add_ons_into_the_highest_base_tier


def test_highest_leaves_out_add_ons_which_are_not_eligible() -> None:
    selected = select_tiers(_social_multiplayer(charity_eligible=False), "highest")

    assert selected[0].name == "Bundle — 16.00 USD + Upsell: Map DLC"
    assert selected[0].owned_ids == ["steam:1", "steam:2", "steam:4"]
# end def test_highest_leaves_out_add_ons_which_are_not_eligible


def test_highest_skips_an_add_on_whose_required_tier_is_not_fulfilled() -> None:
    results = _social_multiplayer()
    results[0] = _result(1, ["steam:1"], eligible=False, tier_name="4.00 USD")

    selected = select_tiers(results, "highest")

    assert selected[0].name == "Bundle — 16.00 USD"
# end def test_highest_skips_an_add_on_whose_required_tier_is_not_fulfilled


def test_highest_ignores_add_ons_without_an_eligible_base_tier() -> None:
    results = [
        _result(1, [], eligible=False, tier_name="4.00 USD"),
        _result(2, ["steam:3"], kind="charity", requires=[1], tier_name="Charity"),
    ]

    assert select_tiers(results, "highest") == []
# end def test_highest_ignores_add_ons_without_an_eligible_base_tier


def test_highest_picks_the_highest_eligible_base_tier_not_the_highest_rank() -> None:
    results = _social_multiplayer()
    results[1] = _result(2, ["steam:1"], eligible=False, tier_name="16.00 USD")

    selected = select_tiers(results, "highest")

    assert selected[0].primary.list_id == "example/bundle#tier-1"
# end def test_highest_picks_the_highest_eligible_base_tier_not_the_highest_rank


def test_all_selects_every_eligible_tier_on_its_own() -> None:
    selected = select_tiers(_social_multiplayer(upsell_eligible=False), "all")

    assert [collection.primary.list_id for collection in selected] == [
        "example/bundle#tier-1",
        "example/bundle#tier-2",
        "example/bundle#tier-3",
    ]
    assert all(collection.additions == () for collection in selected)
# end def test_all_selects_every_eligible_tier_on_its_own


def test_highest_keeps_plain_lists_and_the_order_of_the_input() -> None:
    results = [
        _result(None, ["steam:9"], parent="example/plain"),
        *_social_multiplayer(),
        _result(1, ["steam:5"], parent="example/other"),
    ]

    selected = select_tiers(results, "highest")

    assert [collection.primary.list_id for collection in selected] == [
        "example/plain",
        "example/bundle#tier-2",
        "example/other#tier-1",
    ]
# end def test_highest_keeps_plain_lists_and_the_order_of_the_input
