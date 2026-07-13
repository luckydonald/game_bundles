from __future__ import annotations

import json
from pathlib import Path

import pytest

from game_collections.launchers.base import PlannedCollectionChange, SyncPlan
from game_collections.launchers.steam.io import (
    MODIFIED_NAME,
    NAMESPACE_NAME,
    SteamFileGateway,
    SteamIoError,
    steam_collection_id,
)
from game_collections.launchers.steam.models import (
    CloudStorageNamespaceFile,
    ModifiedKeysFile,
    SteamCollectionPayload,
    parse_json_strict,
)


FIXTURES = Path(__file__).parent / "fixtures/steam"
STEAM_ID = "76561198044975919"
ACCOUNT_ID = "84710191"


def build_fake_steam(tmp_path: Path) -> Path:
    steam_root = tmp_path / "Steam"
    cloud = steam_root / "userdata" / ACCOUNT_ID / "config/cloudstorage"
    cloud.mkdir(parents=True)
    (steam_root / "config").mkdir()
    (steam_root / "config/loginusers.vdf").write_bytes((FIXTURES / "loginusers.vdf").read_bytes())
    for name in ("cloud-storage-namespaces.json", NAMESPACE_NAME, MODIFIED_NAME):
        (cloud / name).write_bytes((FIXTURES / name).read_bytes())
    # end for
    return steam_root
# end def build_fake_steam


def orange_box_plan() -> SyncPlan:
    return SyncPlan(
        launcher="steam",
        account=STEAM_ID,
        eligibility=[],
        changes=[
            PlannedCollectionChange(
                list_id="valve/the-orange-box",
                name="The Orange Box",
                action="create-or-update",
                added_ids=["steam:220", "steam:380", "steam:420", "steam:400", "steam:440"],
            )
        ],
    )
# end def orange_box_plan


def test_stage_creates_inspectable_candidates_without_touching_steam(tmp_path: Path) -> None:
    steam_root = build_fake_steam(tmp_path)
    cloud = steam_root / "userdata" / ACCOUNT_ID / "config/cloudstorage"
    before = {name: (cloud / name).read_bytes() for name in (NAMESPACE_NAME, MODIFIED_NAME)}
    gateway = SteamFileGateway(steam_root, STEAM_ID)

    staged = gateway.stage(orange_box_plan(), tmp_path / "Desktop")

    assert {name: (cloud / name).read_bytes() for name in before} == before
    assert (staged / "README.txt").is_file()
    assert (staged / "manifest.json").is_file()
    namespace = parse_json_strict(
        (staged / f"candidate-{NAMESPACE_NAME}").read_bytes(),
        CloudStorageNamespaceFile,
    )
    modified = parse_json_strict(
        (staged / f"candidate-{MODIFIED_NAME}").read_bytes(),
        ModifiedKeysFile,
    )
    collection_id = steam_collection_id("valve/the-orange-box")
    key = f"user-collections.{collection_id}"
    payload = SteamCollectionPayload.from_entry(dict(namespace.root)[key])
    assert payload.name == "The Orange Box"
    assert payload.added == [220, 380, 400, 420, 440]
    assert key in modified.root
# end def test_stage_creates_inspectable_candidates_without_touching_steam


def test_orange_box_generation_matches_expected_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    steam_root = build_fake_steam(tmp_path)
    gateway = SteamFileGateway(steam_root, STEAM_ID)
    monkeypatch.setattr("game_collections.launchers.steam.io.time.time", lambda: 1_600_000_000)

    staged = gateway.stage(orange_box_plan(), tmp_path / "Desktop")

    assert json.loads((staged / f"candidate-{NAMESPACE_NAME}").read_bytes()) == json.loads(
        (FIXTURES / "expected-orange-box-cloud-storage-namespace-1.json").read_bytes()
    )
    assert json.loads((staged / f"candidate-{MODIFIED_NAME}").read_bytes()) == json.loads(
        (FIXTURES / "expected-orange-box-cloud-storage-namespace-1.modified.json").read_bytes()
    )
# end def test_orange_box_generation_matches_expected_files


def test_apply_requires_confirmation_then_restore_round_trip(tmp_path: Path) -> None:
    steam_root = build_fake_steam(tmp_path)
    cloud = steam_root / "userdata" / ACCOUNT_ID / "config/cloudstorage"
    originals = {name: (cloud / name).read_bytes() for name in (NAMESPACE_NAME, MODIFIED_NAME)}
    gateway = SteamFileGateway(steam_root, STEAM_ID)
    staged = gateway.stage(orange_box_plan(), tmp_path / "Desktop")

    with pytest.raises(SteamIoError, match="confirmation declined"):
        gateway.apply(staged, lambda _prompt: "NO")
    # end with
    assert {name: (cloud / name).read_bytes() for name in originals} == originals

    gateway.apply(staged, lambda _prompt: "REPLACE")
    assert (cloud / NAMESPACE_NAME).read_bytes() != originals[NAMESPACE_NAME]
    assert (staged / "manifest-applied.json").is_file()

    gateway.restore(staged, lambda _prompt: "RESTORE")
    assert {name: (cloud / name).read_bytes() for name in originals} == originals
    assert (staged / "manifest-restored.json").is_file()
# end def test_apply_requires_confirmation_then_restore_round_trip


def test_apply_rejects_source_changes_after_staging(tmp_path: Path) -> None:
    steam_root = build_fake_steam(tmp_path)
    cloud = steam_root / "userdata" / ACCOUNT_ID / "config/cloudstorage"
    gateway = SteamFileGateway(steam_root, STEAM_ID)
    staged = gateway.stage(orange_box_plan(), tmp_path / "Desktop")
    modified_path = cloud / MODIFIED_NAME
    modified_path.write_text("[\"changed-after-staging\"]", encoding="utf-8")

    with pytest.raises(SteamIoError, match="source changed"):
        gateway.apply(staged, lambda _prompt: "REPLACE")
    # end with
# end def test_apply_rejects_source_changes_after_staging


def test_apply_rejects_tampered_candidate(tmp_path: Path) -> None:
    steam_root = build_fake_steam(tmp_path)
    gateway = SteamFileGateway(steam_root, STEAM_ID)
    staged = gateway.stage(orange_box_plan(), tmp_path / "Desktop")
    candidate = staged / f"candidate-{MODIFIED_NAME}"
    candidate.write_text(json.dumps(["tampered"]), encoding="utf-8")

    with pytest.raises(SteamIoError, match="hash changed"):
        gateway.apply(staged, lambda _prompt: "REPLACE")
    # end with
# end def test_apply_rejects_tampered_candidate


def test_apply_refuses_active_steam_pipe(tmp_path: Path) -> None:
    steam_root = build_fake_steam(tmp_path)
    gateway = SteamFileGateway(steam_root, STEAM_ID)
    staged = gateway.stage(orange_box_plan(), tmp_path / "Desktop")
    (steam_root / "steam.pipe").touch()

    with pytest.raises(SteamIoError, match="IPC pipe"):
        gateway.apply(staged, lambda _prompt: "REPLACE")
    # end with
# end def test_apply_refuses_active_steam_pipe


def test_repeat_stage_preserves_manual_apps_and_is_semantically_idempotent(tmp_path: Path) -> None:
    steam_root = build_fake_steam(tmp_path)
    gateway = SteamFileGateway(steam_root, STEAM_ID)
    first = gateway.stage(orange_box_plan(), tmp_path / "Desktop")
    gateway.apply(first, lambda _prompt: "REPLACE")

    namespace_path = (
        steam_root / "userdata" / ACCOUNT_ID / "config/cloudstorage" / NAMESPACE_NAME
    )
    raw = json.loads(namespace_path.read_text(encoding="utf-8"))
    collection_id = steam_collection_id("valve/the-orange-box")
    key = f"user-collections.{collection_id}"
    entry = next(entry for outer_key, entry in raw if outer_key == key)
    payload = json.loads(entry["value"])
    payload["added"].append(999)
    entry["value"] = json.dumps(payload, separators=(",", ":"))
    namespace_path.write_text(json.dumps(raw, separators=(",", ":")), encoding="utf-8")

    second = gateway.stage(orange_box_plan(), tmp_path / "Desktop")
    candidate = parse_json_strict(
        (second / f"candidate-{NAMESPACE_NAME}").read_bytes(),
        CloudStorageNamespaceFile,
    )
    result = SteamCollectionPayload.from_entry(dict(candidate.root)[key])
    assert result.added == [220, 380, 400, 420, 440, 999]
# end def test_repeat_stage_preserves_manual_apps_and_is_semantically_idempotent


def test_read_collection_returns_static_collection_case_insensitively(tmp_path: Path) -> None:
    steam_root = build_fake_steam(tmp_path)
    gateway = SteamFileGateway(steam_root, STEAM_ID)

    payload = gateway.read_collection("FAVORITES")

    assert payload.id == "favorite"
    assert payload.added == [440]
# end def test_read_collection_returns_static_collection_case_insensitively


def test_read_collection_raises_with_available_names_when_missing(tmp_path: Path) -> None:
    steam_root = build_fake_steam(tmp_path)
    gateway = SteamFileGateway(steam_root, STEAM_ID)

    with pytest.raises(SteamIoError, match="not found locally"):
        gateway.read_collection("manual-all")
    # end with
# end def test_read_collection_raises_with_available_names_when_missing


def test_read_collection_rejects_dynamic_collection(tmp_path: Path) -> None:
    steam_root = build_fake_steam(tmp_path)
    gateway = SteamFileGateway(steam_root, STEAM_ID)

    with pytest.raises(SteamIoError, match="dynamic"):
        gateway.read_collection("Dynamic")
    # end with
# end def test_read_collection_rejects_dynamic_collection


def test_second_replacement_failure_rolls_back_first_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    steam_root = build_fake_steam(tmp_path)
    cloud = steam_root / "userdata" / ACCOUNT_ID / "config/cloudstorage"
    originals = {name: (cloud / name).read_bytes() for name in (NAMESPACE_NAME, MODIFIED_NAME)}
    gateway = SteamFileGateway(steam_root, STEAM_ID)
    staged = gateway.stage(orange_box_plan(), tmp_path / "Desktop")
    original_replace = gateway._atomic_replace
    calls = 0

    def fail_second_replace(target: Path, data: bytes, identity: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated second replacement failure")
        # end if
        original_replace(target, data, identity)  # type: ignore[arg-type]
    # end def fail_second_replace

    monkeypatch.setattr(gateway, "_atomic_replace", fail_second_replace)

    with pytest.raises(SteamIoError, match="rollback attempted"):
        gateway.apply(staged, lambda _prompt: "REPLACE")
    # end with
    assert {name: (cloud / name).read_bytes() for name in originals} == originals
# end def test_second_replacement_failure_rolls_back_first_file
