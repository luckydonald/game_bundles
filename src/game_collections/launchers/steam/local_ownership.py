"""Read-only, local-only Steam ownership approximation via installed games.

Unlike ``api.py`` this never calls the Steam Web API and needs no
``STEAM_WEB_API_KEY``. It can only see games that are currently *installed*,
which is a strict subset of what an account actually owns.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import vdf

from game_collections.launchers.steam.discovery import DuplicateRejectingDict


class SteamLocalOwnershipError(RuntimeError):
    """Local installed-game discovery failed closed."""

# end class SteamLocalOwnershipError


def _load_vdf(path: Path) -> dict[str, Any]:
    try:
        raw: Any = vdf.loads(
            path.read_text(encoding="utf-8"),
            mapper=DuplicateRejectingDict,
            merge_duplicate_keys=False,
        )
    except OSError as error:
        raise SteamLocalOwnershipError(f"could not read {path}: {error}") from error
    except (UnicodeDecodeError, SyntaxError, ValueError) as error:
        raise SteamLocalOwnershipError(f"invalid VDF {path}: {error}") from error
    # end try
    if not isinstance(raw, dict):
        raise SteamLocalOwnershipError(f"unsupported VDF root structure: {path}")
    # end if
    return raw
# end def _load_vdf


def discover_library_folders(steam_root: Path) -> list[Path]:
    """Return every Steam library folder path, including ``steam_root`` itself."""
    path = steam_root / "steamapps/libraryfolders.vdf"
    raw = _load_vdf(path)
    if set(raw) != {"libraryfolders"}:
        raise SteamLocalOwnershipError(f"unsupported libraryfolders.vdf root structure: {path}")
    # end if
    folders = raw["libraryfolders"]
    if not isinstance(folders, dict):
        raise SteamLocalOwnershipError(f"unsupported libraryfolders.vdf entries: {path}")
    # end if
    library_paths: list[Path] = []
    for index, entry in folders.items():
        if not isinstance(entry, dict) or "path" not in entry:
            raise SteamLocalOwnershipError(f"library folder entry {index!r} is missing a path: {path}")
        # end if
        library_path = entry["path"]
        if not isinstance(library_path, str) or not library_path:
            raise SteamLocalOwnershipError(f"library folder entry {index!r} has an invalid path: {path}")
        # end if
        library_paths.append(Path(library_path))
    # end for
    if not library_paths:
        raise SteamLocalOwnershipError(f"no library folders found: {path}")
    # end if
    return library_paths
# end def discover_library_folders


def scan_installed_app_ids(library_folders: list[Path]) -> set[int]:
    """Return every app ID with an installed ``appmanifest_<id>.acf`` across all libraries."""
    app_ids: set[int] = set()
    for library_folder in library_folders:
        steamapps_dir = library_folder / "steamapps"
        if not steamapps_dir.is_dir():
            continue
        # end if
        for manifest_path in sorted(steamapps_dir.glob("appmanifest_*.acf")):
            app_ids.add(_parse_appmanifest(manifest_path))
        # end for
    # end for
    return app_ids
# end def scan_installed_app_ids


def _parse_appmanifest(path: Path) -> int:
    raw = _load_vdf(path)
    if set(raw) != {"AppState"}:
        raise SteamLocalOwnershipError(f"unsupported appmanifest root structure: {path}")
    # end if
    app_state = raw["AppState"]
    if not isinstance(app_state, dict) or "appid" not in app_state:
        raise SteamLocalOwnershipError(f"appmanifest is missing appid: {path}")
    # end if
    try:
        app_id = int(app_state["appid"])
    except (TypeError, ValueError) as error:
        raise SteamLocalOwnershipError(f"appmanifest has an invalid appid: {path}") from error
    # end try
    if app_id <= 0:
        raise SteamLocalOwnershipError(f"appmanifest has a non-positive appid: {path}")
    # end if
    expected_name = f"appmanifest_{app_id}.acf"
    if path.name != expected_name:
        raise SteamLocalOwnershipError(f"appmanifest filename does not match its appid: {path}")
    # end if
    return app_id
# end def _parse_appmanifest


def get_installed_app_ids(steam_root: Path) -> set[int]:
    """Approximate ownership: every app currently installed under ``steam_root``."""
    return scan_installed_app_ids(discover_library_folders(steam_root))
# end def get_installed_app_ids
