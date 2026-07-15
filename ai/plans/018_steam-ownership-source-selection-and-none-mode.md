# Steam ownership-source selection and `none` mode

## Summary

Add `--source auto` as the default and `--source none` to `eligible steam`, `sync steam`, and `apply steam`. `auto` resolves ownership from Web API, installed games, then a Steam collection; when none works, it opens a source chooser. `none` deliberately syncs every listed Steam ID without ownership verification.

## Key changes

- Centralize Steam source resolution for `api`, `installed`, `collection`, `auto`, and `none`.
  - `auto` tries API credentials, local installed games, then the configured/default `manual-all` collection.
  - An explicit `--collection` retains its existing meaning of selecting that collection source.
  - Explicit non-auto modes fail directly rather than silently switching sources.
- Add a source chooser after `auto` exhausts its candidates:
  - `apply steam`: a Textual modal with API, installed, collection, and none choices; prompt for a masked API key or collection name as needed and show resolution errors inline.
  - `sync steam` and `eligible steam`: an equivalent terminal chooser with the same prompts and retry behavior.
  - Choices and entered API keys are transient; they are not written to selection config or logs.
- Implement `none` as unverified, unfiltered ownership:
  - Do not apply ownership bounds or unresolved/unconfigured ownership handling.
  - Preserve normal item/date filtering, tier selection, and explicit saved/manual bundle selection.
  - Treat every valid `steam:` ID in each selected list as addable, producing populated Steam collections without claiming ownership is known.
  - Emit a prominent unverified-ownership warning in reports.
- For `sync steam --source none --apply` and `apply steam --source none --apply`, require an additional yes/no warning confirmation before staging. The existing candidate-inspection and typed Steam-replacement confirmations remain required.
- Update command help and README with source precedence, dialog behavior, the installed-games limitation, and the risk/behavior of `none`.

## Test plan

- Cover auto precedence and fallback: API → installed → collection, then chooser; preserve explicit-source failure behavior.
- Cover terminal and Textual chooser flows, including masked API-key/collection-name input, retry after a failed selection, and choosing `none`.
- Verify `none` includes all listed Steam IDs, bypasses ownership-derived eligibility, retains tier/manual selection behavior, and warns before an apply can stage files.
- Update CLI and picker regressions for the former “could not determine Steam ownership” warning path.

## Assumptions

- “Installed” remains the existing local-only approximation: only currently installed Steam games are detected.
- `none` is intentionally unsafe for relevance, not for file replacement: Steam’s existing staging, validation, backup, stopped-client, and replacement safeguards remain unchanged.
