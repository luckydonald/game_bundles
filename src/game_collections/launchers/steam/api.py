"""Read-only Steam Web API ownership client."""

from __future__ import annotations

import httpx

from game_collections.launchers.steam.models import GetOwnedGamesResponse


class SteamApiError(RuntimeError):
    """Steam ownership could not be established."""

# end class SteamApiError


class SteamApiClient:
    """Minimal typed client for ``IPlayerService/GetOwnedGames``."""

    endpoint = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/"

    def __init__(self, api_key: str, timeout: float = 20.0) -> None:
        if not api_key:
            raise SteamApiError("STEAM_WEB_API_KEY is required")
        # end if
        self._api_key = api_key
        self._timeout = timeout
    # end def __init__

    def get_owned_games(self, steam_id: str) -> GetOwnedGamesResponse:
        """Fetch and strictly validate the complete ownership response."""
        try:
            response = httpx.get(
                self.endpoint,
                params={
                    "key": self._api_key,
                    "steamid": steam_id,
                    "include_appinfo": "true",
                    "include_played_free_games": "true",
                    "format": "json",
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            result = GetOwnedGamesResponse.model_validate(response.json())
        except (httpx.HTTPError, ValueError) as error:
            raise SteamApiError(f"Steam ownership request failed or changed format: {error}") from error
        # end try
        return result
    # end def get_owned_games

# end class SteamApiClient

