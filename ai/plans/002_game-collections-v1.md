# Game Collections v1

## Summary

Build a Python 3.14+ resource of Pydantic-validated YAML game lists with a launcher-neutral architecture and a fail-closed Steam synchronizer.

List IDs derive from paths below `lists/`. Steam integration will model every external file it reads or replaces, stage inspectable candidates and backups on the Desktop, and expose no path that can modify Steam before validation, shutdown checks, and typed confirmation.

## Lists And Core Architecture

- `lists/valve/the-orange-box.yml` has the derived ID `valve/the-orange-box`; YAML files contain no explicit ID.
- Reject non-`.yml` files, paths escaping `lists/`, duplicate derived IDs, and case-insensitive path collisions.
- Add `lists/README.md` explaining the format, IDs, validation, schema completion, and contribution workflow.
- Define strict Pydantic list models with required names, schema version 1, qualified storefront IDs, unknown-field rejection, and duplicate detection.
- Generate and commit `schemas/game-list.schema.json` from Pydantic. Add relative `yaml-language-server` directives and a schema drift test.
- Keep the core independent from launchers:
  - `QualifiedGameId` represents `provider:value`.
  - A provider registry validates identifiers such as `steam:440`, later `gog:...` or `epic:...`.
  - An ownership adapter resolves owned IDs.
  - A launcher adapter produces a semantic sync plan, stages external-file changes, validates candidates, and performs a guarded apply.
  - Shared `SyncPlan`, `StagedSync`, `FileReplacement`, and `RestorePlan` models carry launcher-neutral reporting and safety metadata.
- Place launcher-specific implementations beside one another, beginning with `launchers/steam`; later GOG or Epic modules implement the same protocols without changing YAML loading or CLI orchestration.
- Resolve adapters through an explicit internal registry in v1. Keep registration isolated so Python entry-point discovery can be added later without changing adapter contracts.
- Provide generic CLI commands: `validate`, `list`, `eligible <launcher>`, `sync <launcher>`, `schema`, and `restore <launcher>`.

## Complete Steam Models

All models use strict types, `extra="forbid"`, cross-field validators, duplicate-key rejection, bounded file sizes, and fail-closed parsing. Any unrecognized envelope field or incompatible relevant payload aborts before staging.

- `LoginUsersFile` models the VDF root and dynamic SteamID64 keys. `LoginUserRecord` includes exactly the observed fields: `AccountName`, `PersonaName`, `RememberPassword`, `WantsOfflineMode`, `SkipOfflineModeWarning`, `AllowAutoLogin`, `MostRecent`, and `Timestamp`, with VDF boolean/timestamp validation.
- `SteamPidFile` models the numeric PID and validates it against the running process when available. Pipe presence and Steam-related process detection are separate safety signals.
- `CloudStorageNamespacesFile` models `cloud-storage-namespaces.json` as unique `(namespace: int, version: str)` tuples and requires namespace 1 to exist.
- `CloudStorageNamespaceFile` models namespace 1 as unique `(outer_key, CloudStorageEntry)` tuples.
- `CloudStorageEntry` models exactly `key`, `timestamp`, optional `value`, optional `is_deleted`, optional `version`, optional `conflictResolutionMethod`, and optional `strMethodId`. It enforces:
  - outer key equals entry key;
  - exactly one of `value` or `is_deleted=true`;
  - valid timestamp and version types;
  - `strMethodId` appears only with `conflictResolutionMethod="custom"`;
  - known conflict methods only.
- `ModifiedKeysFile` models `cloud-storage-namespace-1.modified.json` as a unique list of non-empty keys, all of which must exist in namespace 1.
- Parse every `user-collections.*` value into `SteamCollectionPayload`, covering exactly `id`, `name`, `added`, `removed`, and optional `filterSpec`.
- Fully model the observed dynamic filter format with `SteamFilterSpec` and `SteamFilterGroup`: require `nFormatVersion=2`, `strSearchText`, ordered `filterGroups`, integer `rgOptions`, boolean `bAcceptUnion`, and the observed optional `setSuggestions` array/object forms. Dynamic collections remain readable but cannot be modified by v1.
- Model `collection-bootstrap-complete` and require it to be `"true"` before collection staging.
- Model Steam’s `GetOwnedGames` response, including response envelope, game entries, app IDs, counts, and optional metadata. Missing/private/malformed responses are errors.
- Keep unrelated namespace entry values as validated opaque strings after their outer `CloudStorageEntry` passes validation; do not parse or reinterpret unrelated feature payloads.
- Add sanitized format fixtures and schema-signature tests for every modeled file. A newly introduced field, changed type, filter format version, duplicate key, or violated invariant must produce an explicit “unsupported Steam format” error and no candidates.

## Steam Collection Mapping

- Select `MostRecent=1` from `loginusers.vdf`, with `--steam-id` and `--steam-root` overrides. Verify SteamID64, derived account ID, userdata directory, and ownership response all identify the same account.
- Read only:
  - `config/loginusers.vdf`
  - `.steam/steam.pid` and pipe/process state
  - `cloud-storage-namespaces.json`
  - `cloud-storage-namespace-1.json`
  - `cloud-storage-namespace-1.modified.json`
- Never touch legacy `sharedconfig.vdf`, `remotecache.vdf`, library cache files, other namespaces, or Steam credentials.
- Create stable Steam IDs from the logical list ID: SHA-256, first 9 bytes, Steam-compatible 12-character base64 encoding, `/` escaped as `*+`, prefixed with `uc-`.
- Store static records as `user-collections.<id>` with compact payloads containing `id`, `name`, `added`, and `removed`.
- Abort on deterministic-ID collision, unrelated same-name collection, system-name collision, malformed existing record, or dynamic collection at the managed ID.
- Make updates additive:
  - union desired Steam IDs with existing `added`;
  - remove those IDs from `removed`;
  - never delete collections or manually added games;
  - preserve valid unrelated static payload state.
- Create a timestamp greater than current Unix time and all existing namespace timestamps.
- Mark dirty entries with `conflictResolutionMethod="custom"` and `strMethodId="union-collections"`, omit `version`, and add the full key to the modified-key file.
- Steam will subsequently download, union conflicts, upload through `CloudConfigStore.Upload`, assign a server version, and clear the dirty marker.

## Locked Steam File IO

- Put all Steam reads and replacements behind one `SteamFileGateway`; launcher/domain code receives validated snapshots and cannot open arbitrary Steam paths.
- The gateway accepts only canonical files selected from a verified Steam root and account. Resolve and containment-check every path; reject symlinks, non-regular files, unexpected owners, unsafe permissions, hard-link anomalies, and path changes between inspection and replacement.
- Open source files read-only with no-follow semantics where supported. Record canonical path, device, inode, owner, mode, size, mtime, and SHA-256.
- Parse JSON with duplicate-key detection and VDF through a structured parser followed immediately by Pydantic validation.
- Build changes as pure transformations of immutable validated snapshots. Serialization is allowed only from validated candidate models.
- `sync steam` is read-only and emits a semantic plan.
- `sync steam --apply` may initially write only to a timestamped Desktop staging directory, configurable through `--output-dir`. It creates:
  - candidate namespace and modified-key files;
  - byte-for-byte metadata-preserving backups;
  - a Pydantic-validated manifest containing source/destination paths, hashes, metadata, account identity, and intended operations;
  - semantic and machine-readable diffs;
  - restoration instructions.
- Print all source, candidate, backup, and destination paths, then pause for inspection.
- Before replacement:
  - require Steam processes, PID, and pipe to be stopped;
  - reopen originals through the gateway;
  - require device, inode, owner, mode, size, mtime, and hashes to match the inspected snapshot;
  - revalidate originals, candidates, manifest, collection invariants, timestamps, and dirty-key consistency;
  - verify backup hashes and candidate permissions;
  - reject any source or staged path substitution.
- Print backup locations and exact operations again, then require a typed confirmation. Provide no non-interactive bypass in v1.
- Stage same-directory temporary files with exclusive creation, restrictive permissions, full writes, `fsync`, reparsing, and hash verification.
- Atomically replace namespace 1 first and modified keys second, then `fsync` the containing directory. If the second replacement fails, restore and verify the first from backup before reporting failure.
- Never modify `cloud-storage-namespaces.json`; it is validation context only.
- Emit a completion manifest only after both replacements and post-write reads match their candidates.
- Print exact restoration commands and require Steam to remain stopped. `restore steam <staging-directory>` repeats path containment, account, metadata, backup hash, Steam-stopped, and typed-confirmation checks.
- No implementation or test run may invoke real-account `--apply` or restoration without a separate explicit user request.

## Testing And Delivery

- Validate Orange Box’s five canonical games and derived path ID.
- Test list models, schema generation/drift, provider registry, and every repository YAML file.
- Test strict Steam models against sanitized valid fixtures and mutations representing added fields, removed fields, type changes, duplicate keys, unknown conflict methods, filter version changes, malformed collection JSON, and inconsistent modified keys.
- Mock complete, partial, private, empty, and failed Steam ownership responses.
- Test deterministic IDs, additive updates, collisions, timestamps, dirty markers, and preservation of unrelated entries.
- Test every IO guard: symlinks, traversal, owner/mode changes, inode swaps, source changes after staging, running Steam, invalid backups, invalid candidates, confirmation rejection, partial replacement rollback, and restoration.
- Replace the inherited README, expand `pyproject.toml`, and generate a project-specific root `AGENTS.md` covering architecture, adapter contracts, schema regeneration, Steam safety, typing, early returns, and mandatory `# end …` comments.
- At implementation start, activate `commit-with-lplp-style`, inspect recent history, stage only task files, fold current prompt commits appropriately, and commit completed tasks through `ai/git/pending-commit.md`.

## Assumptions

- List IDs exclude the `.yml` suffix.
- The Orange Box contains Half-Life 2, Episodes One and Two, Portal, and Team Fortress 2; Lost Coast is excluded.
- Static Steam collections only are writable in v1.
- Steam’s files are an internal interface; any model drift or uncertain invariant stops synchronization.
- Pydantic models describe complete file envelopes and every collection payload; unrelated namespace values remain opaque because this tool neither interprets nor changes them.
- The existing untracked `pyproject.toml` is extended rather than discarded.
