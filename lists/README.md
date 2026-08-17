# Game lists

Each `.yml` file below this directory defines one portable game collection. Its stable ID is its path relative to this directory without the `.yml` suffix. For example, `valve/the-orange-box.yml` is `valve/the-orange-box`.

Files are validated with strict Pydantic models. The committed JSON Schema at `../schemas/game-list.schema.json` is generated from those same models and each list references it for IDE completion.

```yaml
# yaml-language-server: $schema=../../schemas/game-list.schema.json
schema: 1
name: Example collection
references:
  - name: Collection notes
    path: ../../archives/example/metadata.json
  - name: Store page
    url: https://example.com/collection
games:
  - name: Team Fortress 2
    ids: [steam:440]
```

Names are required for reviewability. Qualified IDs are authoritative and use `<provider>:<provider-id>`. A game can carry multiple IDs when it is available from multiple storefronts.

Optional `references` appear before `games`. Each named reference contains a local/repository `path`, an HTTP(S) `url`, or both. Paths may be relative to the list file (such as `../../../archives/.../metadata.json`) or repository-root-relative with an optional leading slash (such as `/archives/.../source.json`). The generated JSON Schema marks these values as file paths for IDE support.

An optional `invalid` list, shaped exactly like `games`, may follow it. It holds games an authoritative re-crawl (currently only `scrape humblebundle`) no longer lists - quarantined there instead of being deleted, and moved back into `games` automatically if a later crawl lists them again. `invalid` entries are never treated as owned, eligible, or synced; nothing reads them except the next merge. Hand-authored lists normally omit this field entirely.

Validate all lists with:

```console
game-collections validate
```

To create a list from names first, omit `ids` (or use an empty list) in a draft outside the validated `lists/` tree, then complete it in place:

```console
game-collections complete my-draft.yml
game-collections complete --provider all my-draft.yml
game-collections complete --store gog,epic --mode missing my-draft.yml
```

Completion defaults to Steam and `--mode blank`, which searches only games with an empty `ids` list or no proper ID. Use `missing` to add selected stores not previously attempted, `unresolved` to also retry `unresolved:store:<store>:*` failures, or `refetch_all` to refresh every selected store for every game. Repeat `--provider`/`--store`, comma-separate values, or pass `all`. Existing IDs for unselected stores are preserved. Unique exact title matches are filled automatically, and ambiguous results are presented for selection.

`--provider isthereanydeal --mode unresolved` is different: instead of a storefront title search, it solves `unresolved:source:isthereanydeal:<bundle-id>:<slug>` markers (left by isthereanydeal-sourced lists below) via that game's own isthereanydeal.com detail page and its cross-store deal listing; see the root `README.md` for details.

Regenerate the IDE schema after changing the Pydantic contract:

```console
game-collections schema
```

## Generated Humble lists

`game-collections scrape humblebundle` writes current Choice to `humblebundle/choice/YYYY-MM.yml` and active bundle tiers below `humblebundle/bundle/YYYY-MM-DD_<bundle>/`.

Tier counts and names follow Humble's advertised cumulative tiers, while the standard list contains games only. Coupons, subscription perks, and other bonuses are retained in the matching `archives/humblebundle/` metadata. A game whose storefront identity could not be selected uses `unresolved:source:humblebundle:<machine-name>` and remains ineligible for launcher synchronization until the reviewed mapping is updated.

Each generated Humble list references its offer URL plus the matching normalized metadata and raw source archive files; references are appended across re-crawls, never overwritten, so a reference another source previously added (e.g. an isthereanydeal mirror URL) survives a later Humble crawl.

Humble is authoritative for its own bundles: re-crawling merges into any already-committed list rather than overwriting it, matching games via storefront ID overlap, exact name, normalized name, and finally fuzzy title similarity (in that order), so an edition-subtitle or punctuation change doesn't lose a game's existing IDs. A game the fresh crawl no longer lists is quarantined into `invalid` (see above) rather than deleted.

Humble's own site doesn't expose past Choice months to guests, so historical months are backfilled separately with `scripts/backfill_humble_choice.py`, which sources titles and per-game membership links from the community mirror at `dangarbri.tech/humblechoice` and resolves Steam IDs the same way `complete` does. Its archive JSON is a best-effort partial record (title, resolved IDs, per-game link) rather than the full official crawl payload the live scraper stores. Run it with `--month YYYY-MM`, `--from`/`--to`, or `--all`; see `--help` for details.

## Generated DailyIndieGame lists

`game-collections scrape dailyindiegame` writes one list per bundle to `dailyindiegame/bundle/<N>.yml`, where `<N>` is the bundle's own numeric ID on the site. Every game already carries a direct `steam:<appid>` ID from the bundle page, so there's no `unresolved:*` state for this source. Each list references its bundle page URL plus the matching normalized metadata and raw source archive files below `archives/dailyindiegame/bundle/<N>/`.
