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

Validate all lists with:

```console
game-collections validate
```

Regenerate the IDE schema after changing the Pydantic contract:

```console
game-collections schema
```

## Generated Humble lists

`game-collections scrape humblebundle` writes current Choice to `humblebundle/choice/YYYY-MM.yml` and active bundle tiers below `humblebundle/bundle/YYYY-MM-DD_<bundle>/`.

Tier counts and names follow Humble's advertised cumulative tiers, while the standard list contains games only. Coupons, subscription perks, and other bonuses are retained in the matching `archives/humblebundle/` metadata. A game whose storefront identity could not be selected uses `unresolved:humblebundle:<machine-name>` and remains ineligible for launcher synchronization until the reviewed mapping is updated.

Each generated Humble list references its offer URL plus the matching normalized metadata and raw source archive files.
