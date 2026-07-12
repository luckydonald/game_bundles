# Local installed-games fallback for Steam ownership (no Web API key)

## Context

User asked whether `STEAM_WEB_API_KEY` or full game-ownership data can be read from local Steam client files instead of calling the `GetOwnedGames` Web API (currently the only ownership source, see `src/game_collections/launchers/steam/api.py` and `adapter.py`).

Research finding (Explore agent, high confidence on the parts that matter):
- `STEAM_WEB_API_KEY` itself is **never** locally derivable — it's a developer secret issued through Valve's web dev portal, unrelated to any client-side file.
- No local file gives a reliable **full owned/licensed** games list. `appcache/appinfo.vdf` and `appcache/packageinfo.vdf` are Valve's **binary** VDF format (not the text `vdf` package this repo already uses) and don't cleanly expose per-account license ownership either way.
- What IS reliably available locally, in plain-text VDF/ACF (parseable with the existing `vdf` package, same as `loginusers.vdf`):
  - `steamapps/libraryfolders.vdf` — every Steam library folder path (root install dir counts as one).
  - `<library>/steamapps/appmanifest_<appid>.acf` — one per **installed** app, with an `AppState.appid` field.
  - Together these give the set of **installed app IDs** — a real but partial proxy for ownership (misses owned-but-never-installed games; on a shared machine also includes games installed by other local accounts).

Outcome: add a second, explicit, local-only ownership source ("installed games") alongside the existing Web API source, so `eligible`/`sync` can run without `STEAM_WEB_API_KEY` when the user accepts the "installed" approximation. Never silently substitute one for the other — this must be an explicit opt-in, and clearly labeled as an approximation everywhere it surfaces (CLI, docs).

## Design

Introduce a small ownership-source seam in the Steam adapter rather than hardcoding the Web API call:

1. **`src/game_collections/launchers/steam/local_ownership.py` (new)**
   - `discover_library_folders(steam_root: Path) -> list[Path]`: parse `steamapps/libraryfolders.vdf` with `vdf.loads` (reuse the `DuplicateRejectingDict` mapper pattern from `discovery.py`), return validated absolute paths (steam_root itself + each `path` entry).
   - `scan_installed_app_ids(library_folders: list[Path]) -> set[int]`: glob each library's `steamapps/appmanifest_*.acf`, parse each with `vdf.loads`, require an `AppState` root and integer `appid` key (strict — raise on malformed manifests, consistent with "treat unknown external fields and format changes as errors" from CLAUDE.md), return the app ID set.
   - Add a matching strict Pydantic model (e.g. `AppManifestFile` in `models.py`) if validation needs more than the bare int, following the existing `LoginUsersFile` pattern.

2. **`src/game_collections/launchers/steam/adapter.py`**
   - Define a tiny `Protocol`/callable seam, e.g. `OwnedAppIdsSource = Callable[[], set[int]]`, instead of hardcoding `self.api_client.get_owned_games(...)` in `evaluate()`.
   - `SteamApiClient.get_owned_games` stays as-is; wrap it in a small adapter closure/class that returns `{game.appid for game in ...}` for the Web-API source.
   - New `SteamLocalInstalledSource` (or plain function) wraps `discover_library_folders` + `scan_installed_app_ids` for the local source.
   - `SteamAdapter.__init__` takes this source instead of constructing `SteamApiClient` directly when none is given; `SteamOptions.api_key` becomes `str | None` (only required for the Web API source).
   - `evaluate()` calls `self.owned_app_ids_source()` instead of the direct API call — rest of the eligibility logic (missing/owned/unsupported) is unchanged.

3. **`src/game_collections/cli.py`**
   - Add `--source {api,installed}` (default `api`, matching current behavior) to `eligible` and `sync`.
   - `_steam_adapter(...)` gains a `source: str` param: for `"api"`, keep today's required-key path unchanged; for `"installed"`, skip the API-key requirement entirely and build the local source from the discovered `steam_root`.
   - Print a one-line caveat when `source == "installed"` (e.g. "installed-only approximation; owned-but-uninstalled games will show as missing").

4. **Docs**: update root `README.md` (and `lists/README.md` if it documents `sync`/`eligible` flags) to describe `--source installed` as an approximation, and note explicitly that `STEAM_WEB_API_KEY` cannot be obtained from local files under any circumstance.

## Out of scope

- No binary-VDF parsing (`appinfo.vdf`/`packageinfo.vdf`) — format risk and incomplete-ownership-mapping risk aren't worth it for an approximation feature.
- No automatic/silent fallback from `api` to `installed` on missing key — must stay an explicit user choice.
- No changes to `restore steam` or `SteamFileGateway` — this only affects how owned app IDs are computed, not file staging/apply.

## Verification

- `tests/test_steam_adapter.py`: extend with a fixture Steam root containing `steamapps/libraryfolders.vdf` + a couple of `appmanifest_*.acf` files; assert `evaluate()`/`plan()` produce the same shape of `CollectionEligibility` as the API-backed path, using the local source directly (no network).
- Add a focused `local_ownership` test module covering: multiple library folders, malformed/missing `AppState.appid` (must raise), duplicate app IDs across libraries (dedupe via `set`).
- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_steam_adapter.py -q` and any new test file.
- Manual smoke: `game-collections eligible steam --source installed --steam-root <real ~/.local/share/Steam>` against the user's real Steam install (read-only, no `--apply` involved) to confirm library/appmanifest parsing works against a live install layout.
