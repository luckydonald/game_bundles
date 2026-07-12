from __future__ import annotations

import json
from pathlib import Path

import pytest

from game_collections.launchers.steam.discovery import account_id_from_steam_id, load_login_users
from game_collections.launchers.steam.models import (
    CloudStorageNamespaceFile,
    CloudStorageNamespacesFile,
    ModifiedKeysFile,
    SteamCollectionPayload,
    parse_json_strict,
)


FIXTURES = Path(__file__).parent / "fixtures/steam"


def test_complete_observed_steam_files_validate(tmp_path: Path) -> None:
    steam_root = tmp_path / "Steam"
    (steam_root / "config").mkdir(parents=True)
    (steam_root / "config/loginusers.vdf").write_bytes((FIXTURES / "loginusers.vdf").read_bytes())

    users = load_login_users(steam_root)
    namespaces = parse_json_strict(
        (FIXTURES / "cloud-storage-namespaces.json").read_bytes(),
        CloudStorageNamespacesFile,
    )
    namespace = parse_json_strict(
        (FIXTURES / "cloud-storage-namespace-1.json").read_bytes(),
        CloudStorageNamespaceFile,
    )
    modified = parse_json_strict(
        (FIXTURES / "cloud-storage-namespace-1.modified.json").read_bytes(),
        ModifiedKeysFile,
    )

    assert users.most_recent_steam_id == "76561198044975919"
    assert account_id_from_steam_id(users.most_recent_steam_id) == 84_710_191
    assert namespaces.version_for(1) == "1534"
    assert modified.root == []
    payloads = [
        SteamCollectionPayload.from_entry(entry)
        for key, entry in namespace.root
        if key.startswith("user-collections.")
    ]
    assert [payload.name for payload in payloads] == ["Favorites", "Dynamic"]
# end def test_complete_observed_steam_files_validate


def test_namespace_schema_drift_fails_closed() -> None:
    raw = json.loads((FIXTURES / "cloud-storage-namespace-1.json").read_text(encoding="utf-8"))
    raw[0][1]["new_steam_field"] = True

    with pytest.raises(ValueError, match="new_steam_field"):
        CloudStorageNamespaceFile.model_validate(raw)
    # end with
# end def test_namespace_schema_drift_fails_closed


def test_duplicate_json_keys_fail_closed() -> None:
    with pytest.raises(ValueError, match="duplicate JSON object key"):
        parse_json_strict(b'[["x", {"key":"x", "key":"y"}]]', CloudStorageNamespaceFile)
    # end with
# end def test_duplicate_json_keys_fail_closed


def test_filter_format_version_drift_fails_closed() -> None:
    raw = json.loads((FIXTURES / "cloud-storage-namespace-1.json").read_text(encoding="utf-8"))
    entry = raw[2][1]
    payload = json.loads(entry["value"])
    payload["filterSpec"]["nFormatVersion"] = 3
    entry["value"] = json.dumps(payload)
    namespace = CloudStorageNamespaceFile.model_validate(raw)

    with pytest.raises(ValueError, match="nFormatVersion"):
        SteamCollectionPayload.from_entry(namespace.root[2][1])
    # end with
# end def test_filter_format_version_drift_fails_closed

