# Add `game-collections complete --all`

## Context

`complete FILE` (src/game_collections/cli.py:350-432) only ever completes one draft
list at a time. The user wants a bulk mode: `complete --all` that sweeps every list
under `lists/` in one invocation — useful for refreshing all lists with a given
`--mode` (e.g. re-solving leftover `unresolved:store:*`/`unresolved:source:isthereanydeal:*`
markers repo-wide, or `refetch_all` after a schema change) without hand-invoking
`complete` per file.

User confirmed scope: `--all` iterates every list discovered under `lists_root`
(default `./lists`, overridable), the same tree `validate`/`list` already walk via
`discover_game_lists`. It does **not** target loose draft files outside `lists/`
(those still complete via the existing single-`FILE` form, since they may have
blank `ids` and don't pass `GameList.model_validate` until completed).

## Behavior

- `file` becomes optional (`Path | None = None`).
- New `--all` boolean flag.
- New `--lists-root` option (`Path | None`, default `./lists` via existing `_lists_root` helper), only meaningful with `--all`.
- Exactly one of `file` / `--all` must be given; otherwise echo an error to stderr and exit 1, before opening `HumbleHttpClient`/`ItadHttpClient`.
- With `--all`: discover lists via `discover_game_lists(_lists_root(lists_root_path))` (reuse as-is, same error handling as `validate_command` at cli.py:145-150), then loop over `[item.path for item in loaded]`.
- Per-target processing is the existing single-file body (read raw YAML, `complete_game_list`, write back, echo `Updated {path}.` + per-name `unresolved: {title}` to stderr) factored so both the single-`FILE` path and the `--all` loop call it.
- Error handling per target:
  - Single-`FILE` mode: unchanged today's behavior — an `(OSError, ValueError, RuntimeError, yaml.YAMLError)` aborts immediately, caught by the existing outer `except`, `Exit(1)`.
  - `--all` mode: catch the same tuple **per target**, echo `error: {path}: {error}` to stderr, keep going (mirrors the continue-on-error/summary style already used by the `scrape` commands, e.g. cli.py:511-801 — not the fail-fast style of `validate`/`migrate-tiers`, since one bad list in a large tree shouldn't block the rest).
  - Print progress per target in `--all` mode only, matching `_echo_list_progress`'s wording convention (cli.py:135-137): `List {index}/{total}: {path}`.
  - After the loop in `--all` mode, echo one summary line: `Completed {n} list(s); {unresolved_count} unresolved name(s), {error_count} error(s).`
  - Exit 1 if any unresolved names or per-target errors occurred (either mode), exactly like today's single-file exit condition, just aggregated.
- Everything else (provider selection, mode, isthereanydeal client/alias setup, `client.close()`/`itad_client.close()` in `finally`) stays exactly as now — built once, reused for every target.

## Files to change

- `src/game_collections/cli.py`
  - `complete_command` (lines 350-432): add `all_lists`/`lists_root_path` params, add the up-front mutual-exclusion check, extract the per-file body (currently lines 403-422) into a small local loop body reused for both the one-`file` case and the `--all` loop, add progress/summary echoes for `--all`.
  - Reuse `_lists_root` (114-116) and `discover_game_lists` (already imported) exactly as `validate_command` does (140-152) for the `--all` discovery step.
- `lists/README.md:35-43` — add a `game-collections complete --all` example alongside the existing single-file ones (lines 37-41), and a sentence noting it sweeps every list under `lists/` (or `--lists-root`) with the same `--mode`/`--provider` semantics described in the paragraph at line 43.

No changes needed to `src/game_collections/search.py`, `lists.py`, or any schema — this is CLI orchestration only, reusing `complete_game_list`/`discover_game_lists` unchanged.

## Tests

- `tests/test_cli.py` currently has zero coverage of `complete` (confirmed — no hits). Add:
  - A `complete --all` test using `CliRunner` + `tmp_path`: write a small `lists/` tree (2 draft-turned-real list files that still validate, e.g. containing `unresolved:store:steam:*` markers so `mode=unresolved` has something to do), monkeypatch `HumbleHttpClient`/`StorefrontResolver.search` (or `complete_game_list` itself) the way existing `scrape` tests in this file already stub network calls, and assert: both files get processed, progress lines are echoed, the summary line appears, and the exit code matches whether anything stayed unresolved.
  - A quick negative test: invoking `complete` with neither `FILE` nor `--all` (and one with both) exits 1 with the mutual-exclusion message, no HTTP clients constructed.
  - Keep using the existing `CliRunner().invoke(app, [...])` idiom already used for `scrape` commands in this file.

## Verification

- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_cli.py -q` (new tests + no regressions).
- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q` full suite.
- Manual smoke check against this repo's real `lists/` tree in dry, read-mostly form: `env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections complete --all --mode unresolved` (network-dependent; fine to run since `complete` only rewrites files it actually completes, and unresolved names remain markers rather than being destroyed) — confirm the progress lines, per-file `Updated`/`unresolved` output, and final summary line all appear, and `git diff` shows only expected list files touched.
- `env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections complete` (no args, no `--all`) and `game-collections complete --all my-file.yml` both exit 1 with the mutual-exclusion message.
