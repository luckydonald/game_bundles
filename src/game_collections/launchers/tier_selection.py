"""Launcher-neutral choice of which tier collections of each bundle get synchronized."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from game_collections.launchers.base import CollectionEligibility
from game_collections.lists import split_tier_suffix
from game_collections.models import TierKind


TierMode = Literal["all", "highest"]

KIND_LABELS: dict[TierKind, str] = {"base": "", "charity": "Charity: ", "upsell": "Upsell: "}


@dataclass(frozen=True, slots=True)
class SelectedCollection:
    """One collection to synchronize: a tier list plus the add-on tiers merged into it."""

    primary: CollectionEligibility
    additions: tuple[CollectionEligibility, ...] = ()

    @property
    def name(self) -> str:
        """The primary's name, extended by each merged add-on's kind label and tier name."""
        parts = [self.primary.name]
        for addition in self.additions:
            parts.append(f"{KIND_LABELS[addition.tier_kind]}{addition.tier_name or addition.name}")
        # end for
        return " + ".join(parts)
    # end def name

    @property
    def owned_ids(self) -> list[str]:
        """Owned ids of the primary followed by those only the merged add-ons contribute."""
        owned = list(self.primary.owned_ids)
        seen = set(owned)
        for addition in self.additions:
            for identifier in addition.owned_ids:
                if identifier in seen:
                    continue
                # end if
                seen.add(identifier)
                owned.append(identifier)
            # end for
        # end for
        return owned
    # end def owned_ids

# end class SelectedCollection


def select_tiers(eligibility: list[CollectionEligibility], mode: TierMode) -> list[SelectedCollection]:
    """Pick the collections to synchronize, keeping the order of `eligibility`.

    `all` selects every eligible list on its own. `highest` selects, per bundle, only the highest
    eligible self-contained tier (the "highest tier I own"), and merges into it every eligible
    dependent add-on tier (non-empty `tier_requires`) of the same bundle whose required tiers are
    fulfilled, so the add-ons extend that one collection's name and games instead of getting their
    own collection. Without an eligible self-contained tier, no add-on is selected either.
    """
    if mode == "all":
        return [SelectedCollection(result) for result in eligibility if result.eligible]
    # end if

    by_parent: dict[str, dict[int, CollectionEligibility]] = {}
    for result in eligibility:
        if result.tier is None:
            continue
        # end if
        parent = split_tier_suffix(result.list_id)[0]
        ranks = by_parent.setdefault(parent, {})
        previous = ranks.get(result.tier)
        if previous is not None:
            raise ValueError(f"ambiguous tier rank {result.tier} in {parent!r}: {previous.list_id!r} and {result.list_id!r}")
        # end if
        ranks[result.tier] = result
    # end for

    primaries: dict[str, SelectedCollection] = {}
    for parent, ranks in by_parent.items():
        ordered = [ranks[rank] for rank in sorted(ranks)]
        eligible_bases = [result for result in ordered if result.eligible and not result.tier_requires]
        if not eligible_bases:
            continue
        # end if
        primary = eligible_bases[-1]
        additions: list[CollectionEligibility] = []
        for result in ordered:
            if not result.eligible or not result.tier_requires:
                continue
            # end if
            if not all(ranks[required].eligible for required in result.tier_requires if required in ranks):
                continue
            # end if
            additions.append(result)
        # end for
        primaries[primary.list_id] = SelectedCollection(primary, tuple(additions))
    # end for

    selected: list[SelectedCollection] = []
    for result in eligibility:
        if result.tier is None:
            if result.eligible:
                selected.append(SelectedCollection(result))
            # end if
            continue
        # end if
        collection = primaries.get(result.list_id)
        if collection is not None:
            selected.append(collection)
        # end if
    # end for
    return selected
# end def select_tiers
