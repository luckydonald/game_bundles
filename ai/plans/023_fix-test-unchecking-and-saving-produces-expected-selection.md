# Fix `test_unchecking_and_saving_produces_expected_selection`

## Context

This test (`tests/test_apply_tui.py:970-991`) has been failing since before this session's other work (confirmed pre-existing via `git stash`/`git stash pop` against clean `mane`). A prior session diagnosed the root cause and left it in memory (`apply_tui_save_test_bug.md`), but did not fix it. This plan fixes the test and removes that now-stale memory once done.

Root cause, confirmed by reading the code directly:

1. `ApplyPickerApp.action_save()` (`src/game_collections/apply/tui.py:1166-1169`) only sets `self._pending_selection` and pushes the `ApplyActionScreen` modal (`tui.py:206-238`, "Dry run" / "Apply to Steam" / "Close" buttons). `app.return_value` isn't set until the modal's callback, `_apply_action_selected()` (`tui.py:632-638`), actually fires — which requires a button press.
2. The test calls `app.action_save()` and immediately asserts on `app.return_value` without ever interacting with the pushed modal, so `return_value` stays `None`.
3. **A second bug the prior session's memory missed**: even once the modal is driven, `app.return_value` is an `ApplyPickerResult` (`tui.py:105-112`, fields `selection: ApplySelection` and `action: Literal[...]`), not an `ApplySelection`. `ApplySelection.selected`/`.excluded` (`src/game_collections/apply/config.py:31-32`) live one level down, on `.selection`. The test's current assertions (`app.return_value.selected`, `app.return_value.excluded`) reach for attributes that don't exist on `ApplyPickerResult` at all — this would raise `AttributeError`, not fail the `is not None` check, once the modal is driven.

## Fix

Edit only `tests/test_apply_tui.py`, in `test_unchecking_and_saving_produces_expected_selection` (lines 970-991):

- After `app.action_save()`, add `await pilot.pause()` so the `ApplyActionScreen` modal actually mounts.
- Drive the modal to a dismissal via `await pilot.click("#apply-action-close")` (the "Close" button — the neutral choice, since this test is about the saved selection, not about actually running dry-run/apply), followed by `await pilot.pause()`.
- Update the assertions to go through `.selection`:
  - `app.return_value.selection.selected == ["humblebundle/bundle/2026-01-01_a/bundle"]`
  - `app.return_value.selection.excluded == ["greenmangaming/bundle/2026-02-01_b/tier-2"]`
- Leave the trailing `app.all_game_lists` assertion (lines 987-990) as-is; it's unaffected by this bug.

No production code changes — the bug is entirely in the test's interaction/assertion shape, not in `tui.py`.

## Verification

```console
env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_apply_tui.py -q
```

Confirm `test_unchecking_and_saving_produces_expected_selection` passes and no other test in the file regresses.

## Cleanup

Per the user's request, once the fix is verified:
- Delete `/home/user/.confuig/claude/accounts/private/projects/-home-user-git-luckydonald-game-collections/memory/apply_tui_save_test_bug.md`.
- Remove its entry from the memory index `MEMORY.md`.

## Commit

This repo's `commit-with-lplp-style` skill is active (per `CLAUDE.md`) — commit the test fix as its own task through that workflow (`ai/git/pending-commit.md`), staging only `tests/test_apply_tui.py`.
