I have completed the read-only exploration. This is not a plan-mode task (no code change requested), so I'll deliver the findings report directly as requested.

## Report: Steam ownership, collections, and CLI in `game_collections`

### 1. Fetching owned games via the Steam Web API

**`/home/user/git/luckydonald/game_collections/src/game_collections/launchers/steam/api.py`**
- `SteamApiError` (line 10) — raised on any failure.
- `SteamApiClient` (line 16):
  - `endpoint = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/"` (line 19)
  - `__init__(self, api_key: str, timeout: float = 20.0)` (line 21) — raises `SteamApiError("STEAM_WEB_API_KEY is required")` if `api_key` falsy (line 22-24).
  - `get_owned_games(self, steam_id: str) -> GetOwnedGamesResponse` (line 29) — calls `httpx.get` with params `key`, `steamid`, `include_appinfo=true`, `include_played_free_games=true`, `format=json` (lines 32-41); validates via `GetOwnedGamesResponse.model_validate(response.json())` (line 44); wraps `httpx.HTTPError`/`ValueError` into `SteamApiError` (lines 45-46).

**`/home/user/git/luckydonald/game_collections/src/game_collections/launchers/steam/adapter.py`**
- `owned_app_ids_from_api(api_client, steam_id) -> OwnedAppIdsSource` (line 38) — closure `source()` (line 40) calls `api_client.get_owned_games(steam_id)` and returns `{game.appid for game in owned_response.response.games}` (line 42). This is the seam used to turn the API client into a plain callable.
- `owned_app_ids_from_installed(steam_root)` (line 48) is the local-only fallback (`--source installed`), delegating to `get_installed_app_ids` in `local_ownership.py`.
- `SteamAdapter.__init__` (line 62-78): if no explicit `owned_app_ids_source` is passed, it requires `options.api_key` (raises `ValueError` otherwise, line 72-74) and builds `owned_app_ids_from_api(SteamApiClient(options.api_key), options.steam_id)` (line 75).
- `SteamAdapter.evaluate` (line 80) calls `self.owned_app_ids_source()` once (line 81) then diffs each game list's Steam app IDs (`game.qualified_ids` filtered by `provider == "steam"`, lines 87-102) against the owned set to build `CollectionEligibility` per list (missing/owned/unsupported, lines 104-115).
- `SteamAdapter.plan` (line 120) turns eligible results into `PlannedCollectionChange` objects (lines 122-131) and returns a `SyncPlan` (lines 132-137).

### 2. How Steam collections are represented/read internally

**Data model — `/home/user/git/luckydonald/game_collections/src/game_collections/launchers/steam/models.py`**

- `CloudStorageEntry` (line 92) — one raw cloud-config KV entry as stored in `cloud-storage-namespace-1.json`:
  - `key: NonEmptyStrictString`
  - `timestamp: StrictInt` (`> 0`)
  - `value: StrictStr | None`
  - `is_deleted: StrictBool | None`
  - `version: StrictStr | None`
  - `conflictResolutionMethod: Literal["last-write","custom","initial"] | None`
  - `strMethodId: StrictStr | None`
  - Validator (lines 103-119) enforces exactly one of `value`/`is_deleted=True` present, and that `strMethodId` only appears together with `conflictResolutionMethod == "custom"`.
- `CloudStorageNamespaceFile` = `RootModel[list[tuple[StrictStr, CloudStorageEntry]]]` (line 125) — the full `cloud-storage-namespace-1.json` file: an **ordered list of `(key, entry)` pairs** (not a dict — order/duplicates matter), validated for unique outer keys matching `entry.key` (lines 128-141). Helper `.as_dict()` (line 143).
- `SteamFilterGroup` / `SteamFilterSpec` (lines 164-181) — the dynamic-collection filter format (format version 2 only supported).
- **`SteamCollectionPayload`** (line 184) — the *decoded* collection JSON that lives inside a `CloudStorageEntry.value` whose key starts with `user-collections.`:
  ```
  id: NonEmptyStrictString
  name: NonEmptyStrictString
  added: list[StrictInt]
  removed: list[StrictInt]
  filterSpec: SteamFilterSpec | None = None
  ```
  - Validator (`validate_apps`, lines 193-205): app IDs must be positive, `added`/`removed` must be internally unique, and `added`/`removed` sets must be disjoint.
  - Classmethod `from_entry(cls, entry: CloudStorageEntry) -> Self` (line 207-218) is the sole decode path: rejects deleted entries, JSON-parses `entry.value` with `_reject_duplicate_object_keys` (line 213), then `model_validate`s it.
- `OwnedGame` / `OwnedGamesPayload` / `GetOwnedGamesResponse` (lines 223-269) — the Web-API response models (separate from collections).
- `parse_json_strict` (line 284) — generic strict JSON decode + duplicate-key rejection + `model.model_validate`, used for `CloudStorageNamespaceFile`, `CloudStorageNamespacesFile`, `ModifiedKeysFile`.

**Reading collections from local Steam config — `/home/user/git/luckydonald/game_collections/src/game_collections/launchers/steam/io.py`**

- `SteamFileGateway` (line 127) is explicitly documented as **"the sole code path allowed to read or replace Steam configuration files"** (line 128). It resolves paths for `login`, `namespaces`, `namespace` (`cloud-storage-namespace-1.json`), `modified` (`cloud-storage-namespace-1.modified.json`) under `<steam_root>/userdata/<account_id>/config/cloudstorage/` (lines 138-143; `NAMESPACE_NAME`/`MODIFIED_NAME` constants at lines 35-36).
- `SteamFileGateway.load_snapshot()` (line 165) — reads all four files via locked reads (`_read_locked`, line 486) and parses them (`parse_login_users`, `parse_json_strict(..., CloudStorageNamespaceFile)` etc., lines 172-175), then calls `_validate_snapshot` (line 176).
- `_validate_snapshot` (line 448) — for every `(key, entry)` in the namespace where `key.startswith("user-collections.")` and `not entry.is_deleted`, it calls `SteamCollectionPayload.from_entry(entry)` (lines 462-466) to prove every stored collection decodes successfully. This is effectively **"how collections are read"** — there's no separate `Collection` class; a collection *is* a `SteamCollectionPayload` decoded on demand from a `CloudStorageEntry` found under the `user-collections.<id>` namespace key.
- `_build_candidates` (line 383) is where existing collections are enumerated and indexed:
  - Loops `entries` skipping non-`user-collections.` keys and deleted entries (lines 392-395).
  - `payloads[payload.id] = payload` — keyed by collection **id** (line 397).
  - `names[payload.name.casefold()] = payload.id` — a **case-insensitive name → id index** (line 398), used later for collision detection (line 410-413: raises `SteamIoError` if a *different* collection already owns that name).
  - Requires `entry_map.get("collection-bootstrap-complete").value == "true"` (lines 400-403) — Steam's bootstrap marker key, fail-closed otherwise.
  - For each `PlannedCollectionChange` in the sync plan: computes `collection_id = steam_collection_id(change.list_id)` (line 407), looks up any `existing` payload by that id, refuses to touch it if it has become a dynamic collection (`existing.filterSpec is not None`, lines 414-416), unions `added`/subtracts `removed` against the existing app-id set (lines 417-419), and writes back a new `SteamCollectionPayload` + `CloudStorageEntry` with `conflictResolutionMethod="custom"`, `strMethodId="union-collections"` (lines 420-432).
- `steam_collection_id(list_id: str) -> str` (line 694) — derives the stable Steam collection id from a **logical list id** (not the display name): `sha256(list_id)[:9]` base64-encoded with custom escaping, prefixed `uc-` (lines 696-698). E.g. `steam_collection_id("valve/the-orange-box")` in tests (`test_steam_io.py:78`).
- `_validate_candidate_pair` (line 469) re-validates every non-deleted `user-collections.` entry after building candidates and asserts `key == f"user-collections.{payload.id}"` (lines 476-481).

### 3. Is there a literal `all` collection?

No. There is **no special-cased `"all"` collection anywhere in this codebase.** Only two collection-id conventions appear:
- Steam's own built-in collections use fixed short ids without the `uc-` prefix — the test fixture shows `"favorite"` (Favorites) as an example (`/home/user/git/luckydonald/game_collections/tests/fixtures/steam/cloud-storage-namespace-1.json`, `user-collections.favorite`).
- User/managed collections created by this tool always get an id of the form `uc-<base64(sha256(list_id)[:9])>` via `steam_collection_id()` (io.py:694-699), keyed by the **logical `list_id`** (e.g. `"valve/the-orange-box"`), not by name.

Name lookups only exist for **collision detection** (`names[payload.name.casefold()] = payload.id`, io.py:398) — i.e., matching an *existing* Steam collection by its display name to prevent creating two differently-keyed collections with the same visible name. There's no code anywhere that treats an id or name literally equal to `"all"` specially, and no `"manual-all"`-style naming convention exists in the repo (grep across `src/` and `tests/` for `all`, `manual-all`, `ALL_LIST`, `virtual`, `all_games` returned nothing relevant beyond ordinary English words like "gallery"/"call").

### 4. Typer CLI definitions — `/home/user/git/luckydonald/game_collections/src/game_collections/cli.py`

Shared helper `_steam_adapter` (line 656-685):
```python
def _steam_adapter(
    steam_root: Path | None,
    steam_id: str | None,
    api_key: str | None,
    source: str = "api",
) -> tuple[SteamAdapter, SteamFileGateway]:
```
- Validates `source in ("api", "installed")` (line 662).
- `root = discover_steam_root(steam_root)` (665), `gateway = SteamFileGateway.discover(root, steam_id)` (666).
- If `source == "installed"`: warns to stderr, uses `owned_app_ids_from_installed(root)`, builds `SteamOptions` **without** `api_key` (lines 667-674).
- Else (`api`, default): `key = api_key or os.environ.get("STEAM_WEB_API_KEY")` (line 676); raises `ValueError("provide --api-key or STEAM_WEB_API_KEY (or use --source installed)")` if absent (677-679); builds `SteamOptions(..., api_key=key)` and `owned_app_ids_from_api(SteamApiClient(key), options.steam_id)` (680-681).
- Constructs `SteamAdapter(options, owned_app_ids_source=owned_app_ids_source, gateway=gateway)` (683).

`eligible steam` command (line 708-730):
```python
@app.command("eligible")
def eligible_command(
    launcher: Annotated[str, typer.Argument()] = "steam",
    lists_root: Annotated[Path | None, typer.Option("--lists-root")] = None,
    steam_root: Annotated[Path | None, typer.Option("--steam-root")] = None,
    steam_id: Annotated[str | None, typer.Option("--steam-id")] = None,
    api_key: Annotated[str | None, typer.Option("--api-key", hide_input=True)] = None,
    source: Annotated[str, typer.Option("--source", help="api (Web API, needs a key) or installed (local-only approximation)")] = "api",
) -> None:
```
Rejects any `launcher != "steam"` (718-721), calls `_steam_adapter(...)` then `adapter.plan(...)` then `_print_plan(plan)` (722-725).

`sync steam` command (line 733-777) has the identical option set plus `--apply` (bool, line 736) and `--output-dir` (line 737). Dry-run by default (line 753-756); when `--apply`, stages via `adapter.stage(...)` (757), prints inspection paths, requires interactive `typer.confirm` (765) and then a typed `"REPLACE"` confirmation inside `adapter.apply(...)` (769) before touching Steam files.

`restore steam <staged_dir>` command (line 780-801) takes `--steam-root`/`--steam-id` only (no `--api-key`/`--source`, since restore never touches ownership).

The `--api-key` option is defined identically in both `eligible_command` (line 714) and `sync_command` (line 741): `typer.Option("--api-key", hide_input=True)`, optional `str | None`, defaulting to `None` and falling back to `STEAM_WEB_API_KEY` env var inside `_steam_adapter`.

### 5. Existing tests related to owned-games source / collections

- **`/home/user/git/luckydonald/game_collections/tests/test_steam_adapter.py`** (63 lines) — tests `SteamAdapter.evaluate` against a fake `owned_app_ids_source` callable (lines 22-24, 27-52); tests that constructing `SteamAdapter` without a source and without `api_key` raises `ValueError` containing `"owned_app_ids_source"` (lines 55-63). No test currently exercises `owned_app_ids_from_api` against a live/mocked HTTP call — that's only exercised indirectly via the plain-callable seam.
- **`/home/user/git/luckydonald/game_collections/tests/test_steam_io.py`** (222 lines) — the most relevant collection tests:
  - `build_fake_steam` (line 29) builds a fixture Steam root using `tests/fixtures/steam/*` (loginusers.vdf, cloud-storage-namespaces.json, `cloud-storage-namespace-1.json`, `.modified.json`).
  - `orange_box_plan()` (line 42) builds a `SyncPlan` with one `PlannedCollectionChange(list_id="valve/the-orange-box", name="The Orange Box", ...)`.
  - `test_stage_creates_inspectable_candidates_without_touching_steam` (59) — asserts staged candidate collection payload decodes via `SteamCollectionPayload.from_entry` under key `user-collections.{steam_collection_id(list_id)}`.
  - `test_orange_box_generation_matches_expected_files` (87) — golden-file comparison against `tests/fixtures/steam/expected-orange-box-cloud-storage-namespace-1(.modified).json`.
  - `test_repeat_stage_preserves_manual_apps_and_is_semantically_idempotent` (167) — proves manually-added app IDs in an existing collection are preserved/unioned on re-stage.
  - Various failure-path tests: confirmation decline, tampered candidate hash, source changed after staging, active Steam pipe, rollback on partial failure.
- **`/home/user/git/luckydonald/game_collections/tests/test_steam_models.py`** (103 lines) — model-level validation tests (not read in full above, but by name covers `SteamCollectionPayload`/`CloudStorageEntry` validators).
- **`/home/user/git/luckydonald/game_collections/tests/test_steam_local_ownership.py`** (128 lines) — tests `get_installed_app_ids`, `discover_library_folders`, `scan_installed_app_ids`, `_parse_appmanifest` (the `--source installed` fallback path, no API key involved).
- No test file directly hits `SteamApiClient`/`api.py` with a mocked `httpx` response, and no test references any `"all"`-named collection.

### Summary answers to your specific bullets

- **Owned-games fetch function**: `SteamApiClient.get_owned_games` (`api.py:29`), wrapped by `owned_app_ids_from_api` (`adapter.py:38`).
- **Local collection reader**: `SteamFileGateway.load_snapshot`/`_validate_snapshot` (`io.py:165`, `io.py:448`), decoding via `SteamCollectionPayload.from_entry` (`models.py:207`).
- **Typer command definitions**: `eligible_command` (`cli.py:709`), `sync_command` (`cli.py:734`), both sharing `--api-key` (`cli.py:714`, `cli.py:741`) and `_steam_adapter` (`cli.py:656`).
- **Collection schema**: `SteamCollectionPayload` (`models.py:184`) — `id`, `name`, `added: list[int]`, `removed: list[int]`, optional `filterSpec`.
- **Keying by name**: collections are keyed by `id` (derived from `list_id` via `steam_collection_id`, `io.py:694`), not by name; name is only used case-insensitively for collision checks (`io.py:398,410`). There is no literal `"all"` collection or `"manual-all"` naming convention in this codebase.