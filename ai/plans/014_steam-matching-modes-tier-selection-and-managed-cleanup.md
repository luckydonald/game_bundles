# Steam Matching Modes, Tier Selection, and Managed Cleanup

## Summary

Add `--mode any|all` and `--tiers all|highest` to `game-collections sync steam` for every ownership source, in both dry-run and `--apply` flows.

Defaults become `--mode all --tiers highest`. Sync will reconcile the `🗃️ ` managed namespace: selected collections are created or updated, while previously managed collections that no longer match are deleted through the existing staged, backed-up, confirmed Steam transaction.

## Public Behavior

- `--mode all`: match when the list has at least one Steam AppID and every Steam AppID is owned. Ignore unresolved and non-Steam games.
- `--mode any`: match when at least one Steam AppID is owned. Export only the owned Steam IDs; missing and unsupported entries remain diagnostics.
- `--tiers all`: select every matching list, preserving prior tier-selection behavior.
- `--tiers highest`: select only the greatest matching sibling tier per bundle directory:
  - recognize `tier-N.yml`;
  - recognize `(entire-)?N-item-bundle.yml`;
  - rank by the numeric component and fail on ambiguous duplicate ranks;
  - leave non-tier lists independent;
  - with cumulative lists and `any`, a match inherited from a lower tier can make the highest cumulative tier selectable.
- Do not add these flags to `eligible steam`; its existing interface and tier presentation remain unchanged.
- Invalid values fail before planning. Dry-run reports the complete create/update/delete plan; only `--apply` stages and performs it.

## Reconciliation and Steam Safety

- Treat every static `🗃️ `-prefixed Steam collection as tool-managed and reserve that prefix for this application.
- Also recognize legacy unprefixed collections when their deterministic ID and historical list name match a currently discovered list.
- Read current collections through `SteamFileGateway`, then:
  - create/update every list selected by mode and tier policy;
  - delete every managed collection not selected, including no-longer-matching lists, superseded tiers, and prefixed orphan exports whose source list disappeared;
  - never delete unrelated non-prefixed collections;
  - explicitly protect the collection used by `--source collection` from cleanup;
  - fail closed on dynamic managed collections, deterministic-ID/name conflicts, or malformed state.
- Extend semantic plan changes with typed `create-or-update` and `delete` actions plus a direct launcher target ID so orphaned collections can be addressed safely.
- Implement deletion as a validated `is_deleted: true` collection tombstone using the collection conflict method, a newer timestamp, and the paired modified-key entry.
- Show every deletion in normal dry-run output, the staging manifest, and the human inspection report before typed confirmation.
- Retained managed collections remain additive and preserve manually added games; only stale managed collections are removed.
- Update README and repository Steam-safety guidance to replace the obsolete “never removes collections” invariant with prefix-scoped reconciliation.

## Test Plan

- Adapter tests for `all`, `any`, zero Steam IDs, ignored non-Steam entries, partial ownership, and exported owned-ID sets.
- Tier-selection tests for old `tier-N` lists, Humble `(entire-)?N-item-bundle` lists, `all`, `highest`, non-tier lists, and ambiguous ranks.
- Cleanup-plan tests covering stale ownership matches, superseded tiers, prefixed orphans, legacy unprefixed exports, protected ownership-source collections, unrelated manual collections, and dynamic/conflicting managed collections.
- Steam IO tests proving deletion produces a valid tombstone and dirty key while preserving unrelated namespace data, backups, rollback, and restoration.
- CLI tests for defaults, accepted/rejected values, concise diagnostics, visible delete actions, and all three ownership sources.
- Update sanitized golden fixtures and run the complete test suite; never execute real-account `--apply` or restore during verification.

## Assumptions

- General cleanup means Steam should exactly reflect the collections selected by the current sync run.
- The `🗃️ ` prefix is an ownership namespace, so manually created collections using that prefix are considered managed.
- If no list or tier matches, its existing managed export is deleted.
- Existing managed collections removed by cleanup may contain manually added games; staged backups and explicit confirmation provide recovery.
