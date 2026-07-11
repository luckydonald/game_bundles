# Game Collections v1

## Summary

Build a Python 3.14+ resource of Pydantic-validated YAML game lists plus a guarded Steam synchronizer. List IDs come from their paths below `lists/`; Steam collections use Steam’s current cloud-storage format, discovered read-only from the logged-in client.

The first list is `lists/valve/the-orange-box.yml`, whose ID is `valve/the-orange-box`. `lists/README.md` will explain the format and contribution workflow.

## Lists And Schema

- A list file contains no explicit collection ID. Derive it from its POSIX path relative to `lists/`, without the `.yml` suffix; reject non-`.yml` files, symlinks escaping the root, duplicate derived IDs, and case-colliding paths.
- Define strict Pydantic models as the single source of truth:

```yaml
# yaml-language-server: $schema=../../schemas/game-list.schema.json
schema: 1
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

- Require names, qualified storefront IDs, and schema version 1. Reject unknown fields, malformed IDs, duplicate games, and duplicate storefront IDs.
- Load with `yaml.safe_load` and validate immediately through Pydantic.
- Generate and commit `schemas/game-list.schema.json` through `game-collections schema`; every YAML file carries a relative `yaml-language-server` directive.
- Add a schema drift test comparing committed JSON Schema with deterministic Pydantic generation.
- Provide `game-collections validate`, `list`, `eligible steam`, `sync steam`, and `schema` commands.
- Use `STEAM_WEB_API_KEY` and the selected SteamID64 for `GetOwnedGames`. Treat unavailable/private results as errors, not empty ownership. A list is eligible only when every Steam ID is owned.

## Steam Synchronization

- Use the current Steam representation, not legacy `sharedconfig.vdf`. The investigated client stores collections in:
  - `userdata/<account-id>/config/cloudstorage/cloud-storage-namespace-1.json`
  - `userdata/<account-id>/config/cloudstorage/cloud-storage-namespace-1.modified.json`
- Select the `MostRecent=1` account from `config/loginusers.vdf`; allow `--steam-id` and `--steam-root` overrides. Derive the userdata account ID from SteamID64 and verify all selected paths agree.
- Parse namespace 1 as Steam’s array of `[key, entry]` pairs. Static collections use keys named `user-collections.<steam-collection-id>` and compact values shaped as:

```json
{"id":"uc-...","name":"The Orange Box","added":[220,380,420,400,440],"removed":[]}
```

- Derive a stable Steam collection ID from the logical list ID: hash `valve/the-orange-box` with SHA-256, take the first 9 bytes, encode them using Steam’s 12-character base64-style user-collection encoding, escape `/` as `*+`, and prefix `uc-`. This follows Steam’s observed user-created ID shape while keeping repeated syncs stable.
- Abort on a deterministic-ID collision, malformed existing record, dynamic `filterSpec`, system collection name collision, or another user collection already using the requested display name. Never delete or silently merge an unrelated same-name collection.
- For eligible lists, create or update the deterministic record:
  - Preserve manually added existing apps by unioning `added` with the list’s Steam IDs.
  - Remove newly added IDs from `removed`.
  - Preserve other unrelated record data only when valid for a static collection.
  - Set a timestamp greater than both current Unix time and every existing namespace timestamp.
  - Set `conflictResolutionMethod` to `custom` and `strMethodId` to `union-collections`, matching Steam’s client implementation.
  - Omit `version` for a dirty local update, matching Steam’s own `Upsert`.
- Add the complete `user-collections.<id>` key to namespace 1’s modified-key array without duplicates. Do not alter `cloud-storage-namespaces.json`, legacy VDF files, or any other namespace.
- On the next Steam start, Steam will load the dirty key, download current remote state, apply its `union-collections` conflict resolver, upload through `CloudConfigStore.Upload`, assign the server version, and clear the dirty marker.
- Keep v1 additive: never remove games, collections, or unrelated Steam data.

### Guarded Apply Workflow

- `game-collections sync steam` is entirely read-only and prints the semantic change plan.
- `game-collections sync steam --apply` initially writes only to a timestamped staging directory on the user’s Desktop, configurable with `--output-dir`. It creates:
  - candidate replacements for both namespace files;
  - byte-for-byte timestamped backups made with metadata preservation;
  - hashes and source/destination paths;
  - a human-readable semantic diff and recovery instructions.
- Print every candidate, original, backup, and eventual destination path, then pause so the user can inspect them.
- Before offering replacement:
  - require Steam and its PID/pipe to be stopped;
  - re-hash both originals and abort if either changed since candidate generation;
  - reparse candidates and originals;
  - validate pair consistency, unique keys, entry/key agreement, timestamps, dirty markers, and backup hashes;
  - preserve original ownership and permissions on candidates.
- Only after those checks, print backup locations again and require an explicit typed confirmation naming the action. There is no non-interactive bypass in v1.
- Replace the namespace file first and modified-key file second using same-directory temporary files, `fsync`, and atomic `os.replace`. If the second replacement fails, restore the first automatically from its verified backup.
- After success, print exact restoration commands and require Steam to remain stopped during restoration. Also provide `game-collections steam restore <staging-directory>`, with the same Steam-stopped check and typed confirmation.
- During implementation and testing, never invoke `--apply` against the real logged-in account without a separate explicit request from the user.

## Verification And Delivery

- Test list-path ID derivation, Orange Box contents, Pydantic failures, schema drift, and validation of every repository list.
- Mock Steam ownership for complete, partial, private, empty, and failed responses.
- Build sanitized fixtures matching the observed namespace and modified-key formats; never commit real account data.
- Test deterministic Steam IDs, static record creation, additive updates, name/ID collisions, timestamp advancement, dirty-key handling, semantic reports, and byte-preserving backups.
- Test source-change detection, running-Steam refusal, typed confirmation, atomic replacement rollback, restoration, and dry-run immutability.
- Expand `pyproject.toml`, replace the inherited README, and generate a project-specific root `AGENTS.md` covering architecture, commands, schema regeneration, Steam safety, typing, early returns, and mandatory `# end …` comments.
- At implementation start, activate `commit-with-lplp-style`, inspect recent history, fold the current task’s chained prompt commits appropriately, stage only explicit task files, and commit each completed task through `ai/git/pending-commit.md`.

## Assumptions

- The Orange Box contains Half-Life 2, Episodes One and Two, Portal, and Team Fortress 2; Lost Coast is excluded.
- Qualified IDs are authoritative; required names make lists reviewable.
- Static Steam collections only are supported in v1.
- Steam’s cloud-storage files are an internal interface and may change; structural preflight failures must stop synchronization rather than guess.
- The existing untracked `pyproject.toml` is extended rather than discarded.
