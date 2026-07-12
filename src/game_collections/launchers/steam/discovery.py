"""Read-only discovery of a Steam installation and active account."""

from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Any

import vdf

from game_collections.launchers.steam.models import LoginUsersFile


STEAM_ID64_ACCOUNT_OFFSET = 76_561_197_960_265_728


class SteamDiscoveryError(RuntimeError):
    """Steam installation or account discovery failed closed."""

# end class SteamDiscoveryError


def default_steam_roots() -> tuple[Path, ...]:
    """Return platform-standard Steam installation roots in priority order."""
    home = Path.home()
    system = platform.system()
    if system == "Linux":
        return (home / ".local/share/Steam", home / ".steam/steam")
    # end if
    if system == "Darwin":
        return (home / "Library/Application Support/Steam",)
    # end if
    if system == "Windows":
        program_files = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
        return (program_files / "Steam",)
    # end if
    return ()
# end def default_steam_roots


def discover_steam_root(override: Path | None = None) -> Path:
    """Find exactly one real Steam root."""
    candidates = (override,) if override else default_steam_roots()
    resolved: list[Path] = []
    for candidate in candidates:
        if candidate is None or not candidate.exists():
            continue
        # end if
        current = candidate.resolve(strict=True)
        if current not in resolved:
            resolved.append(current)
        # end if
    # end for
    if len(resolved) != 1:
        raise SteamDiscoveryError(f"expected exactly one Steam root, found: {resolved}")
    # end if
    return resolved[0]
# end def discover_steam_root


def load_login_users(steam_root: Path) -> LoginUsersFile:
    """Parse VDF structurally, then enforce the complete Pydantic model."""
    path = steam_root / "config/loginusers.vdf"
    try:
        raw: Any = vdf.loads(path.read_text(encoding="utf-8"), mapper=dict)
    except (OSError, ValueError) as error:
        raise SteamDiscoveryError(f"could not parse {path}: {error}") from error
    # end try
    if not isinstance(raw, dict) or set(raw) != {"users"}:
        raise SteamDiscoveryError(f"unsupported loginusers.vdf root structure: {path}")
    # end if
    return LoginUsersFile.model_validate(raw["users"])
# end def load_login_users


def account_id_from_steam_id(steam_id: str) -> int:
    """Convert SteamID64 to the account ID used for userdata directories."""
    account_id = int(steam_id) - STEAM_ID64_ACCOUNT_OFFSET
    if account_id <= 0 or account_id > 0xFFFF_FFFF:
        raise SteamDiscoveryError(f"invalid individual SteamID64: {steam_id}")
    # end if
    return account_id
# end def account_id_from_steam_id

