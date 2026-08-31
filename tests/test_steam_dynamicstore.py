from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from game_collections.launchers.steam.adapter import owned_app_ids_from_dynamicstore
from game_collections.launchers.steam.dynamicstore import (
    DynamicStoreDumpFile,
    SteamDynamicStoreUserData,
    load_dynamicstore_dump,
)


REFERENCE_DUMP_PATH = Path(
    "ai/references/https/store.steampowered.com/dynamicstore/userdata/_.json"
)


def _minimal_payload(owned_apps: list[int]) -> dict:
    return {
        "rgOwnedApps": owned_apps,
        "bShowFilteredUserReviewScores": True,
        "rgPrimaryLanguage": 0,
        "bAllowAppImpressions": 0,
        "nCartLineItemCount": 0,
        "nRemainingCartDiscount": 0,
        "nTotalCartDiscount": 0,
    }
# end def _minimal_payload


@pytest.mark.skipif(not REFERENCE_DUMP_PATH.exists(), reason="requires the real reference dump")
def test_real_reference_dump_validates_and_contains_the_known_owned_dlc() -> None:
    data = json.loads(REFERENCE_DUMP_PATH.read_text(encoding="utf-8"))

    model = SteamDynamicStoreUserData.model_validate(data)

    assert len(model.rgOwnedApps) == 2322
    assert 377160 in model.rgOwnedApps  # Fallout 4 (base game)
    assert 540810 in model.rgOwnedApps  # Fallout 4 - High Resolution Texture Pack (DLC)
# end def test_real_reference_dump_validates_and_contains_the_known_owned_dlc


def test_dump_file_requires_a_timezone_aware_fetched_at(tmp_path: Path) -> None:
    path = tmp_path / "dump.json"
    path.write_text(
        json.dumps({"fetched_at": "2026-08-15T14:32:00", "data": _minimal_payload([10])}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="timezone"):
        load_dynamicstore_dump(path)
    # end with
# end def test_dump_file_requires_a_timezone_aware_fetched_at


def test_owned_app_ids_from_dynamicstore_reads_the_envelope(tmp_path: Path) -> None:
    path = tmp_path / "dump.json"
    envelope = DynamicStoreDumpFile(
        fetched_at=datetime(2026, 8, 15, 14, 32, tzinfo=UTC),
        data=SteamDynamicStoreUserData.model_validate(_minimal_payload([377160, 540810])),
    )
    path.write_text(envelope.model_dump_json(), encoding="utf-8")

    source = owned_app_ids_from_dynamicstore(path)

    assert source() == {377160, 540810}
# end def test_owned_app_ids_from_dynamicstore_reads_the_envelope


def test_owned_app_ids_from_dynamicstore_missing_file_raises_oserror(tmp_path: Path) -> None:
    source = owned_app_ids_from_dynamicstore(tmp_path / "missing.json")

    with pytest.raises(OSError):
        source()
    # end with
# end def test_owned_app_ids_from_dynamicstore_missing_file_raises_oserror
