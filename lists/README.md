# Game lists

Each `.yml` file below this directory defines one portable game collection. Its stable ID is its path relative to this directory without the `.yml` suffix. For example, `valve/the-orange-box.yml` is `valve/the-orange-box`.

Files are validated with strict Pydantic models. The committed JSON Schema at `../schemas/game-list.schema.json` is generated from those same models and each list references it for IDE completion.

```yaml
# yaml-language-server: $schema=../../schemas/game-list.schema.json
schema: 1
name: Example collection
games:
  - name: Team Fortress 2
    ids: [steam:440]
```

Names are required for reviewability. Qualified IDs are authoritative and use `<provider>:<provider-id>`. A game can carry multiple IDs when it is available from multiple storefronts.

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
