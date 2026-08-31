from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from game_collections.launchers.steam.adapter import owned_app_ids_from_dynamicstore
from game_collections.launchers.steam.dynamicstore import (
    DynamicStoreDumpFile,
    SteamDynamicStoreUserData,
    describe_dump_age,
    load_dynamicstore_dump,
    save_dynamicstore_dump,
    should_prompt_for_refresh,
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


@pytest.mark.parametrize(
    ("force", "interactive", "expected"),
    [
        (None, True, True),
        (None, False, False),
        (True, False, True),
        (False, True, False),
    ],
)
def test_should_prompt_for_refresh(force: bool | None, interactive: bool, expected: bool) -> None:
    assert should_prompt_for_refresh(force=force, interactive=interactive) is expected
# end def test_should_prompt_for_refresh


def test_describe_dump_age_reports_no_dump_yet() -> None:
    assert describe_dump_age(None, datetime(2026, 8, 30, tzinfo=UTC)) == "No dynamicstore dump has been exported yet."
# end def test_describe_dump_age_reports_no_dump_yet


def test_describe_dump_age_reports_relative_days() -> None:
    envelope = DynamicStoreDumpFile(
        fetched_at=datetime(2026, 8, 14, 14, 32, tzinfo=UTC),
        data=SteamDynamicStoreUserData.model_validate(_minimal_payload([])),
    )

    description = describe_dump_age(envelope, datetime(2026, 8, 30, 14, 32, tzinfo=UTC))

    assert description == "Last updated: 2026-08-14 14:32 UTC (16 days ago)"
# end def test_describe_dump_age_reports_relative_days


def test_save_dynamicstore_dump_validates_and_writes(tmp_path: Path) -> None:
    path = tmp_path / "dump.json"
    raw = json.dumps(_minimal_payload([377160, 540810]))

    envelope = save_dynamicstore_dump(path, raw, datetime(2026, 8, 30, tzinfo=UTC))

    assert envelope.data.rgOwnedApps == [377160, 540810]
    reloaded = load_dynamicstore_dump(path)
    assert reloaded.data.rgOwnedApps == [377160, 540810]
    assert reloaded.fetched_at == datetime(2026, 8, 30, tzinfo=UTC)
# end def test_save_dynamicstore_dump_validates_and_writes


def test_save_dynamicstore_dump_rejects_invalid_json(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid dynamicstore dump JSON"):
        save_dynamicstore_dump(tmp_path / "dump.json", "not json", datetime(2026, 8, 30, tzinfo=UTC))
    # end with
# end def test_save_dynamicstore_dump_rejects_invalid_json
