# ITAD per-game detail-page solver for `unresolved:source:isthereanydeal:*`

## Context

ITAD bundle tier YAMLs (`lists/<provider>/bundle/...`) frequently contain
`unresolved:source:isthereanydeal:<bundle_id>:<slug>` markers whenever a
bundle detail page had no recognized storefront link for a game (~4,548
files today). There is currently no code that ever revisits these markers —
`complete_game_list` (`src/game_collections/search.py`) only does generic
storefront title-search and happens to strip `unresolved:source:*` markers
as a side effect of an unrelated successful search.

ITAD itself hosts a per-game detail page
(`https://isthereanydeal.com/game/<slug>/info/`) with an embedded
`var page = ["Game", {"game": {...}, "detail": {...}}]` blob containing
`detail.appid` (Steam appid, `int | None`) directly, plus a `game.id` (gid).
That gid can be POSTed to `https://isthereanydeal.com/api/game/info/` (same
anonymous session-token auth as the bundles list API) to get a `deals` array
of `{shop: <shop-id>, url: "https://itad.link/<id>/", ...}` entries — each
`url` redirects to the real storefront page, letting non-Steam games (GOG,
Epic, etc.) resolve too via the same `STORE_ROOTS`/`parse_store_identity`
machinery the bundle parser already uses.

This plan adds that lookup as a genuine solver, reachable via
`game-collections complete FILE --provider isthereanydeal --mode unresolved`,
and separately fixes the bundle parser to always record a game's own
`isthereanydeal:<slug>` id (not just resolved storefront ids), so future
resolution has a stable anchor independent of the bundle it was first seen
in.

Decisions already confirmed with the user:
- CLI shape: extend the existing `complete` verb — add `"isthereanydeal"` as
  a selectable `--provider` value, used together with `--mode unresolved`.
  No new batch verb; the ~4,548-file backlog is fixed forward-only (re-run
  `complete` per file, or delete-and-recrawl), not backfilled by this change.
- No appid + no matching deal store: keep the `unresolved:source:...`
  marker, but still add `isthereanydeal:<slug>` (already true in every case
  since the bundle-parser fix always adds it).
- Every fetch's raw payloads (embedded page JSON, deals API JSON, and each
  deal's resolved redirect URL) get archived to disk, not just derived ids.

While investigating, confirmed a real duplicate-identity case worth
handling explicitly: ITAD has *two separate games* for the same real
product across platforms — `pinball-fx-my-little-pony-pinball` (Steam DLC,
gid `018d937f-6cbf-7251-9831-fad1495eed7d`, `appid=2351841`) and
`my-little-pony-pinball` (Epic DLC, gid `018d937f-6b34-7099-a216-ded41ab04039`,
`appid=None`) — each with its own gid/slug/deals, neither aware of the
other. Left unhandled, the Epic one would resolve to nothing (no Steam
appid, and its own deals likely won't include a Steam link) even though we
already know its Steam-side id via the other slug. This needs a small
reviewed alias config (see section 3b) rather than being solved by the API
data alone.

Other confirmed-good MLP slugs for docs/tests/fixtures going forward (used
instead of placeholder-looking names like `no-mans-sky`/`wildstar`):
`my-little-pony-a-zephyr-heights-mystery` (appid `2235440`),
`my-little-pony-a-maretime-bay-adventure` (appid `1600780`).

## 1. `models.py` — new archive model

Add `ItadGameArchive(StrictModel)` next to `ItadArchive`:
- `schema_version: Literal[1]` (alias `schema`, same pattern as `ItadArchive`)
- `slug: NonEmptyString`
- `title: NonEmptyString`
- `appid: int | None = Field(default=None, gt=0)`
- `ids: list[NonEmptyString] = Field(min_length=1)` — final resolved
  qualified ids (`steam:...`, `gog:...`, etc., always including
  `isthereanydeal:<slug>`)
- `url: HttpUrl` — the `/game/<slug>/info/` page URL
- `dates: ItadDates` — reuse the existing model as-is with `start=None`,
  `expiry=None`, `crawled=<fetch time>`

## 2. `sources/isthereanydeal/parser.py` — two changes

**a. Always record the game's own id.** In `_resolve_urls` (line ~307),
append `f"isthereanydeal:{slug}"` unconditionally after the existing
storefront-URL loop, regardless of whether any storefront id resolved (so
the id list may now contain both `isthereanydeal:<slug>` and an
`unresolved:source:isthereanydeal:...` marker together — that's expected).
Update `tests/test_isthereanydeal_parser.py` fixtures/assertions
accordingly (every `ItadItem.ids` gains a trailing `isthereanydeal:<slug>`
entry).

**b. New parser for the per-game detail page.** Add
`parse_game_detail_json(html: str, slug: str) -> ItadGameDetail` (a small
`@dataclass` with `gid: str`, `title: str`, `appid: int | None`,
`payload: dict[str, Any]` — the raw `data[1]` dict, for archiving). Mirrors
`parse_bundle_detail_json`: reuse the existing `_find_page_script`,
`_PAGE_SCRIPT_PATTERN`, `_extract_balanced` helpers, expect
`data[0] == "Game"`, validate `game.title` (str) and `detail.appid`
(`int | None`, error if present but non-int), raise `ItadParseError` for any
other shape mismatch. No DOM fallback needed (mirrors the Bundle page: the
embedded script isn't rendering-gated).

## 3. New file `sources/isthereanydeal/resolver.py`

Following the `humblebundle/resolver.py` / `greenmangaming/resolver.py`
naming convention (this source's own "resolve an id" module):

- `UNRESOLVED_PREFIX = "unresolved:source:isthereanydeal:"` and
  `parse_unresolved_marker(value: str) -> tuple[int, str] | None` — returns
  `(bundle_id, slug)` or `None` if `value` isn't a matching marker.
- `ItadGameHttpClient` (or extend `ItadHttpClient` in `crawler.py` with new
  methods — prefer extending it directly so token-bootstrap logic isn't
  duplicated): add `fetch_deals(gid: str) -> dict[str, Any]` (POST
  `https://isthereanydeal.com/api/game/info/` with `{"gid": gid}`, same
  `itad-sessiontoken` header/retry/bootstrap-refresh-on-400 pattern as
  `list_page`), and `resolve_redirect(url: str) -> str` (HEAD or GET with
  `follow_redirects=True`, return `str(response.url)`).
- `resolve_game(slug, fetch_detail_page, fetch_deals, resolve_redirect,
  crawled) -> ItadGameResolution` (dataclass: `archive: ItadGameArchive`,
  `source: dict[str, Any]`):
  1. Fetch `https://isthereanydeal.com/game/{slug}/info/`, run
     `parse_game_detail_json`.
  2. Fetch deals via `fetch_deals(gid)`.
  3. For every deal, resolve its redirect and, if the resolved URL matches a
     known `STORE_ROOTS` prefix, resolve via `parse_store_identity` (reuse
     the same dedupe-and-match loop `_resolve_urls` uses — factor that inner
     loop out of `parser.py` into a small shared helper, e.g.
     `qualified_ids_from_urls(urls: list[str]) -> list[str]`, called by both
     `_resolve_urls` and this new path).
  4. Build final `ids`: `steam:<appid>` if present, plus every qualified id
     found via deals, plus `isthereanydeal:<slug>` always, deduped.
  5. `source` dict for archiving: `{"page": <raw data[1]>, "deals":
     <raw deals API response>, "deals_resolved": [{"shop": ..., "url": ...,
     "url_resolved": ...}, ...]}`.
- `_archive_paths(archive_root, slug) -> (metadata.json, source.json)` under
  `archive_root / "isthereanydeal/game" / slug`, and
  `write_itad_game_archive(resolution, archive_root) -> tuple[Path, Path]`
  using `atomic_write`/`dump_json` from `sources/common.py` (same as every
  other source).
- `resolve_isthereanydeal_markers(current: list[str], resolve: Callable[[str],
  ItadGameResolution]) -> list[str]` — for every marker in `current` matched
  by `parse_unresolved_marker`, call `resolve(slug)` (see 3b — this is the
  alias-aware wrapper, not the bare single-slug `resolve_game`), merge
  `resolution.archive.ids` into the list (dedup), and drop the marker only
  if at least one non-`isthereanydeal:` id was found; used by `search.py`.

## 3b. New config `config/isthereanydeal-game-aliases.yml` — cross-platform duplicates

Reviewed, hand-maintained config listing groups of ITAD slugs that are
known to be the same real-world game despite being separate ITAD entries
(different gid/appid per platform-specific store listing — confirmed real
with the MLP Pinball case above: Steam DLC `pinball-fx-my-little-pony-pinball`
vs Epic DLC `my-little-pony-pinball`). Mirrors the
`provider_config.py`/`shop_config.py` convention exactly (same repo, same
`schema: 1` + `load_*_config(path)` shape, empty-if-absent):

```yaml
schema: 1
aliases:
  - [pinball-fx-my-little-pony-pinball, my-little-pony-pinball]
```

New `sources/isthereanydeal/game_alias_config.py`:
- `ItadGameAliasConfig(StrictModel)`: `schema_version: Literal[1]` (alias
  `schema`), `aliases: list[list[NonEmptyString]] = Field(default_factory=list)`,
  with a `model_validator` requiring each group to have >= 2 distinct slugs
  and no slug to appear in more than one group.
- `load_game_alias_config(path: Path) -> dict[str, frozenset[str]]` — loads
  the config (or `{}` if the file is absent), and returns every slug in a
  group mapped to its full group (including itself), for O(1) lookup.

In `resolver.py`, add `resolve_game_with_aliases(slug, alias_groups:
dict[str, frozenset[str]], resolve_one: Callable[[str], ItadGameResolution])
-> ItadGameResolution`: looks up `alias_groups.get(slug, frozenset({slug}))`,
calls `resolve_one` for every slug in that group (each still independently
archived under its own `archives/isthereanydeal/game/<slug>/`, since each
is a genuinely distinct ITAD entry/product listing), and returns a
synthesized `ItadGameResolution` whose `archive.ids` is the union of every
group member's ids (so the Epic-only entry ends up with the Steam appid
too, and vice versa) keyed by the *originally requested* slug's own
metadata (title/url/appid). This is what `resolve_isthereanydeal_markers`
and `complete_command`'s closure should actually call — not bare
`resolve_game` — so cross-platform duplicates resolve correctly by default.

## 4. `search.py` — wire `"isthereanydeal"` as a provider

- Extend `ProviderSelection` to `StoreName | Literal["all", "isthereanydeal"]`.
- `selected_providers`: accept `"isthereanydeal"` as a valid requested value
  without it being expanded by `"all"` (which stays storefronts-only).
- `complete_game_list`: add an optional parameter,
  `itad_resolve: Callable[[str], ItadGameResolution] | None = None`. In the
  per-game provider loop, when a requested provider is `"isthereanydeal"`,
  skip the normal `resolve_title`/`_should_search` path entirely and instead
  call `resolve_isthereanydeal_markers(current, itad_resolve)` once per game
  (only if the game's `current` ids contain at least one matching marker;
  otherwise no-op, mirroring `_should_search`'s "nothing to do" shape). Raise
  `ValueError` up front if `"isthereanydeal"` is requested but
  `itad_resolve` is `None`.
- Import `ItadGameResolution`/`resolve_isthereanydeal_markers` from
  `game_collections.sources.isthereanydeal.resolver`.

## 5. `cli.py` — `complete_command`

- Add `--archive-root` option (default `Path("archives")`, matching the
  scrape commands) and `--game-alias-config` option (default
  `Path("config/isthereanydeal-game-aliases.yml")`, matching
  `--provider-config`/`--shop-config` on `scrape isthereanydeal`) — both only
  used when isthereanydeal resolution actually runs.
- When `"isthereanydeal"` is among the selected providers, construct an
  `ItadHttpClient`/`ItadGameHttpClient`, `load_game_alias_config(...)`, build
  a small closure `resolve(slug)` that calls
  `resolve_game_with_aliases(slug, alias_groups, resolve_one)` where
  `resolve_one` calls `resolve_game(...)` and immediately
  `write_itad_game_archive` per slug (so partial progress persists across
  ctrl-C, matching every other scrape/write flow), and pass the outer
  closure as `itad_resolve=` into `complete_game_list`. Close the client in
  the existing `finally` block.

## 6. Schema

`ItadGameArchive` is a new public archive model → generate
`schemas/isthereanydeal-game-archive.schema.json` via a new
`write_isthereanydeal_game_schema` in `schema.py`, register it as
`--isthereanydeal-game-output` in `schema_command`, and add the matching
`test_committed_isthereanydeal_game_schema_matches_pydantic_models` in
`tests/test_schema.py` (same pattern as the existing four).

## 7. Tests

- `tests/test_isthereanydeal_parser.py`: update `_resolve_urls`
  fixtures/assertions for the always-appended `isthereanydeal:<slug>` id;
  add cases for `parse_game_detail_json` (appid present / `null` / missing
  `detail`/`game` key / not-a-`"Game"` tag).
- New `tests/test_isthereanydeal_resolver.py`: `parse_unresolved_marker`,
  `resolve_game` with injected fake `fetch_detail_page`/`fetch_deals`/
  `resolve_redirect` (appid-only case, deals-only case, no-match case),
  `resolve_game_with_aliases` (using the real MLP Pinball pair as the test
  fixture: resolving `my-little-pony-pinball` — no appid on its own — pulls
  in `pinball-fx-my-little-pony-pinball`'s `steam:2351841` id via the alias
  group), `resolve_isthereanydeal_markers` merge/strip behavior, and
  `write_itad_game_archive` round-trip via `load_cached_archive`.
- New `tests/test_isthereanydeal_game_alias_config.py`: `load_game_alias_config`
  (absent file, valid group, duplicate-slug-across-groups rejected,
  single-slug group rejected).
- `tests/test_search.py`: `complete_game_list` with
  `providers=("isthereanydeal",)` — resolves a marker via a fake
  `itad_resolve`, leaves non-matching games untouched, raises when
  `itad_resolve` is omitted.
- `tests/test_schema.py`: new committed-schema test per item 6.

## 8. Docs

Update root `README.md` (`complete` verb section) and `lists/README.md` if
it documents `unresolved:` id conventions, to mention
`--provider isthereanydeal` and what it does.

## Verification

- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest` (full suite).
- `env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections schema` (schema
  drift check passes).
- Manual smoke test against a scratch draft list with three entries: slug
  `my-little-pony-a-zephyr-heights-mystery` (has `detail.appid = 2235440`
  directly — simple case), slug `my-little-pony-a-maretime-bay-adventure`
  (`appid = 1600780` — simple case), and slug `my-little-pony-pinball` (the
  Epic DLC with `appid = None` — exercises both the deals-API fallback path
  *and* the alias config pulling in `pinball-fx-my-little-pony-pinball`'s
  Steam id). Populate `config/isthereanydeal-game-aliases.yml` with the
  Pinball pair first. Run
  `uv run game-collections complete <scratch file> --provider isthereanydeal --mode unresolved`
  and confirm all three markers resolve/augment correctly and
  `archives/isthereanydeal/game/<slug>/` is written for every slug touched
  (four directories: the three requested plus
  `pinball-fx-my-little-pony-pinball` pulled in via the alias).

Note for any future docs/examples referencing this feature (README, code
comments, test fixtures): use these confirmed-real MLP slugs as the worked
examples, not placeholder-looking names like `no-mans-sky`/`wildstar`:
`my-little-pony-a-zephyr-heights-mystery`,
`my-little-pony-a-maretime-bay-adventure`,
`pinball-fx-my-little-pony-pinball` / `my-little-pony-pinball` (the
alias-config pair).
