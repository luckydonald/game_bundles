# Steam ownership-source selection and `none` mode

## Summary

Add `--source auto` as the default and `--source none` to `eligible steam`, `sync steam`, and `apply steam`. `auto` resolves ownership from Web API, then a Steam collection, and finally installed games. Only the existing Textual `apply steam` flow offers a fallback source chooser; non-TUI commands fail after automatic resolution fails.

## Key changes

- Centralize Steam source resolution for `api`, `collection`, `installed`, `auto`, and `none`.
  - `auto` tries API credentials first, the configured/default `manual-all` collection second, and installed games last.
  - An explicit `--collection` retains its existing collection-source behavior.
  - Explicit non-auto modes fail directly rather than silently switching sources.
- Add a Textual source-selection modal to `apply steam` after `auto` exhausts its candidates.
  - Offer API, collection, installed, and none; request a masked API key or collection name when required and display failed-attempt feedback inline.
  - Values entered into the modal are transient and never saved or logged.
- For `eligible steam` and `sync steam`, failed `--source auto` resolution exits with an actionable error listing attempted sources and directing the user to use an explicit source. No terminal chooser is added.
- Implement `none` as unverified ownership:
  - Bypass ownership bounds and unresolved/unconfigured ownership handling.
  - Retain item/date filters, tiers, and explicit saved/manual bundle selection.
  - Add every valid `steam:` ID in remaining selected lists to the generated collection.
  - Mark reports as unverified ownership rather than presenting those IDs as confirmed owned.
- Require confirmation whenever `none` is selected:
  - In `apply`, show the warning/confirmation in the Textual flow before continuing to the picker, whether `none` was selected in the fallback modal or passed explicitly.
  - In `eligible` and `sync`, require an explicit terminal confirmation for `--source none` before planning.
  - Existing staging, candidate-inspection, and typed replacement confirmations remain unchanged for `--apply`.
- Update command help and README with source order, the installed-source limitation, non-TUI auto failure behavior, and the explicit risk of none mode.

## Test plan

- Verify auto precedence: API → collection → installed; verify `eligible` and `sync` fail cleanly after all automatic candidates fail.
- Cover the Textual fallback modal’s API, collection, installed, and none paths, including required none confirmation and transient secret handling.
- Cover terminal confirmation for `eligible/sync --source none`, including rejection without planning.
- Verify none mode adds every listed Steam ID while bypassing ownership-based gating but retaining tiers and explicit bundle selection.

## Assumptions

- “Installed” remains the existing local-only approximation: only currently installed Steam games are detected.
- `none` is deliberately unverified for relevance; all existing Steam file safety invariants still apply.
