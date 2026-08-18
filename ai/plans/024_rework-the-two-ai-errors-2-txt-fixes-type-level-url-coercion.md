# Rework the two `ai/errors/2.txt` fixes: type-level URL coercion + non-destructive stash restore

## Context

The previous turn fixed both crashes from `ai/errors/2.txt` with quick patches:

1. A `_optional_url()` helper function in `parser.py`, called at each of the 5 sites that
   feed a `str | None` value into an `HttpUrl | None` Pydantic field.
2. A `restore_autostash()` change that inspected `git stash pop`/`apply` stderr for
   `"could not restore untracked files from stash"` and dropped the stash whenever it saw
   that message and no unmerged tracked paths.

The user asked for both to be reworked:

- **URL fix**: push the coercion into the Pydantic type itself, like the codebase's
  existing `NonEmptyString`/`ReferencePath` annotated types in
  `src/game_collections/models.py:14-19`, instead of a helper function every call site has
  to remember to call. The validator must be **specific**: coerce only the exact `""`
  empty-string case actually seen in the crash, not any other falsy value.
- **Stash fix**: the previous turn's stderr-sniffing "drop the stash" logic is wrong -
  dropping a stash can permanently discard untracked local changes that failed to
  restore, which is exactly the data the autostash exists to protect. The fix must not
  introduce any new drop condition. Restoring should:
  1. First try to keep local changes layered **on top of the crawl's own commit**
     (`git stash pop` as-is) - the best case, since it keeps both the crawl's output and
     the user's edits.
  2. Only for the *specific* paths where that would otherwise produce a patch-apply
     conflict, fall back to discarding the crawl commit's working-tree copy of just that
     path (safe - it's already preserved in the crawl commit's history) and re-apply so
     the user's pre-crawl edit for that path lands instead. Do **not** reset every
     crawl-touched path speculatively - only the ones that actually conflict.
  3. If restoration still doesn't fully succeed after that (e.g. an unrelated untracked
     file collides), leave the stash exactly as-is and raise `GitAutocommitError` so a
     human resolves it manually - never drop it on an unresolved issue.

  This is, in effect, reverting `restore_autostash()` to its original (pre-previous-turn)
  algorithm: the stderr-based drop branch was the bug, not the underlying try/fallback
  structure.

## Part 1 - `OptionalHttpUrl` type

In `src/game_collections/sources/humblebundle/models.py`:

- Add `Annotated` to the `typing` import and `BeforeValidator` to the `pydantic` import.
- Add a small named validator and type alias near the top of the file (after imports,
  before `HumblePrice`):

  ```python
  def _empty_string_to_none(value: object) -> object:
      return None if value == "" else value
  # end def _empty_string_to_none


  OptionalHttpUrl = Annotated[HttpUrl | None, BeforeValidator(_empty_string_to_none)]
  ```

  Only the literal `""` is coerced; any other input (including non-string JSON values)
  passes through unchanged to `HttpUrl`'s own validation, preserving today's error
  behavior for genuinely malformed input.
- Replace `HttpUrl | None` with `OptionalHttpUrl` on the 4 optional-URL fields in this
  file: `HumbleLink.url` (line 28), `HumbleItem.cover_art_url` (line 51),
  `HumbleCharity.url` (line 92), `HumbleCharity.logo_url` (line 94). Leave the
  non-optional `HttpUrl` fields (`HumbleItem.youtube_urls`, `HumbleArchive.url`) alone.

In `src/game_collections/sources/humblebundle/parser.py`:

- Remove the `_optional_url()` helper added last turn.
- At its 5 former call sites, pass the raw `.get(...)` result straight through, keeping
  each site's existing `isinstance(..., str)` guard (still needed since these are
  JSON-sourced dicts that can hold non-str values) but dropping the now-redundant
  emptiness check:
  - `_links()` (~line 240): `url = raw.get(url_key) if isinstance(raw.get(url_key), str) else None`
  - bundle charity block (~lines 424/426): `url=info.get("url") if isinstance(info.get("url"), str) else None`,
    `logo_url=info.get("logo_url") if isinstance(info.get("logo_url"), str) else None`
  - `_bundle_item` cover art (~line 544): `cover_art_url=raw.get("image") if isinstance(raw.get("image"), str) else None`
  - Choice charity block (~line 568): `logo_url=charity.get("charity_logo") if isinstance(charity.get("charity_logo"), str) else None`

  (These end up textually identical to the pre-previous-turn code - the model now handles
  the `""` case that used to crash.)

Add a direct model-level test (in `tests/test_humblebundle_parser.py` or wherever
`HumbleCharity`/`HumbleLink` are covered - confirm with
`grep -rn "HumbleCharity\|HumbleLink" tests/`) constructing
`HumbleCharity(name="x", url="")` and asserting `url is None`, to prove the coercion lives
in the type, not the call site.

## Part 2 - Restore `restore_autostash` to the safe algorithm

In `src/game_collections/git_ops.py`:

- Remove `_UNTRACKED_COLLISION` and the two branches that reference it (the
  `if not conflicting and _UNTRACKED_COLLISION in pop.stderr: ... drop ...` block, and the
  `or (not _unmerged_paths(...) and _UNTRACKED_COLLISION in apply_result.stderr)` clause
  on the fallback's success check).
- Keep `_UNMERGED_STATUS` / `_unmerged_paths()` - they're exactly the "which paths would
  otherwise conflict" detector the user wants.
- Resulting body (matching the function's original shape):
  1. `git stash pop`; return on `returncode == 0`.
  2. `conflicting = _unmerged_paths(...)`.
  3. If `conflicting`: `git checkout pre_crawl_head -- <conflicting>`, then
     `git stash apply`; if that returns `0`, `git stash drop` and return.
  4. Otherwise (no conflicting paths found, or the fallback apply still didn't return 0),
     fall through to `raise GitAutocommitError(...)` with the existing manual-resolution
     message, leaving the stash untouched.
- No signature change needed - `paths` from `commit_changed_paths` is not required here,
  since conflict detection is derived from actual git status, not a pre-declared list.

In `tests/test_git_ops.py`:

- Remove `test_restore_autostash_drops_stash_when_only_untracked_files_collide` (asserts
  the now-reverted drop-on-collision behavior).
- Add a replacement test asserting the *correct* behavior: when an untracked file that was
  part of the stash gets recreated in the working tree before restore (so restoring it
  would collide) and there are no tracked-file conflicts, `restore_autostash` must raise
  `GitAutocommitError` and the stash must still be present in `git stash list` afterward
  (nothing dropped).
- Leave `test_restore_autostash_pops_cleanly_when_no_conflict` and
  `test_restore_autostash_falls_back_to_pre_crawl_content_on_conflict` as-is - they already
  match the restored algorithm.

No changes needed in `cli.py` or `tests/test_cli.py` for Part 2 - the function signature
is unchanged.

## Verification

- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_git_ops.py tests/test_cli.py -q`
- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/ -k "humblebundle or humble" -q`
- Full suite: `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q`
- Confirm `HumbleCharity(name="x", url="")` no longer raises, and that passing a clearly
  invalid non-empty URL string still does raise (proving the validator is scoped to `""`
  only, not silently swallowing other bad input).
