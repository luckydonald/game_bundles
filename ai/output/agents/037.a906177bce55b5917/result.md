## Summary

### 1. The duplicate-check validator

File: `/home/user/git/luckydonald/game_collections/src/game_collections/models.py`

```python
147	    @model_validator(mode="after")
148	    def validate_games(self) -> Self:
149	        names = [game.name.casefold() for game in self.games]
150	        if len(names) != len(set(names)):
151	            raise ValueError("list contains duplicate game names")
152	        # end if
153	
154	        identities = [identifier.compact() for game in self.games for identifier in game.qualified_ids]
155	        if len(identities) != len(set(identities)):
156	            raise ValueError("list contains duplicate qualified game IDs")
157	        # end if
```
(`models.py:147-157`, inside `class GameList`, lines 129-178)

**What "qualified game ID" means and how it's computed:**

- A `Game` (lines 63-105) has an `ids: list[NonEmptyString]` field (min length 1) holding compact strings like `"steam:440"`.
- `Game.qualified_ids` (lines 93-97) parses each raw string in `self.ids` via `QualifiedGameId.parse(raw)`.
- `QualifiedGameId` (lines 30-51) is `provider: NonEmptyString` + `value: NonEmptyString`. `.parse()` splits the raw string on the first `:` (`provider, separator, value = raw.partition(":")`), validating `provider` against `PROVIDER_PATTERN = ^[a-z][a-z0-9-]*$` (line 12) and requiring both `separator` and `value` to be non-empty (lines 39-41).
- `.compact()` (lines 46-49) reassembles it as `f"{self.provider}:{self.value}"`.
- The `GameList.validate_games` check builds `identities` as the flattened list of `.compact()` strings across **every game's `qualified_ids`** in `self.games`, and errors if any compact string repeats **anywhere in the list** (i.e. across different `Game` entries, not just within one). This is distinct from `Game.validate_ids` (lines 73-91), which only checks duplicates *within a single game's own* `ids`/`requires` lists.

So a "qualified game ID" is simply the `provider:value` pair from a game's `ids` entries (e.g. `steam:440`, `humble:some-machine-name`), and the bug this guards against is the same storefront ID being attached to two different `Game` entries within one `GameList`.

### 2. Where `GameList` is constructed/validated in the Humble Bundle scraper

File: `/home/user/git/luckydonald/game_collections/src/game_collections/sources/humblebundle/crawler.py`

- Two `GameList(...)` construction sites, one for Choice-bundle pick-tiers and one for classic tiered bundles:
  - `crawler.py:328-340` — builds `game_list` from `pool_games` (deduped via `seen_pool_ids` at lines 309-318) for each Choice pick option.
  - `crawler.py:380-397` — builds `game_list` from `games` per tier (deduped via `seen_ids` at lines 349-358).
- Both then call `_write_merged_game_list(game_list, path, lists_root, repository_root)` (defined at `crawler.py:271-285`):
  ```python
  271	def _write_merged_game_list(game_list: GameList, path: Path, lists_root: Path, repository_root: Path) -> None:
  ...
  282	    existing = load_game_list(path, lists_root).data if path.exists() else None
  283	    merged = merge_game_list(existing, game_list, authoritative=True)
  284	    atomic_write(path, render_game_list_yaml(merged, path, repository_root))
  ```
  - `load_game_list` (in `/home/user/git/luckydonald/game_collections/src/game_collections/lists.py:52-69`) is what actually raises the "invalid game list ..." wrapper message:
    ```python
    63	    try:
    64	        data = GameList.model_validate(raw)
    65	    except ValidationError as error:
    66	        raise ListLoadError(f"invalid game list {path}:\n{error}") from error
    ```
    This is the source of the exact error format seen in `/home/user/git/luckydonald/game_collections/ai/errors/4.txt`:
    ```
    error: https://www.humblebundle.com/games/dread-and-dark-fantasies-rpg-collection: invalid game list lists/humblebundle/bundle/2026-08-31_dread-and-dark-fantasies-rpg-collection/tier-1.yml:
    1 validation error for GameList
      Value error, list contains duplicate qualified game IDs [...]
    ```
  - Note `load_game_list` here is loading the **already-committed existing file** at `path` (line 282, `if path.exists()`) before merging in the freshly-crawled `game_list` — so this particular failure mode is triggered by an already-written/committed list file that itself contains duplicate qualified IDs (e.g. from a prior buggy merge or hand-edit), not necessarily by the freshly-crawled data.
  - `merge_game_list` (in `/home/user/git/luckydonald/game_collections/src/game_collections/sources/common.py:184-231`) combines `existing` and `fresh` via `.model_copy(update=...)` (lines 214, 228-230), which does **not** re-run Pydantic validators — so a merge itself could silently produce duplicate qualified IDs across the merged `games`/`invalid` split without being caught until the file is loaded again.

### 3. Related fields feeding into / adjacent to the qualified-ID computation

- `Game.ids: list[NonEmptyString]` (`models.py:67`) — the field actually used for `qualified_ids`/the duplicate check in `GameList.validate_games`.
- `Game.requires: list[NonEmptyString]` (`models.py:71`) — "Qualified IDs of other games that must be owned/present for this entry to make sense, e.g. the free base game a DLC entry needs." Parsed the same way via `QualifiedGameId.parse` and exposed as `Game.qualified_ids_required` (`models.py:99-103`), and checked for **internal** duplicates in `Game.validate_ids` (lines 82-89, `"game contains duplicate qualified required IDs"`). Importantly, `requires` is **not** included in the `GameList.validate_games` cross-game duplicate check (that check only iterates `game.qualified_ids`, not `qualified_ids_required`).
- `Game.group: GameGroup | None` (`models.py:68`, `GameGroup` at lines 54-60) — provenance link (`id`, `name`) for games split out of one compound Humble offer; used by `merge_game_list`/`find_matching_game` for identity matching but not part of the qualified-ID identity itself.
- `PROVIDER_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")` (`models.py:12`) — constrains the storefront/provider prefix (e.g. `steam`, `humble`, `gog`) used in qualified IDs.
- In the Humble crawler, `_item_all_ids(item)` (`crawler.py:249-255`) and `_games_for_item(item)` (`crawler.py:258-268`) are what produce the raw `ids`/`requires` lists (from `item.resolution.ids` / `item.resolution.requires` / `split.ids`) that ultimately become `Game.ids`/`Game.requires` before `GameList` construction — worth checking if the underlying bug (dupe qualified IDs) originates there, since `seen_pool_ids`/`seen_ids` dedupe only guards against the *same Humble item* being added twice, not against two different items resolving to the same qualified storefront ID.