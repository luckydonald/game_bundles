# Game Collections v1

## Summary

Build a Python 3.14+ project that stores storefront-neutral game collections in YAML, validates every file through Pydantic, generates a JSON Schema from those same models for IDE completion, determines which collections a Steam user fully owns, and safely adds eligible collections to the local Steam library.

The first collection will be Valve’s **The Orange Box** with its five canonical games.

## Key Changes

- Define versioned YAML files under `collections/`, using required names and qualified storefront IDs:

```yaml
# yaml-language-server: $schema=../../schemas/collection.schema.json
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

- Model the complete YAML contract with strict Pydantic models. Reject unknown fields, unsupported schema versions, malformed collection IDs, missing names, malformed qualified IDs, duplicate games, and duplicate storefront IDs.
- Load YAML through `yaml.safe_load`, then immediately validate it with Pydantic. Keep Pydantic models as the single source of truth for both runtime validation and schema generation.
- Generate and commit `schemas/collection.schema.json` using Pydantic’s JSON Schema generation. Add `game-collections schema` to regenerate it deterministically.
- Put a relative `yaml-language-server` schema directive in every collection file so compatible IDE YAML extensions provide completion and diagnostics without repository-specific editor configuration.
- Add a test that regenerates the schema in memory and compares it with the committed file, failing when model changes are not reflected in the schema.
- Keep collection loading provider-independent. Parse each qualified ID into a provider and provider-specific value so Epic, GOG, and other adapters can be added later.
- Provide a Typer CLI:
  - `game-collections validate [PATH]`
  - `game-collections list`
  - `game-collections eligible steam`
  - `game-collections sync steam`
  - `game-collections sync steam --apply`
  - `game-collections schema [--output PATH]`
- Use `STEAM_WEB_API_KEY` and `STEAM_ID` by default, with equivalent CLI options. Mark a collection eligible only when every Steam game in it is owned.
- Report invalid YAML, Pydantic validation errors with file locations, unavailable/private ownership data, missing games, and games without Steam IDs explicitly.
- Synchronize through `userdata/<account-id>/7/remote/sharedconfig.vdf`, deriving the local account ID from SteamID64 and supporting `--steam-root`.
- Create collections by structurally adding the collection name to eligible apps’ Steam tags. Preserve unrelated apps, tags, and collections.
- Make v1 additive and idempotent: add missing tags, but never remove tags or delete collections.
- Keep dry-run as the default. Require `--apply`, refuse writes while Steam is running, create a timestamped backup, serialize to a temporary file, and replace the VDF atomically.
- Support standard Linux, Windows, and macOS Steam roots; fail clearly when the installation, account, or configuration file is absent or ambiguous.
- Replace the inherited README with schema, contribution, credential, synchronization, backup, and recovery documentation.
- Expand `pyproject.toml` with dependencies, console entry point, pytest configuration, and Python 3.14 metadata.
- Generate a project-specific root `AGENTS.md` after implementation, including architecture, commands, schema regeneration, safety invariants, typing, early returns, and mandatory `# end …` comments.

## Test Plan

- Validate the Orange Box YAML and assert its five names and Steam IDs.
- Test Pydantic errors for unknown fields, unsupported versions, missing names, malformed IDs, and duplicates.
- Verify the committed JSON Schema exactly matches deterministic Pydantic generation.
- Parse every repository collection as part of the test suite.
- Mock Steam ownership for fully owned, partially owned, empty, private, and failed API cases.
- Verify Orange Box eligibility requires all five games.
- Test VDF preservation, additive synchronization, repeat-run idempotency, account selection, backups, and atomic replacement.
- Verify dry-run never changes files and `--apply` refuses while Steam is active.
- Add CLI tests for validation output, schema generation, eligibility, failure exit codes, dry-run, and guarded application.

## Assumptions

- “The Orange Box” contains Half-Life 2, Episodes One and Two, Portal, and Team Fortress 2; Lost Coast and ancillary entries are excluded.
- Required game names aid maintenance; qualified IDs remain authoritative.
- Pydantic models are the only authored schema definition. The JSON Schema is generated and committed for IDE use.
- Static Steam collections are supported in v1; dynamic Steam rules are out of scope.
- Steam has no supported public collection-write API, so v1 uses guarded local configuration synchronization.
- The existing untracked `pyproject.toml` will be extended rather than replaced wholesale.
