# Steam ownership-source selection and `none` mode

## Summary

Add `--source auto` as the default and `--source none` to `eligible steam`, `sync steam`, and `apply steam`. `auto` resolves ownership from Web API, then a Steam collection, and finally installed games. If none work, only the Textual `apply steam` picker opens a source chooser; non-TUI commands fail with actionable guidance.

## Key changes

- Centralize Steam source resolution for `api`, `collection`, `installed`, `auto`, and `none`.
  - `auto` tries API credentials first, the configured/default `manual-all` collection second, and installed games last because it is only a local installed-game approximation.
  - An explicit `--collection` retains its existing meaning of selecting that collection source.
  - Explicit non-auto modes fail directly rather than silently switching sources.
- Add a Textual source-selection modal to `apply steam` after `auto` exhausts its candidates.
  - Offer API, collection, installed, and none; prompt for a masked API key or collection name as needed and show resolution errors inline.
  - The entered values remain transient and are never saved to selection config or logged.
- For `eligible steam` and `sync steam`, `--source auto` fails after all automatic sources fail. The error explains the failed candidates and directs the user to pass `--source api|collection|installed|none` explicitly; no terminal chooser is added.
- Implement `none` as unverified, unfiltered ownership:
  - Do not apply ownership bounds or unresolved/unconfigured ownership handling.
  - Preserve normal item/date filtering, tier selection, and explicit saved/manual bundle selection.
  - Treat every valid `steam:` ID in each selected list as addable, producing populated Steam collections without claiming ownership is known.
  - Emit a prominent unverified-ownership warning in reports.
- For `sync steam --source none --apply` and `apply steam --source none --apply`, require an additional yes/no warning confirmation before staging. Existing candidate-inspection and typed Steam-replacement confirmations remain required.
- Update command help and README with source precedence, the installed-games limitation, non-TUI failure behavior, and the risk/behavior of `none`.

## Test plan

- Cover auto precedence and fallback: API → collection → installed; verify failures do not open a chooser for `eligible` or `sync`.
- Cover the Textual modal’s API/collection/installed/none flows, masked API-key input, retry after a failure, and no-source picker display.
- Verify `none` includes all listed Steam IDs, bypasses ownership-derived eligibility, retains tier/manual selection behavior, and requires the additional apply warning.
- Update CLI and picker regressions for the former ownership-warning path.

## Assumptions

- “Installed” remains the existing local-only approximation: only currently installed Steam games are detected.
- `none` is intentionally unsafe for relevance, not for file replacement: Steam’s existing staging, validation, backup, stopped-client, and replacement safeguards remain unchanged.
