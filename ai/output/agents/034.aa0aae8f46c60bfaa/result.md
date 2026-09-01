No isthereanydeal archive exists for `dread-and-dark-fantasies-rpg-collection` (only humblebundle/bundle has it) — confirming ITAD hasn't crawled/archived that bundle at all yet, so `_existing_list_match` skip only prevented the *list* write in a hypothetical run, and the archive-writing lines run unconditionally before the skip check regardless.

## Report

**1-2. Skip message and skip-check logic**

File: `src/game_collections/sources/isthereanydeal/crawler.py`

```python
# lines 402-419
def _existing_list_match(lists_root: Path, provider_slug: str, real_slug: str) -> Path | None:
    """Best-effort dedup check: is this bundle already covered by a dedicated scraper?

    Matches by substring, not exact path, since e.g. Humble's own directories
    are date-prefixed (`2026-07-10_squad-goals`) rather than the bare slug.
    """
    provider_root = lists_root / provider_slug
    if not provider_root.is_dir():
        return None
    # end if
    needle = real_slug.casefold()
    for path in sorted(provider_root.rglob("*")):
        if needle and needle in path.name.casefold():
            return path
        # end if
    # end for
    return None
# end def _existing_list_match
```

Plus a special-cased Humble Choice matcher `_existing_choice_match` (lines ~370-399, matches monthly-title pattern against `lists/humblebundle/choice/<YYYY-MM>.yml`).

Both are called in `write_itad_offer` (lines 422-441):
```python
existing = _existing_choice_match(lists_root, archive.provider_slug, offer.summary) or _existing_list_match(
    lists_root, archive.provider_slug, archive.real_slug
)
if existing is not None:
    log(f"  Skipped {archive.real_slug}: already covered by {existing}")
    return tuple(written)
# end if
```

This is purely a filesystem/string-based dedup — it checks whether `real_slug` appears as a substring of any file/directory name under `lists/<provider_slug>/` (`humblebundle` for ITAD's `provider_slug`), i.e. does a matching `lists/humblebundle/...` path already exist on disk. It is *not* driven by any model field. Note: the ITAD archive (`archives/isthereanydeal/bundle/.../metadata.json` + `source.json`) is written unconditionally at lines 430-434, **before** this skip check — only the public `lists/isthereanydeal/bundle/...` YAML write is skipped.

**3. No provenance/crawler-tracking field exists**

`src/game_collections/models.py` has no `crawlers`/`sources` list field anywhere. The only provenance mechanism is `GameList.references: list[Reference]` (line 136), and `Reference` (lines 108-126) has just `name`, `path`, `url` — no structured crawler identifier. `src/game_collections/sources/common.py`'s `_merged_references` (lines 75-87) appends new references from a fresh crawl onto an existing list's references without dropping either side, but this is only invoked via `merge_game_list`, which the ITAD skip path never reaches (it returns early instead of loading/merging the existing Humble list).

**4. Current schema for `lists/<provider>/bundle/...` entries**

`GameList` (models.py lines 129-174): `schema_version` (alias `schema`, `Literal[1]`), `name`, `tier: int | None`, `pick_quota: int | None`, `references: list[Reference]`, `games: list[Game]`, `invalid: list[Game]`. CLAUDE.md line 41: "`archives/`: normalized metadata + raw source archives for scraped/imported lists (per-source subdirectory), referenced from the matching list's `references` field." Both Humble (`humblebundle/crawler.py` lines 333-336, 383-389) and ITAD (`isthereanydeal/crawler.py` lines 472-475, 512-515) populate `references` with a source-offer URL Reference plus "Crawl metadata"/"Crawl source" path References pointing into their own `archives/<provider>/...` — each crawler only ever references its *own* archive, never the other's.

**5. Resolved-id-per-shop detection**

`src/game_collections/sources/isthereanydeal/parser.py`, `_log_unmatched_shop_keys` (lines 284-306), calling `_resolve_urls` (lines 309+). It builds `resolved_providers` from ids not prefixed `unresolved:`, then for each shop key without a hint match logs: `f"  bundle {bundle_id} {slug!r}: shop {shop_id} ({shop_name}) has no matching resolved id (resolved: {sorted(resolved_providers) or 'none'})"` (lines 300-303). This is a corroboration-only log line (comment at lines 270-274), independent of file-existence dedup — it fires per-game during parsing regardless of whether the bundle's list gets skipped as "already covered."

**6. Archives on disk**

`archives/humblebundle/bundle/2026-08-31_dread-and-dark-fantasies-rpg-collection/` exists; `archives/isthereanydeal/bundle/` has no entry for this slug — ITAD has apparently never actually archived this bundle, so today's dedup can't be cross-checking any ITAD-side provenance marker; it's solely "does a `lists/humblebundle/**` path containing this slug substring exist."