# Rework the two `ai/errors/2.txt` fixes: type-level URL coercion + deterministic stash restore

## Context

The previous turn fixed both crashes from `ai/errors/2.txt` with quick patches:

1. A `_optional_url()` helper function in `parser.py`, called at each of the 5 sites that
   feed a `str | None` value into an `HttpUrl | None` Pydantic field.
2. A `restore_autostash()` change that inspected `git stash pop`/`apply` stderr for the
   text `"could not restore untracked files from stash"` and dropped the stash if it saw
   that message and no unmerged paths.

The user wants both approaches reworked before this lands:

- **URL fix**: push the empty-string-to-`None` coercion into the Pydantic type itself
  (a reusable annotated type), instead of a helper function every call site has to
  remember to call. This is the same pattern the codebase already uses for
  `NonEmptyString`/`ReferencePath` in `src/game_collections/models.py:14-19`.
- **Stash fix**: don't drop the stash reactively based on parsing git's stderr. Instead,
  exploit the actual guarantee: the autostash is created from a working tree that exactly
  matches `pre_crawl_head` for every path the crawl is about to touch. So *before* calling
  `git stash apply`, reset exactly those crawl-touched paths back to `pre_crawl_head`
  content - this makes the tracked-file part of the apply provably conflict-free, no
  stderr-sniffing needed. If `git stash apply` still doesn't return 0 after that (e.g. an
  unrelated untracked-file collision), leave the stash in place and raise
  `GitAutocommitError` as before - do not drop it speculatively.

## Part 1 - `OptionalHttpUrl` type

In `src/game_collections/sources/humblebundle/models.py`:

- Add `from typing import Annotated` and `from pydantic import BeforeValidator` to the
  imports (alongside the existing `Field, HttpUrl, model_validator`).
- Define, near the top of the file (after the existing imports, before `HumblePrice`):

  ```python
  OptionalHttpUrl = Annotated[HttpUrl | None, BeforeValidator(lambda value: value or None)]
  ```

  This coerces `""` (and any other falsy value pydantic would otherwise try to parse as a
  URL) to `None` before `HttpUrl` validation runs, while still passing real strings through
  for normal `HttpUrl` parsing.
- Replace every `HttpUrl | None` field annotation in this file with `OptionalHttpUrl`:
  `HumbleLink.url` (line 28), `HumbleItem.cover_art_url` (line 51), `HumbleCharity.url`
  (line 92), `HumbleCharity.logo_url` (line 94). Leave the non-optional `HttpUrl` fields
  (`HumbleItem.youtube_urls` list items, `HumbleArchive.url`) untouched.

In `src/game_collections/sources/humblebundle/parser.py`:

- Remove the `_optional_url()` helper added in the previous turn.
- At each of its 5 former call sites, pass the raw `dict.get(...)` value straight through
  instead of pre-sanitizing it - the model now does the coercion:
  - `_links()` (~line 240): `HumbleLink(name=raw[name_key], url=raw.get(url_key))`
  - bundle charity block (~lines 422-427): `url=info.get("url")`,
    `logo_url=info.get("logo_url")`
  - `_bundle_item` cover art (~line 544): `cover_art_url=raw.get("image")`
  - Choice charity block (~line 568): `logo_url=charity.get("charity_logo")`
  - Note: these `.get()` calls can return non-`str` JSON values (numbers, dicts, lists) in
    theory; keep each site's existing `isinstance(..., str)` guard as the *first* condition
    in the ternary, but drop the emptiness check now that the field handles it. E.g.:
    `url=info.get("url") if isinstance(info.get("url"), str) else None,` (unchanged) is
    fine to keep as-is since the type only needs to handle `""`, not non-str types - or
    simplify further only where the surrounding code already guarantees a str/None value.
    Confirm per-site whether the isinstance guard is still needed by checking what
    `.get()` can actually return there (JSON-sourced dict, so always keep the guard).

Existing tests in `tests/test_humblebundle_parser.py` (or wherever `HumbleCharity`/
`HumbleLink` coverage lives - confirm via `grep -rn "HumbleCharity\|HumbleLink" tests/`)
should still pass; add/extend a case that constructs `HumbleCharity(name=..., url="")`
directly to prove the type itself coerces `""` to `None` (not just the parser call site).

## Part 2 - Deterministic `restore_autostash`

In `src/game_collections/git_ops.py`:

- Remove `_UNMERGED_STATUS`, `_unmerged_paths()`, and `_UNTRACKED_COLLISION` - no longer
  needed once the reset makes conflicts structurally impossible for the paths we know
  about.
- Change the signature to `restore_autostash(repository_root: Path, pre_crawl_head: str,
  paths: Sequence[str]) -> None`, where `paths` is the same path list already passed to
  `commit_changed_paths` for this scrape (the crawl only ever touches these paths, and the
  autostash snapshot exactly matches `pre_crawl_head` for them).
- New body:
  1. Try `git stash pop`. Return on success (`returncode == 0`) - this is the common,
     conflict-free case and avoids the extra checkout when nothing collided.
  2. On failure, run `git checkout pre_crawl_head -- <paths>` to reset just the
     crawl-touched paths back to their pre-crawl content. Since the stash was created from
     a working tree identical to `pre_crawl_head` for these paths, this guarantees
     `git stash apply` cannot conflict on any of them.
  3. Run `git stash apply`. If `returncode == 0`, run `git stash drop` and return.
  4. Otherwise (e.g. a leftover untracked file unrelated to the crawl collides), leave the
     stash untouched and raise `GitAutocommitError` with the existing manual-resolution
     message - never drop the stash on a non-clean outcome.

In `src/game_collections/cli.py`:

- `scrape_humblebundle_command` (~lines 557-562): factor the paths list already passed to
  `commit_changed_paths` (`["lists", "archives", str(resolution_map)]`) into a local
  variable and pass it to both `commit_changed_paths` and `restore_autostash`.
- `scrape_isthereanydeal_command` (~lines 843-846): same change with its paths list
  (`["lists", "archives/isthereanydeal"]`).

In `tests/test_git_ops.py`:

- Update `test_restore_autostash_pops_cleanly_when_no_conflict`,
  `test_restore_autostash_falls_back_to_pre_crawl_content_on_conflict`, and
  `test_restore_autostash_raises_when_nothing_was_stashed` to pass a `paths` argument
  (e.g. `["lists"]`) matching what each test's `commit_changed_paths` call used.
- Replace `test_restore_autostash_drops_stash_when_only_untracked_files_collide` (added
  last turn to cover the stderr-sniffing behavior) with a test matching the new contract:
  an untracked-file collision that survives the reset must raise `GitAutocommitError` and
  leave the stash in `git stash list`, not drop it.
- Keep/adapt the conflict-fallback test to assert the new mechanism (checkout + apply)
  still recovers the user's pre-existing local edit when the crawl touched the same file.

In `tests/test_cli.py`:

- Update the three `monkeypatch.setattr("game_collections.cli.git_ops.restore_autostash",
  lambda root, head: ...)` call sites (~lines 215, 252, 332) to accept the new `paths`
  parameter (`lambda root, head, paths: ...`), matching the new call signature from
  `cli.py`.

## Verification

- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_git_ops.py tests/test_cli.py -q`
- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/ -k "humblebundle or humble" -q`
- Full suite: `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q`
- Re-derive the exact scenario from `ai/errors/2.txt` (empty-string charity URL) via a
  direct `HumbleCharity(name="x", url="")` construction in a quick REPL/test to confirm it
  no longer raises.
