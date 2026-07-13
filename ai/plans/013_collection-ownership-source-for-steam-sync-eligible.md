# `--collection` ownership source for Steam sync/eligible

## Context

Ownership lookup today has two modes: `--source api` (Web API + `STEAM_WEB_API_KEY`) and `--source installed` (scan locally installed appmanifests, misses owned-but-uninstalled games). The user has created a manually-curated Steam collection (`manual-all`) that they drag every owned game into, so it holds the true full ownership list without needing an API key. We're adding a third source that reads that collection straight out of Steam's local cloud-storage config, using it as an alternative "ground truth" for ownership — same purpose as `api`/`installed`, just backed by a manually maintained local collection instead.

Note (from exploration): Steam's built-in "All Games" view is *not* a stored `user-collections.*` entry — it's computed by the client, so it can't be read this way. That's why this feature relies on the user's own manually created static collection instead.

## Design

### `io.py` — read a named local collection

Add `SteamFileGateway.read_collection(name: str) -> SteamCollectionPayload`, reusing the exact iteration pattern already in `_build_candidates` (`io.py:388-398`) for decoding `user-collections.*` entries and indexing by `payload.name.casefold()`:

```python
def read_collection(self, name: str) -> SteamCollectionPayload:
    """Read a single named local Steam collection (case-insensitive) for use as an ownership source."""
    snapshot = self.load_snapshot()
    by_name: dict[str, SteamCollectionPayload] = {}
    for key, entry in snapshot.namespace.root:
        if not key.startswith("user-collections.") or entry.is_deleted:
            continue
        # end if
        payload = SteamCollectionPayload.from_entry(entry)
        by_name[payload.name.casefold()] = payload
    # end for
    match = by_name.get(name.casefold())
    if match is None:
        available = ", ".join(sorted(p.name for p in by_name.values())) or "(none found locally)"
        raise SteamIoError(
            f"Steam collection {name!r} not found locally; available collections: {available}.\n"
            f"{MANUAL_COLLECTION_HINT}"
        )
    # end if
    if match.filterSpec is not None:
        raise SteamIoError(
            f"Steam collection {name!r} is a dynamic (filter-based) collection; "
            "only a manually curated (static) collection can be used as an ownership source"
        )
    # end if
    return match
# end def read_collection
```

Add a module-level `MANUAL_COLLECTION_HINT` string constant with the exact creation steps the user gave (library → select all → drag → drop onto "+ DRAG HERE TO CREATE A NEW COLLECTION" → name it `manual-all` → close Steam), so both the CLI error and the README use identical wording.

### `adapter.py` — new `OwnedAppIdsSource`

```python
def owned_app_ids_from_collection(gateway: SteamFileGateway, collection_name: str) -> OwnedAppIdsSource:
    """Wrap a manually curated local Steam collection as an :data:`OwnedAppIdsSource`."""
    def source() -> set[int]:
        return set(gateway.read_collection(collection_name).added)
    # end def source
    return source
# end def owned_app_ids_from_collection
```

### `cli.py` — wiring

- `_steam_adapter` (`cli.py:656`) gains a `collection: str | None = None` parameter and `source` becomes `str | None = None`. Resolve: `resolved_source = source or ("collection" if collection is not None else "api")`. Validate `resolved_source in ("api", "installed", "collection")`. New branch:
  ```python
  elif resolved_source == "collection":
      collection_name = collection or "manual-all"
      options = SteamOptions(steam_id=gateway.steam_id, steam_root=root)
      owned_app_ids_source = owned_app_ids_from_collection(gateway, collection_name)
  ```
  (mirrors the existing `installed` branch — no `api_key` needed.)
- `eligible_command` and `sync_command` both get the option pair added, replacing the current `source: ... = "api"`:
  ```python
  source: Annotated[str | None, typer.Option("--source", help="api (Web API, needs a key), installed (local-only approximation), or collection (read a manually curated local Steam collection)")] = None,
  collection: Annotated[str | None, typer.Option("--collection", help="name of a local Steam collection to use as the ownership source; implies --source collection; defaults to 'manual-all'")] = None,
  ```
  and pass `collection` through to `_steam_adapter(...)`.
- `restore_command` is untouched (never touches ownership).

**Known limitation to flag:** Typer/Click can't cleanly give a `str`-typed option a "value-optional" bare form (`--collection` with literally nothing after it) without fighting Click's flag/const machinery in a fragile way. So `--collection` on its own (nothing else typed) is **not** distinguishable from a missing value — the practical default behavior is: *omit `--collection` entirely* → defaults to `manual-all` (once `--source collection` is chosen, or `--collection` is given at all which implies that source); if you do type `--collection`, you must give it a value (`--collection manual-all` or `--collection=manual-all`). This satisfies "just typing `--collection=manual-all`" and "omitting it defaults to manual-all", just not a literally bare trailing `--collection` token.

## Tests

- `tests/test_steam_io.py`: add a case using the existing `build_fake_steam` fixture — add a `user-collections.<id>` entry named e.g. `"manual-all"` with a static `added` list, then assert `gateway.read_collection("manual-all")` returns it (case-insensitive name match too). Add a not-found case and a `filterSpec`-present (dynamic) case, both asserting `SteamIoError` with the expected message content.
- `tests/test_steam_adapter.py`: no change needed to `SteamAdapter` itself (unaffected), but could add a small unit test for `owned_app_ids_from_collection` using a fake gateway stub returning a canned `SteamCollectionPayload`.
- No `tests/test_cli.py` exists yet; CLI wiring (`_steam_adapter`'s new `collection`/`source` resolution) is exercised indirectly through the `io.py`/`adapter.py` unit tests above. Not adding a new CLI test file unless the user wants one.

## Documentation

- `README.md:54-56`: extend the existing `--source installed` paragraph with a new one documenting `--source collection` / `--collection NAME` (default `manual-all`), and include the exact **manual-all creation steps** the user gave (library → select all games → drag onto `+ DRAG HERE TO CREATE A NEW COLLECTION` (or an existing `manual-all` tile) → name it `manual-all` → `CREATE COLLECTION` → close Steam), phrased for a README rather than a terminal error message.
- `lists/README.md`: skim for any place ownership sources are already mentioned; add a short cross-reference if so, otherwise no change needed there.

## Verification

- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_steam_io.py tests/test_steam_adapter.py -q`
- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q` (full suite, confirm no regressions)
- Manually run `uv run game-collections eligible steam --collection manual-all` against a throwaway/fixture Steam root (not the real account) to confirm the new source resolves and errors are readable; also try a deliberately wrong collection name to see the "available collections" listing.
