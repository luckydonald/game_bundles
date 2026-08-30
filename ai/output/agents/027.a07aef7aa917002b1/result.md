Now I have everything needed to write a concise fact-focused report.

## Findings

### 1. `local_ownership.py` (`--source installed`)

File: `src/game_collections/launchers/steam/local_ownership.py`

- `discover_library_folders()` (lines 43-69) parses `steamapps/libraryfolders.vdf` for library paths.
- `scan_installed_app_ids()` (lines 72-85) globs every `steamapps/appmanifest_*.acf` under each library and calls `_parse_appmanifest()` on each.
- `_parse_appmanifest()` (lines 88-110) reads only the `AppState.appid` field, requires `set(raw) == {"AppState"}`, validates the id is a positive int matching the filename, and returns it. **No other `AppState` fields are read** (no `UserConfig`, no name, no "type" indicator).
- Result: `get_installed_app_ids()` (lines 113-116) returns a flat `set[int]` of every appid with an on-disk manifest — installed base games and installed DLC are indistinguishable in this set. Steam does create an `appmanifest_<dlc_appid>.acf` for many DLC ("Depots" typically list under a shared install dir), so a DLC appid can already appear in this set if Steam has downloaded/registered it, but the code neither detects nor special-cases that fact — it's a side effect of scanning by filename only.
- No `grep -i dlc` hits anywhere in `launchers/steam/` (adapter.py, api.py, discovery.py, io.py, local_ownership.py, models.py) — confirmed empty.

### 2. Steam Web API ownership source

File: `src/game_collections/launchers/steam/api.py` (`SteamApiClient`, lines 16-51)
- Calls `GET https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/` with `include_appinfo=true`, `include_played_free_games=true`.
- Response parsed via `GetOwnedGamesResponse` (models.py, `response.games: list[OwnedGame]`).

`src/game_collections/launchers/steam/adapter.py`, `owned_app_ids_from_api()` (lines 84-91):
```python
def source() -> set[int]:
    owned_response = api_client.get_owned_games(steam_id)
    return {game.appid for game in owned_response.response.games}
```
Just flattens `response.games[].appid` into a set. `GetOwnedGames` is Valve's documented endpoint for the account's owned **base products** (games/apps a license unlocks) — per Steam's own API semantics, `games` here does **not** separately enumerate owned DLC as distinct rows in the way base games are listed; DLC ownership is usually reflected only via the `dlc` sub-array of `GetOwnedGames`'s undocumented but sometimes-present extended fields (not requested/parsed here) or via app-details lookups, not the base `games` list used here. There is no code comment in this repo asserting this either way, and no field in `OwnedGame` (models.py lines 236-253) for DLC — the model only has appid/name/playtime/etc. This is a documented Steam Web API limitation, not something addressed in-repo.

### 3. `models.py` — DLC/parent-app fields

`src/game_collections/launchers/steam/models.py`: no `dlc`, `parent`, `fullgame`, `requires`, or similar fields anywhere. `OwnedGame` fields (lines 239-251): `appid, name, playtime_2weeks, playtime_forever, img_icon_url, has_community_visible_stats, playtime_windows_forever, playtime_mac_forever, playtime_linux_forever, playtime_deck_forever, rtime_last_played, content_descriptorids, playtime_disconnected`. No DLC-related modeling anywhere in the file (confirmed by the earlier `grep -i dlc` returning nothing in this dir).

### 4. Steam Store API / SteamDB usage

`src/game_collections/sources/humblebundle/steamdb.py` — a browser-based scraper of steamdb.info's *search* page only (not app-details API). It fetches `https://steamdb.info/search/?q={query}` and parses result rows for `(id, title)` pairs, distinguishing only **App** vs **Bundle** result rows via the href pattern `^/(app|bundle)/(\d+)/$` (lines 39, 144-154). Comment at lines 121-129 explicitly notes DLC rows exist in search results (marked with `<i class="stype">DLC</i>`) but are **not specially parsed or filtered out** — a DLC's search row would be treated exactly like a normal "app" row and returned as a plain numeric appid, with no `is_dlc`/`fullgame` field captured. There is no Steam Store `appdetails` API call anywhere in the codebase (`grep` for `dlc` across all of `src/` returns only these two files plus `completion.py`/`storefronts.py` bundle-comment hits — no `appdetails`/`fullgame` usage found).

`src/game_collections/sources/storefronts.py` `parse_store_identity()` (lines 58-128): only handles Steam **bundle** URLs specially (`steam:bundle/<id>`, lines 90-95, with an explicit comment that a Deluxe-Edition-only-sold-as-bundle "of the base app + DLC" has no single AppID). No DLC-specific parsing branch exists (only `app/<id>` and `bundle/<id>` regexes).

### 5. Ownership-matched computation (`apply/metadata.py`, `launchers/base.py`, `completion.py`)

- `apply/metadata.py` does **not** compute ownership at all — it's purely display metadata (source/bundle_kind/date/tier/name) derived from `list_id` and `GameList`, no ownership logic.
- `launchers/base.py` defines the neutral `LauncherAdapter`/`CollectionEligibility`/`SyncPlan` contract only; no appid-specific logic.
- Actual ownership matching lives in `src/game_collections/completion.py`, `evaluate_completion()` (lines 29-98):
  - For each `Game`, collects its `steam` provider `qualified_ids`, skips any `bundle/` value (line 47-52), else parses the numeric appid (lines 54-62).
  - Ownership check is a **simple set-membership test**: `any(app_id in owned_app_ids for app_id in game_app_ids)` (line 67) and `missing = sorted(set(required) - owned_app_ids)` / `owned = sorted(set(required) & owned_app_ids)` (lines 85-86).
  - This is provider-agnostic to whether an appid is a base game or DLC — **a DLC appid would be checked and matched identically to a base-game appid today** (plain int membership in the `owned_app_ids` set), since nothing in `evaluate_completion`, `SteamAdapter.evaluate()` (adapter.py lines 135-198, which just calls `evaluate_completion` with the flat `owned_app_ids` set), or the three `OwnedAppIdsSource` implementations (`owned_app_ids_from_api`, `owned_app_ids_from_installed`, `owned_app_ids_from_collection` — adapter.py lines 84-109) distinguishes appid "kind" in any way.

### Summary of gaps relative to a DLC feature

- No source currently determines whether a given Steam appid *is* a DLC, nor what its parent/base-game appid is (no `fullgame`/`parent`/`requires` concept anywhere in the repo).
- `installed` source: DLC appid ownership is only incidentally detectable if Steam happens to write an `appmanifest_<dlc_id>.acf` for it; the code doesn't know or care it's DLC.
- `web` source (`GetOwnedGames`): only requests/parses the `games` array of `OwnedGame`; does not request or model Valve's separate `dlc` field, so DLC ownership via this path is not guaranteed to be exposed at all today.
- `collection` source (`owned_app_ids_from_collection`, adapter.py lines 103-109): reads a manually curated local Steam collection's `added` appid list — purely whatever ids a human put there, so it would "work" for a DLC appid the same as any other, with zero special handling.
- Ownership matching (`evaluate_completion`) treats every steam appid as an opaque int; a DLC appid entered in a game's `ids:` would simply be checked for set membership like any base game today, with no base-game-dependency validation or enforcement anywhere in the codebase.