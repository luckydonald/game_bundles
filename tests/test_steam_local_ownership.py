from __future__ import annotations

from pathlib import Path

import pytest

from game_collections.launchers.steam.local_ownership import (
    SteamLocalOwnershipError,
    discover_library_folders,
    get_installed_app_ids,
    scan_installed_app_ids,
)


LIBRARYFOLDERS_TEMPLATE = """"libraryfolders"
{{
{entries}
}}
"""

LIBRARY_ENTRY_TEMPLATE = """\t"{index}"
\t{{
\t\t"path"\t\t"{path}"
\t\t"label"\t\t""
\t\t"apps"
\t\t{{
\t\t}}
\t}}
"""

APPMANIFEST_TEMPLATE = """"AppState"
{{
\t"appid"\t\t"{app_id}"
\t"name"\t\t"Fake Game {app_id}"
}}
"""


def _write_libraryfolders(steam_root: Path, library_paths: list[Path]) -> None:
    entries = "\n".join(
        LIBRARY_ENTRY_TEMPLATE.format(index=index, path=str(path))
        for index, path in enumerate(library_paths)
    )
    steamapps = steam_root / "steamapps"
    steamapps.mkdir(parents=True, exist_ok=True)
    (steamapps / "libraryfolders.vdf").write_text(
        LIBRARYFOLDERS_TEMPLATE.format(entries=entries), encoding="utf-8"
    )
# end def _write_libraryfolders


def _write_appmanifest(library_path: Path, app_id: int) -> None:
    steamapps = library_path / "steamapps"
    steamapps.mkdir(parents=True, exist_ok=True)
    (steamapps / f"appmanifest_{app_id}.acf").write_text(
        APPMANIFEST_TEMPLATE.format(app_id=app_id), encoding="utf-8"
    )
# end def _write_appmanifest


def test_discover_library_folders_includes_steam_root(tmp_path: Path) -> None:
    steam_root = tmp_path / "Steam"
    other_library = tmp_path / "OtherLibrary"
    _write_libraryfolders(steam_root, [steam_root, other_library])

    result = discover_library_folders(steam_root)

    assert result == [steam_root, other_library]
# end def test_discover_library_folders_includes_steam_root


def test_scan_installed_app_ids_across_multiple_libraries(tmp_path: Path) -> None:
    steam_root = tmp_path / "Steam"
    other_library = tmp_path / "OtherLibrary"
    _write_libraryfolders(steam_root, [steam_root, other_library])
    _write_appmanifest(steam_root, 220)
    _write_appmanifest(other_library, 440)

    app_ids = get_installed_app_ids(steam_root)

    assert app_ids == {220, 440}
# end def test_scan_installed_app_ids_across_multiple_libraries


def test_scan_installed_app_ids_deduplicates_same_app_across_libraries(tmp_path: Path) -> None:
    steam_root = tmp_path / "Steam"
    other_library = tmp_path / "OtherLibrary"
    _write_appmanifest(steam_root, 220)
    _write_appmanifest(other_library, 220)

    app_ids = scan_installed_app_ids([steam_root, other_library])

    assert app_ids == {220}
# end def test_scan_installed_app_ids_deduplicates_same_app_across_libraries


def test_missing_libraryfolders_raises(tmp_path: Path) -> None:
    steam_root = tmp_path / "Steam"
    steam_root.mkdir()

    with pytest.raises(SteamLocalOwnershipError):
        discover_library_folders(steam_root)
    # end with
# end def test_missing_libraryfolders_raises


def test_appmanifest_missing_appid_raises(tmp_path: Path) -> None:
    steam_root = tmp_path / "Steam"
    steamapps = steam_root / "steamapps"
    steamapps.mkdir(parents=True)
    (steamapps / "appmanifest_220.acf").write_text('"AppState"\n{\n\t"name"\t\t"Half-Life 2"\n}\n', encoding="utf-8")

    with pytest.raises(SteamLocalOwnershipError):
        scan_installed_app_ids([steam_root])
    # end with
# end def test_appmanifest_missing_appid_raises


def test_appmanifest_filename_mismatch_raises(tmp_path: Path) -> None:
    steam_root = tmp_path / "Steam"
    steamapps = steam_root / "steamapps"
    steamapps.mkdir(parents=True)
    (steamapps / "appmanifest_220.acf").write_text(APPMANIFEST_TEMPLATE.format(app_id=999), encoding="utf-8")

    with pytest.raises(SteamLocalOwnershipError):
        scan_installed_app_ids([steam_root])
    # end with
# end def test_appmanifest_filename_mismatch_raises
