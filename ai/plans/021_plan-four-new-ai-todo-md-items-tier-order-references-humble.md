# Plan: four new `ai/todo.md` items (tier order, references, humble authority, live validation)

## Context

The previous four `ai/todo.md` items are done and committed. Four new items were
added afterward:

```
- [ ] The order of `tier-1` to `tier-3` is reversed between `humblebundle` and `isthereanydeal`, which causes full file conflicts.
  - The full bundle is the highest tier.
  - I believe `humblebundle` has it wrong.
- [ ] `references` should be appended to, not overwritten.
- [ ] HumbleBundle shall still be authoritative with its games, so not on humble = remove from bundle.
      - hehe, that rhymes!
- [ ] Validate by running both scrapers and comparing the list's output, if there are remaining issues to tackle.
```

Investigated via five Explore passes plus two rounds of user clarification.
Findings, already verified against current code:

- **Tier order bug is real and confirmed**, but only in the classic Humble
  Games-bundle path, not Choice. Humble's own `tier_order` field is
  full-tier-first (descending); `humblebundle/parser.py` preserves that
  order faithfully (correct, not buggy); `humblebundle/crawler.py`'s classic
  tier-writing loop (~lines 322-346) just enumerates that order 1..N with
  **no re-sort**, so a live crawl would write `tier-1.yml` = the full/highest
  bundle and `tier-3.yml` = the smallest — backwards from the convention
  (confirmed via real on-disk data and isthereanydeal's own, correctly
  ascending, tier order) where tier number rises with item count and the
  full bundle is always the highest-numbered tier. The Choice-picks path is
  already correct (sorted by quota ascending in the parser).
- **`references` is always fully replaced, never merged**, in the one place
  that already merges anything (`merge_game_list` in `sources/common.py`) —
  it takes `references` wholesale from the fresh crawl. Only humblebundle's
  crawler calls `merge_game_list` today; isthereanydeal/greenmangaming/
  dailyindiegame overwrite everything unconditionally (out of scope here —
  todo only asks about the append-vs-overwrite *policy*, and the only place
  that policy currently exists is `merge_game_list`).
- **Humble-authority removal directly conflicts with `merge_game_list`'s
  current "never remove" design.** There is no manual/provenance marker on
  `Game` anywhere. The user confirmed: no hand-edited entries exist in
  practice, so the only real risk is an isthereanydeal-authored file (ITAD
  can write into `lists/humblebundle/...` when it reaches a bundle before
  the dedicated scraper does) later losing ITAD-only games once Humble's own
  crawler starts merging into it. The user explicitly chose the simpler
  option — Humble is unconditionally authoritative, no provenance check —
  but wants non-matching existing games quarantined into a new `invalid:`
  section rather than hard-deleted, and asked for a real "same game"
  matching cascade instead of the current bare `name.casefold()` key.
- **No existing fuzzy-matching utility.** `sources/storefronts.py:36-41`'s
  `normalized_title()` (NFKD-normalize, casefold, strip to alnum-only) is
  the only real normalization helper in the codebase and is a clean fit for
  a "normalized name" tier. No fuzzy-similarity library is installed; user
  wants a 4th fuzzy tier added, which means a new dependency (`rapidfuzz`,
  the modern standard — no `python-Levenshtein`/`thefuzz` baggage).
- For live validation, the user wants an actual scrape-and-diff run as part
  of this task, plus a new `--git` flag on the scrape commands that
  autostashes pending changes before the scrape and restores them after —
  **not** an auto-commit (that stays a manual/agent action via the existing
  `commit-with-lplp-style` flow), scoped to `scrape humblebundle` and
  `scrape isthereanydeal` (the two being compared).

**Sequencing:** 1 (tier order) → 2 (references) → 3 (humble authority +
matching + invalid) → 4 (`--git` flag + live validation run), since item 4's
comparison run is only meaningful once 1-3 are in place, and 3 depends on
nothing from 1/2 but is the largest change.

---

## Item 1 — Fix reversed tier order in the classic Humble Games-bundle path

**Fix:** in `src/game_collections/sources/humblebundle/crawler.py`, the
`tiers_with_games` construction feeding the classic-bundle `enumerate` loop
(~lines 322-333) must sort by ascending item count before ranking:
```python
tiers_with_games = sorted(tiers_with_games, key=lambda pair: pair[0].item_count)
```
(exact variable names to confirm against current code — the loop currently
iterates `archive.tiers` in raw/source order with no sort key at all). The
Choice-picks path (~lines 283-317) needs no change — already sorted by quota
ascending in `parser.py:488`.

**Tests:** `tests/test_humblebundle_crawler.py` — add/extend a classic-tier
test asserting that when `archive.tiers` arrives in descending item-count
order (mirroring real Humble `tier_order` data), the crawler still writes
`tier-1.yml` = smallest, highest `tier-N.yml` = the full/entire bundle.

No schema change (write-order only, not a model shape change).

---

## Item 2 — Append `references`, don't overwrite, in `merge_game_list`

**Fix:** in `src/game_collections/sources/common.py::merge_game_list`,
instead of taking `references` wholesale from `fresh`, merge:
```python
merged_references = list(existing.references)
merged_references.extend(ref for ref in fresh.references if ref not in merged_references)
```
`Reference` is a plain Pydantic model with field-wise `==`, so `in` works
directly — no new equality/hash code needed. Order: existing references
first (their positions stay stable across re-crawls), then any references
`fresh` introduces that aren't already present verbatim.

**Tests:** `tests/test_sources_common.py` — new case: existing has a
reference fresh doesn't (e.g. a prior ITAD mirror reference), fresh has a
reference existing doesn't (the current crawl's own reference) → merged has
both, existing ones first. Also a no-op case: identical references on both
sides don't duplicate.

No schema change (`references` is already `list[Reference]`).

---

## Item 3 — Humble-authoritative removal, "same game" matching cascade, `invalid:` quarantine

### Model change — `src/game_collections/models.py`

Add to `GameList`:
```python
invalid: list[Game] = []
```
Same shape as `games`, no separate uniqueness constraint needed (quarantined
entries don't need to stay unique against each other, only tracked). Follow
whatever existing pattern `GameList` uses for other optional/empty-default
list fields (check `render_game_list_yaml` / `model_dump` exclusion rules
used for e.g. `references`/`pick_quota` today so `invalid: []` doesn't get
force-written into every list that doesn't use it). Regenerate
`schemas/game-list.schema.json` (`uv run game-collections schema`) —
required per CLAUDE.md for any public list model change.

Document the new field in `lists/README.md`: what it means (games a Humble
re-crawl no longer lists, kept for recovery rather than deleted) and that
`invalid` entries must be excluded from ownership/eligibility/sync
consideration everywhere `games` is currently read for that purpose — audit
`launchers/steam/adapter.py`, `completion.py`, `apply/metadata.py` and
confirm none of them iterate `GameList.games` in a way that would need an
explicit `+ invalid` exclusion (they shouldn't, since `invalid` is a new,
separate field — this is a confirmation pass, not expected to require code
changes there).

### Matching cascade — new helper in `sources/common.py`

Add a dependency: `rapidfuzz` (`pyproject.toml`, main dependencies — a normal
runtime need, not test/tui-extra-only, since crawlers run unattended).

New helper, e.g. `_match_game(fresh_game: Game, candidates: list[Game]) -> Game | None`,
consulted in this order, first hit wins, matched candidate is removed from
the mutable `candidates` pool by the caller:
1. **Id overlap** — `set(fresh_game.ids) & set(candidate.ids)` non-empty.
2. **Exact name** — `fresh_game.name.casefold() == candidate.name.casefold()`
   (today's only check).
3. **Normalized name** — `normalized_title(fresh_game.name) == normalized_title(candidate.name)`
   reusing `sources/storefronts.normalized_title` (import across source
   packages already happens elsewhere, e.g. `search.py`).
4. **Fuzzy similarity** — `rapidfuzz.fuzz.WRatio(fresh_game.name, candidate.name) >= THRESHOLD`
   over remaining unmatched candidates, picking the highest-scoring one above
   threshold if any. Start with `THRESHOLD = 90` as a named module constant
   with a one-line comment on why (empirically reasonable for
   edition/subtitle noise like "Foo: Deluxe Edition" vs "Foo" — not tuned
   against a real dataset, so call this out as an initial value, adjustable
   in a follow-up if the live validation run in Item 4 surfaces false
   positives/negatives).

### `merge_game_list` rewrite — `sources/common.py`

New signature: `merge_game_list(existing: GameList | None, fresh: GameList, *, authoritative: bool = False) -> GameList`.

- `existing is None` → return `fresh` unchanged (as today).
- `authoritative=False` (default) → **current behavior exactly**, existing
  tests keep passing unchanged: union of games, matched by `name.casefold()`
  only (keep it simple/backward-compatible for any future non-Humble
  caller), never removes, `invalid` passed through unchanged from existing
  (untouched, not created).
- `authoritative=True` (Humble's mode) → use the 4-tier cascade above:
  - Build a mutable candidate pool from `existing.games + existing.invalid`
    (so a previously-quarantined game can move back to `games` if it
    reappears in a later crawl).
  - For each `fresh` game (in fresh's order), try to match against the pool;
    matched → keep the **candidate's** `Game` (preserving any `ids`/`group`
    state) at that position; unmatched → the fresh `Game` is genuinely new,
    appended.
  - Any pool entries never matched to a fresh game become the new
    `invalid` list (replacing the old one — already-invalid entries that
    still don't match stay invalid; ones that matched moved back to
    `games`).
  - `references` always goes through Item 2's append-merge, regardless of
    `authoritative`.

### Wiring — `humblebundle/crawler.py`

`_write_merged_game_list` / both `write_humble_offer` call sites pass
`authoritative=True` unconditionally (per the user's explicit choice — no
provenance check).

### Tests

- `tests/test_sources_common.py`: cascade unit tests (id-only match with
  differing names, exact-name match, normalized-name match e.g. dash/colon
  differences, fuzzy match e.g. "Foo: Deluxe Edition" vs "Foo", no-match →
  new game added and old one quarantined), `invalid` round-trip (a
  previously-invalid game reappearing in fresh moves back to `games`),
  `authoritative=False` still behaves exactly as today (regression guard).
- `tests/test_humblebundle_crawler.py`: integration case — re-crawl that
  drops a previously-listed game quarantines it into `invalid:` instead of
  deleting it or leaving it in `games`.
- `tests/test_models.py` (or wherever `GameList` is tested): `invalid`
  field defaults to `[]`, round-trips through YAML.
- `tests/test_schema.py` must still pass after regeneration (drift check).

---

## Item 4 — `--git` autostash flag + live scrape-and-compare validation run

### `--git` flag

Add a `--git` boolean flag (default `False`) to `scrape humblebundle` and
`scrape isthereanydeal` in `src/game_collections/cli.py`. Behavior, using
`subprocess.run([...], check=True, text=True, capture_output=True)` calls
matching the style already used in `scripts/tag_backup.py`:

- Before the scrape body runs: `git stash push --include-untracked -m "pre-scrape autostash"`.
  Detect the no-op case (git prints "No local changes to save" and creates
  no stash entry) so the restore step doesn't try to pop a stash that was
  never created.
- Run the existing scrape logic unchanged.
- In a `finally` block (so it still runs on scrape failure): if a stash was
  created, `git stash pop`. If the pop fails (conflict with the scrape's own
  new/changed files), print a clear error pointing at `git stash list` /
  `git stash show -p` for manual resolution rather than silently dropping
  the stash or raising an opaque traceback.
- This flag does **not** commit anything — committing scrape output stays a
  manual/agent action via the existing `commit-with-lplp-style` flow.

**Tests:** `tests/test_cli.py` — mock/patch the subprocess calls (no real
git operations in unit tests) to verify: stash-then-scrape-then-pop ordering,
no-op detection when the tree is already clean, and that pop still runs when
the scrape body raises.

### Live validation run

After items 1-3 are implemented and tested, actually run:
```console
env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections scrape humblebundle --git
env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections scrape isthereanydeal --git
```
against one or two real overlapping bundles (pick a recent Humble Choice/
Games bundle also present on isthereanydeal), then diff the resulting
`lists/humblebundle/...` output for tier order, `references`, and any
`invalid:` entries. I will confirm with the user before running anything
that writes files or touches the network, and report/fix anything the diff
surfaces (e.g. threshold tuning for the fuzzy tier) as a follow-up within
this same task rather than opening a new todo item, unless what's found is
large enough to warrant its own separate item.

---

## Verification (all items)

```console
env UV_CACHE_DIR=/tmp/uv-cache uv run pytest
env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_humblebundle_crawler.py tests/test_sources_common.py tests/test_isthereanydeal_crawler.py tests/test_cli.py tests/test_schema.py -q
env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections validate
env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections schema   # must show only the intended invalid: field addition
```
Plus the live scrape-and-compare run described in Item 4, gated on explicit
confirmation before it executes.
