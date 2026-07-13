## Report

### 1. How `src/game_collections/sources/humblebundle/` handles Choice bundles today

**No "pick N of pool" mechanic exists anywhere in this source.** It only ever emits the full pool as one list, implicitly assuming the buyer got everything.

- `src/game_collections/sources/humblebundle/parser.py:468-577` (`parse_choice_page`) parses the live Choice/membership page and always builds **exactly one** `HumbleTier` for the whole month, with `item_count=len(items)` and `items=items` covering the *entire* offered pool (`parser.py:561-569`). There is no field, no parsed "how many you're allowed to pick" count, no per-item pick/point cost — Humble Choice actually lets you pick N (historically 9–12) of ~12 games, but that constraint is nowhere read out of the embedded JSON here.
- `src/game_collections/sources/humblebundle/models.py:68-85` (`HumbleTier`) only models a **cumulative** tier concept ("pay $X, get these N items", used for the Games-bundle case where tiers really are cumulative all-or-nothing supersets). It has `item_count` + `items` and a validator that just checks they match (`models.py:77-83`); there is no `pick_count`, `min_picks`, `max_picks`, or any "subset of this pool" field. For `kind="choice"` this same model is reused for the single, all-inclusive tier — i.e. Choice is force-fit into the "cumulative tier" shape even though its actual mechanic (pick N of M) is different and unmodeled.
- `src/game_collections/sources/humblebundle/crawler.py:266-304` (`write_humble_offer`) turns each `archive.tiers[i].items` into a flat `Game` list and writes one `.yml` per tier. For `kind == "choice"` there's only the one tier, so it writes a **single list containing every game in that month's Choice pool** (`crawler.py:279-284`, path `humblebundle/choice/{key}.yml`) — there is no representation of "you only actually own N of these."
- `src/game_collections/sources/humblebundle/resolver.py` resolves storefront IDs per distinct item across all tiers (`resolve_archive`, `resolver.py:247-299`) — again pool-wide, no pick-count awareness.
- Tests confirm this: `tests/test_humblebundle_parser.py:150-222` and `tests/test_humblebundle_crawler.py:39-160` construct/assert a single `choice` tier with all sample items and check the writer produces `lists/humblebundle/choice/2026-07.yml` containing that whole tier — none of the tests reference a pick count, "choice count", or partial-ownership concept. Grepping both test files for "choice" (see command output) turns up only the tier/page machinery, nothing pick-related.
- Real generated output confirms the pool-as-one-list assumption in practice: `lists/humblebundle/choice/*.yml` (e.g. `2026-07-13`'s current month) each contain the full monthly game list with no pick-count metadata.

So: today's Humble Choice handling is **"assume you got the whole pool,"** by construction — never a real "pick N of M" model.

### 2. `src/game_collections/models.py` — verbatim

Read in full above; key excerpt of the parts relevant to a BYOB feature:

```python
# src/game_collections/models.py:54-77
class Game(StrictModel):
    """A named game with one or more storefront identities."""

    name: NonEmptyString
    ids: list[NonEmptyString] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_ids(self) -> Self:
        parsed = [QualifiedGameId.parse(raw) for raw in self.ids]
        compact = [identifier.compact() for identifier in parsed]
        if len(compact) != len(set(compact)):
            raise ValueError("game contains duplicate qualified IDs")
        self.ids = compact
        return self

    @property
    def qualified_ids(self) -> tuple[QualifiedGameId, ...]:
        return tuple(QualifiedGameId.parse(raw) for raw in self.ids)
```

```python
# src/game_collections/models.py:101-123
class GameList(StrictModel):
    """The complete contents of one ``lists/**/*.yml`` file."""

    schema_version: Literal[1] = Field(alias="schema", serialization_alias="schema")
    name: NonEmptyString
    references: list[Reference] = Field(default_factory=list)
    games: list[Game] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_games(self) -> Self:
        names = [game.name.casefold() for game in self.games]
        if len(names) != len(set(names)):
            raise ValueError("list contains duplicate game names")
        identities = [identifier.compact() for game in self.games for identifier in game.qualified_ids]
        if len(identities) != len(set(identities)):
            raise ValueError("list contains duplicate qualified game IDs")
        return self
```

Full file also included above at `src/game_collections/models.py:1-133` (`StrictModel`, `QualifiedGameId`, `Reference`, `validate_list_id`). Nothing in this model expresses "own N of these M" — `GameList.games` is unconditionally treated as one flat, fully-owned (or `--mode any`-partially-matched-but-unstructured) set with no pick/quota semantics or per-item price/point-cost concept.

### 3. Existing "subset/pick N of M" concepts elsewhere in the repo

Nothing generic exists (no `any_of`/`partial`/`pick_count` field anywhere in `src/game_collections`), but there **is** a directly relevant, partially-modeled precedent for BYOB specifically in the isthereanydeal (ITAD) aggregator source, and an explicit open TODO about it:

- **ITAD models it as "byob" already, but intentionally does not capture the pick-count/pricing structure:**
  - `src/game_collections/sources/isthereanydeal/models.py:165` — `ItadListSummary.byob: bool` (a flag from the discovery list API, currently just stored, not acted on).
  - `src/game_collections/sources/isthereanydeal/models.py:39-56` (`ItadTier` docstring) explicitly states: *"a single synthetic tier covering every game in a 'Build Your Own'/mix-and-match bundle with no fixed price (`price` is `None` there — the per-game marginal pricing table isn't modeled)."*
  - `src/game_collections/sources/isthereanydeal/parser.py:528-534` (`parse_bundle_detail_page` docstring): *"A single flat-price bundle or a 'Build Your Own'/mix-and-match bundle (`byob` in the list API) both render as exactly one tier-name header covering every game, so no special-casing is needed for either shape."* — i.e. BYOB is deliberately collapsed to "one tier, all games," same all-or-pool pattern as Humble Choice.
  - `ai/plans/011_isthereanydeal-parse-the-embedded-var-page-json-instead-of-r.md:44-49` documents the *real* underlying data that would let this be modeled properly: the ITAD embedded JSON's `liveData.byob` is `[{"count": N, "price": [amount_cents, "CUR"]}, ...]` — literally the "pick N games for $price" tiers of a BYOB bundle — and the plan says this is *"already intentionally unmodeled today."* This is the closest thing in the repo to the exact BYOB mechanic the user is asking about, and it's flagged as future work, not done.
  - Concrete generated example showing the current pool-only representation: `lists/fanatical/bundle/2025-06-25_build-your-own-point-and-click-collection/tier-1.yml` — 14 games in one flat list, filename literally `tier-1.yml`, no pick count anywhere in the YAML (matches `GameList` schema exactly, no extra fields possible since `StrictModel` forbids extras).
- **Explicit user-authored backlog item** at `ai/query.md:1005`: *"We need to add support for BYOB (~~bring~~ ~~buy~~ build your own bundle), where thouse would allow for the usual 3-4 game selections to match. Ideas?"* — confirms this is a known, previously-deferred gap, not something quietly already solved.
- `ai/output/agents/005.ac96a7dbc4150dd7f/prompt.md:39` (an earlier task's scope note) explicitly calls out not to act on the BYOB backlog item, flagging it as a "possibly-separate ask."
- Grep for `pick|subset|any_of|partial|choose` across `src/game_collections` (full results above) turns up only unrelated hits: `local_ownership.py:5` ("subset of what an account actually owns" — a docstring about partial Steam ownership snapshots, not bundle modeling), and every other `choose`/`choice` hit is the interactive storefront-candidate-selection callback (`CandidateChooser`/`_choose_*` in `cli.py`, `resolver.py`, `search.py`) — i.e. "choose which search result is correct," unrelated to "choose which games to redeem."

### 4. `lists/README.md` authoring workflow and match semantics

Full file read above (`lists/README.md:1-61`). Key points for how BYOB would need to fit in:

- **List identity/shape** (`lists/README.md:3-21`): one `.yml` file = one portable collection, validated by the strict `GameList`/`Game` Pydantic models; JSON Schema is generated from those same models (`game-collections schema`). Any BYOB field would need to be added to `GameList`/`Game` and the schema regenerated — there's no schema-less escape hatch (`StrictModel` forbids extra fields).
- **Authoring/completion workflow** (`lists/README.md:31-41`): drafts start with blank `ids`, then `game-collections complete` fills them via storefront search (`--mode blank|missing|unresolved|refetch_all`, `--provider`/`--store` selection). This workflow is per-game ID resolution and has no concept of per-game inclusion/exclusion state — it would need to stay orthogonal to any new "how many of these are actually owned" concept.
- **Generated Humble lists section** (`lists/README.md:49-57`): documents today's `scrape humblebundle` output — "Tier counts and names follow Humble's advertised cumulative tiers, while the standard list contains games only." This is the exact place that would need updating/extending for a Humble-Choice-flavored BYOB model, and it's also where the doc explicitly frames Choice as tier-based (cumulative), not pick-based, consistent with finding #1.
- **Match semantics, from root `README.md:63`** (not `lists/README.md`, but this is what the user meant by "sync steam"): *"`sync steam` defaults to `--mode all --tiers highest`. `--mode all` requires every Steam ID in a list to be owned, while `--mode any` requires at least one and exports only the owned Steam IDs; games without Steam IDs do not affect either match mode."* This is the closest existing analog to "own N of M": `--mode any` already means "partial ownership of a fixed list is fine, export only what's owned" — but it's a binary per-game, whole-list-scoped switch with no quantity/threshold (no "own at least N", no "list is only valid if you picked exactly N"). `--tiers highest`/`all` (also `README.md:63`, CLI flag at `src/game_collections/cli.py:803`) is the existing per-bundle-directory "pick the best cumulative tier" reconciliation logic, driven by sibling `tier-N.yml`/`(entire-)?N-item-bundle.yml` naming (per `crawler.py:279-284`'s own naming convention) — this is the nearest existing "choose among sibling variants of a bundle" mechanic, but it selects a whole pre-baked tier file, not an arbitrary N-of-M subset within one list.

### Summary for planning

- Reusing Humble Choice's existing code as-is will not work: it structurally discards the "pick N of M" fact at parse time (one tier = whole pool) and the Choice month's actual per-buyer redemption picks are never fetched/stored anywhere in `archives/humblebundle/`.
- The closest and most reusable prior art is the **ITAD `byob` handling** (`models.py`, `parser.py` in `sources/isthereanydeal/`) plus its own documented gap in `ai/plans/011_...md` — that plan already identifies the exact upstream data shape (`liveData.byob: [{"count": N, "price": [...]}]`) that a BYOB "own N of M" feature would need to consume, and flags it as unmodeled by design so far.
- Any real fix needs new model fields (e.g. on `GameList`/`Game`, or a new sibling model) capable of expressing a pick quota/threshold — nothing in `models.py`, `HumbleTier`, or `ItadTier` today has such a field, and `--mode all/any` in `sync steam` is the only existing quantity-adjacent concept, and it's list-wide all-or-any, not "N of M."