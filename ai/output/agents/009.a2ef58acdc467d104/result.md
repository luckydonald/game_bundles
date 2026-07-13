Now I have all the details needed. Here is the full report.

## 1. Where each source decides the tier filename

### humblebundle
File: `/home/user/git/luckydonald/game_collections/src/game_collections/sources/humblebundle/crawler.py`, function `write_humble_offer` (lines 247-306), the decisive block is lines 266-285:

```python
for index, tier in enumerate(archive.tiers):
    ...
    name = archive.name if archive.kind == "choice" else f"{archive.name} — {tier.name}"
    if archive.kind == "choice":
        path = list_directory / f"{key}.yml"
    else:
        prefix = "entire-" if index == 0 else ""
        path = list_directory / f"{prefix}{tier.item_count}-item-bundle.yml"
    # end if
```

- Naming convention (only for `kind == "bundle"`, i.e. non-Choice Humble bundles): `{item_count}-item-bundle.yml`, and the **first** tier (`index == 0`, the cheapest/base tier which Humble always makes cumulative) gets an `entire-` prefix: `entire-{item_count}-item-bundle.yml`. Subsequent tiers are plain `{item_count}-item-bundle.yml` (item_count is the *cumulative* running item count for that tier, taken straight from `HumbleTier.item_count`, not a tier index).
- Choice-kind offers ignore all this and always write a single `{key}.yml` (no tier files at all — Choice only ever gets one list).
- Note: legacy files on disk under `lists/humblebundle/bundle/**` still contain old `tier-1.yml`, `tier-2.yml`, ... names (e.g. `lists/humblebundle/bundle/2015-06-15_twitche3/tier-1.yml`), meaning the naming scheme changed at some point — the *current* writer no longer produces `tier-N.yml` for Humble, only the `(entire-)?N-item-bundle.yml` form.
- `HumbleTier.identifier` (see `humblebundle/models.py:71`) is not used for the filename at all in the current writer.

### greenmangaming
File: `/home/user/git/luckydonald/game_collections/src/game_collections/sources/greenmangaming/crawler.py`, function `write_gmg_offer` (lines 233-275), decisive line:

```python
path = list_directory / f"{tier.identifier}.yml"    # line 260
```

- The filename is exactly `GmgTier.identifier` + `.yml` — no separate naming logic in the crawler at all.
- `identifier` itself comes from parsing the live bundle page in `/home/user/git/luckydonald/game_collections/src/game_collections/sources/greenmangaming/parser.py`, function `parse_bundle_page`, lines 213-253. It's extracted straight off the site's HTML:
  - `TIER_ID_PATTERN = re.compile(r'data-upgrade-tier-id="([^"]+)"')` (line 41)
  - `identifier = identifier_match.group(1)` (line 225) — this is whatever GreenManGaming's own markup encodes in `data-upgrade-tier-id`.
  - On the live site (confirmed by files under `lists/greenmangaming/bundle/**`, e.g. `2026-06-02_master-builders-collection/tier-1.yml`...`tier-4.yml`) this value happens to already look like `tier-1`, `tier-2`, etc., but that's a property of GMG's markup, not something this repo's code constructs — there is no in-repo "single-tier vs multi-tier" special case (unlike Humble's `entire-` prefix).

### isthereanydeal
File: `/home/user/git/luckydonald/game_collections/src/game_collections/sources/isthereanydeal/crawler.py`, function `write_itad_offer` (lines 412-464), decisive line:

```python
path = list_directory / f"{tier.identifier}.yml"    # line 449
```

- Again just `ItadTier.identifier + ".yml"`, and `identifier` is constructed purely in the parser as `f"tier-{len(tiers) + 1}"` in two places in `/home/user/git/luckydonald/game_collections/src/game_collections/sources/isthereanydeal/parser.py`:
  - `parse_bundle_detail_json` (function starts line 325), tier construction at line 442: `identifier=f"tier-{len(tiers) + 1}"`.
  - `parse_bundle_detail_page` (function starts line 523; the legacy HTML fallback path), tier construction at line 618: `identifier=f"tier-{len(tiers) + 1}"`.
- So ITAD always produces `tier-1.yml`, `tier-2.yml`, ... with 1-based, strictly incrementing numbering as tiers are appended to the (cumulative) `tiers` list — no `entire-` special case, single or multi tier alike just get `tier-1.yml`, `tier-2.yml`, etc.
- Note: no ITAD list files currently exist under `lists/isthereanydeal/` in this working tree (0 results from the `find`), so this path is presently unexercised on disk, but the code is as above. There is also dedup logic (`_existing_choice_match` line 366, `_existing_list_match` line 392) that can skip writing an ITAD offer entirely if it's already covered by the dedicated Humble/GMG scrapers.

### dailyindiegame
File: `/home/user/git/luckydonald/game_collections/src/game_collections/sources/dailyindiegame/crawler.py`, function `write_dig_offer` (lines 253-289), decisive line:

```python
path = list_directory / f"{archive.machine_name}.yml"    # line 276
```

- DailyIndieGame bundles have **no tier concept whatsoever** — `DigArchive` (in `dailyindiegame/models.py`) has a flat `items: list[DigItem]`, no `tiers` field at all. One list file per bundle, named by its `machine_name` (confirmed on disk: `lists/dailyindiegame/bundle/2352.yml`, `2351.yml`, etc. — these numbers are the bundle's `machine_name`/id, from `bundle_number()` in `dailyindiegame/parser.py`). There is nothing to "recognize" for tier ordering here.

## 2. Is tier number stored in the list YAML / `GameList` model, or derived from filename only?

Purely from the filename. The public `GameList` Pydantic model in `/home/user/git/luckydonald/game_collections/src/game_collections/models.py` (lines 101-123) has only these fields:

```python
class GameList(StrictModel):
    schema_version: Literal[1] = Field(alias="schema", serialization_alias="schema")
    name: NonEmptyString
    references: list[Reference] = Field(default_factory=list)
    games: list[Game] = Field(min_length=1)
```

No `tier`, `rank`, `identifier`, or `item_count` field exists anywhere in `GameList`/`Game`/`Reference`. The per-tier `identifier`/`item_count`/`name` do exist, but only in each source's internal **archive** model (`HumbleTier`, `GmgTier`, `ItadTier` in each source's `models.py`, all with `identifier: NonEmptyString`, `name: NonEmptyString`, `item_count: int`) — those are written to `metadata.json` (the crawl archive under `archive_root`), never into the public list YAML. The list YAML's `name` field does embed the tier's human name as a suffix (e.g. `f"{archive.name} — {tier.name}"`), but that's free text, not a structured/parseable tier number. So today, tier ordering for the game-list files is 100% derived from the filename by consumers.

## 3. How `steam/adapter.py` parses tier ordering from filenames

File: `/home/user/git/luckydonald/game_collections/src/game_collections/launchers/steam/adapter.py`

Patterns (lines 34-35):
```python
TIER_STEM_PATTERN = re.compile(r"^tier-(?P<rank>[0-9]+)$")
ITEM_BUNDLE_STEM_PATTERN = re.compile(r"^(?:entire-)?(?P<rank>[0-9]+)-item-bundle$")
```

Parsing function `_tier_identity` (lines 299-309):
```python
def _tier_identity(list_id: str) -> tuple[str, int] | None:
    parent, separator, stem = list_id.rpartition("/")
    if not separator:
        return None
    # end if
    match = TIER_STEM_PATTERN.fullmatch(stem) or ITEM_BUNDLE_STEM_PATTERN.fullmatch(stem)
    if match is None:
        return None
    # end if
    return parent, int(match.group("rank"))
# end def _tier_identity
```

- `list_id` is a path-like ID (e.g. `humblebundle/bundle/2026-06-17_upload-vr-summer-2026/5-item-bundle`); it's split on the last `/` into `parent` (the bundle directory) and `stem` (the filename without `.yml`).
- The stem is matched against `tier-(\d+)$` first, then `(entire-)?(\d+)-item-bundle$`. Either way the captured `rank` becomes the tier's ordering integer — for `tier-N` filenames rank = N directly; for the `item-bundle` filenames rank is actually the **cumulative item count**, not a small 1/2/3 tier index (this works because higher item-count is always the higher/more-inclusive tier).
- If neither regex matches, `_tier_identity` returns `None` and the list is treated as tier-less (always included if eligible when `tier_mode == "highest"`, per `_selected_list_ids` lines 183-217).
- `_selected_list_ids` (lines 183-217) uses `_tier_identity` to group by `parent`, raises `ValueError` on duplicate `(parent, rank)` pairs ("ambiguous tier rank"), and for `tier_mode == "highest"` keeps only the highest-`rank`, eligible list per parent directory.

This confirms the adapter only recognizes exactly two filename shapes: `tier-<int>` and `(entire-)?<int>-item-bundle`. Any new naming scheme (or an ITAD-specific one, since ITAD already emits `tier-N.yml` and would already be recognized) needs either to match one of these two regexes or the adapter's patterns/`_tier_identity` need updating.

## Full `models.py` (verbatim)

Already reproduced in full above from the Read; restating the complete file content for convenience — path `/home/user/git/luckydonald/game_collections/src/game_collections/models.py`, all 132 lines, containing: `LIST_ID_PATTERN`, `PROVIDER_PATTERN`, `NonEmptyString`, `ReferencePath`, `StrictModel` (base, `extra="forbid", strict=True`), `QualifiedGameId` (`provider`, `value`, plus `parse`/`compact`), `Game` (`name`, `ids: list[NonEmptyString]`, `qualified_ids` property, dup-ID validator), `Reference` (`name`, `path: ReferencePath | None`, `url: AnyHttpUrl | None`, target-required validator), `GameList` (`schema_version` aliased `schema`, `name`, `references: list[Reference]`, `games: list[Game]`, dup-name/dup-ID validator), and module function `validate_list_id`. This is the file where a new tier-related field (e.g. `tier: int | None` or `tier_rank`) would need to be added if you want tier info stored in the YAML itself instead of derived from the filename.