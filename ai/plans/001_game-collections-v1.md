# Game Collections v1

## Summary

Build a Python 3.14+ project that stores maintainable, storefront-neutral game collections in YAML, validates them, determines which collections a Steam user fully owns, and safely adds eligible collections to the local Steam library. Dry-run is the default; writes require `--apply`, Steam to be closed, and an automatic backup.

The first real collection will be Valve’s **The Orange Box** with its five canonical games.

## Key Changes

- Define versioned YAML files under `collections/`, using required human-readable names and qualified storefront IDs:

```yaml
schema: 1
id: valve/the-orange-box
name: The Orange Box
games:
  - name: Half-Life 2
    ids: [steam:220]
  - name: Half-Life 2: Episode One
    ids: [steam:380]
  - name: Half-Life 2: Episode Two
    ids: [steam:420]
  - name: Portal
    ids: [steam:400]
  - name: Team Fortress 2
    ids: [steam:440]
```

- Implement typed models and validation for schema versions, collection IDs, required names, qualified IDs, duplicate collections, duplicate games, and malformed provider identifiers.
- Keep collection loading provider-independent. Parse each qualified ID into a provider name and provider-specific value so Epic, GOG, and other adapters can be added later.
- Provide a Typer CLI:
  - `game-collections validate [PATH]`
  - `game-collections list`
  - `game-collections eligible steam`
  - `game-collections sync steam`
  - `game-collections sync steam --apply`
- Use `STEAM_WEB_API_KEY` and `STEAM_ID` by default, with equivalent CLI options. Query Steam’s owned-games API and mark a collection eligible only when every game with a Steam ID is owned.
- Report invalid data, inaccessible/private ownership data, missing games, and games without Steam IDs explicitly; never treat unavailable ownership data as an empty library.
- Implement Steam synchronization through `userdata/<account-id>/7/remote/sharedconfig.vdf`, deriving the local account ID from the SteamID64 and allowing `--steam-root` as an override.
- Create collections by structurally adding the collection name to each eligible app’s Steam tags. Preserve unrelated apps, tags, and collections.
- Make synchronization additive and idempotent in v1: add missing tags, but never remove tags or delete collections.
- Refuse `--apply` while Steam is running, back up the VDF with a timestamp, write through a temporary file, and atomically replace the original only after successful serialization.
- Support standard Linux, Windows, and macOS Steam roots; fail with an actionable message when the root, account, or VDF file is ambiguous or absent.
- Replace the inherited base README with format, contribution, credential, dry-run, backup, and recovery documentation.
- Expand `pyproject.toml` with package metadata, dependencies, console entry point, pytest configuration, and the Python 3.14 requirement.
- Generate a project-specific root `AGENTS.md` after implementation, documenting architecture, commands, safety invariants, typing requirements, early-return style, and mandatory `# end if` / `# end for` / `# end def` / `# end class` comments.

## Test Plan

- Validate the Orange Box YAML and assert all five names and Steam app IDs.
- Test qualified-ID parsing, schema rejection, missing names, malformed IDs, and duplicate detection.
- Mock owned-games responses for fully owned, partially owned, empty, private, and failed API cases.
- Verify eligibility requires all five Orange Box games.
- Test VDF synchronization against sanitized fixtures, including preservation of unrelated tags, repeat-run idempotency, multi-account selection, backup creation, and atomic replacement.
- Verify dry-run never changes files and `--apply` refuses to run while Steam is active.
- Add CLI integration tests for validation, eligibility reporting, dry-run output, failure exit codes, and guarded application.

## Assumptions

- “The Orange Box” means Half-Life 2, Episodes One and Two, Portal, and Team Fortress 2; Lost Coast and ancillary package entries are excluded.
- Game names are required for maintainability, while qualified IDs are authoritative.
- Only static Steam collections are in v1; dynamic Steam collection rules are out of scope.
- Steam offers no supported public collection-write API, so v1 deliberately uses guarded local configuration synchronization.
- The existing untracked `pyproject.toml` is the starting point and will be extended rather than discarded.
