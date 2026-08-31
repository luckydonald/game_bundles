# Resolve Humble "Edition" items that bundle a base game + DLCs into one Steam purchase

## Context

`scrape humblebundle` is currently crawling
`https://www.humblebundle.com/games/dread-and-dark-fantasies-rpg-collection`, which contains the
item **"Steelrising - Bastille Edition"**. There is no single Steam app or bundle page titled
exactly that, so `StorefrontResolver._resolve_title` finds no unique exact-title match and falls
back to the interactive "Multiple…"/"Other…" prompt.

I fetched the bundle's live `webpack-bundle-page-data` JSON directly (`curl`, not WebFetch, which
is blocked for humblebundle.com/steamdb.info) and confirmed the real item shape. Its
`cta_badge` is `null` (i.e. **not** Humble's own `"dlc"` badge), so it never goes through the
existing "DLC pack" gating in `parser.py` at all. Its `description_text` starts with:

```html
<p><strong>Bastille Edition:</strong></p>
<p>Includes: Base game + Discus Chain DLC + Cagliostro's Secrets DLC.</p>
...
```

I also confirmed live against store.steampowered.com/search that both components exist as their
own separately searchable, exact-title Steam store pages:
- `Steelrising - Discus Chain` (appid found via search)
- `Steelrising - Cagliostro's Secrets` (appid found via search)

...and `Steelrising` itself already resolves cleanly today (confirmed in
`lists/humblebundle/bundle/2024-05-07_may-2024/bundle.yml` and
`.../2025-12-15_humbling-soulslike-bundle-encore/bundle.yml`).

So **no new Steam identity concept (sub/package ids, `steam:sub/<id>`, steamdb `/sub/` parsing)
is needed** — the steamdb/`/sub/729916` forensics in the original request were just how the
correct set of titles was discovered; the actual fix is to teach the Humble parser to recognize
this "Edition: … / Includes: Base game + X DLC + Y DLC." description shape and turn it into a
list of independently-resolvable titles, reusing the existing per-title Steam search + the
existing "DLC pack" split/`HumbleResolvedGame` machinery in `resolver.py` — just without the
"requires a separately-owned free base game" semantics that real DLC packs have (here the base
game is *itself* granted by this same purchase, so no `requires` link is needed).

## Existing mechanism being extended

- `src/game_collections/sources/humblebundle/parser.py`: `_bundle_item` gates a **strict**,
  Humble-badge-driven DLC-pack split — only when `"dlc" in tags` (from `cta_badge.badge`) does it
  call `_parse_dlc_pack_details` (an `HTMLParser` picking the first Steam `<a>` link as
  `base_game_url` and every `<li>` of the first `<ul>` as `bundled_dlc_names`).
- `src/game_collections/sources/humblebundle/models.py`: `HumbleItem.base_game_url` /
  `.bundled_dlc_names` drive this; `HumbleResolution.splits: list[HumbleResolvedGame]` holds the
  per-DLC resolved results, `HumbleResolution.requires` is the shared base-game dependency.
- `src/game_collections/sources/humblebundle/resolver.py`:
  - `resolve_item` (line 315): if `item.bundled_dlc_names` is set, resolves each name via
    `_resolve_title` and attaches `requires` (from `base_game_url`, or `[]` if none) to every
    split.
  - `resolve_archive` (line 339): same `if item.bundled_dlc_names:` check decides whether to
    write `HumbleResolution(splits=...)` vs. `HumbleResolution(ids=...)`.
  - `_resolve_title` itself is unchanged by this work — it already does exact-title Steam search
    per title, which is all that's needed once we hand it the right titles.

Since `resolve_item`/`resolve_archive` only care about "is there a list of titles to resolve
independently, with `requires` from `base_game_url` (empty if unset)", the resolver changes are
small: extend the existing `bundled_dlc_names` branch conditions to also fire for the new field.

## Implementation

### 1. `models.py` — new field on `HumbleItem`

Add, next to `base_game_url`/`bundled_dlc_names` (lines 81-84), with a comment distinguishing the
two split reasons:

```python
# Populated for "Edition" items whose title ends "- <Edition> Edition" and whose description
# states "Includes: Base game + <DLC> + <DLC>." (no `cta_badge`, unlike a "DLC pack" - Steam
# only sells the base game + DLCs together via this edition, with no single matching app page).
# Each component (including the base game itself) is resolved independently, with no `requires`.
edition_component_titles: list[NonEmptyString] = Field(default_factory=list)
```

### 2. `parser.py` — detect the "Edition bundle" shape

Add a narrow, conservative detector (mirroring the existing `_parse_dlc_pack_details` caution
about false positives — this one has no site-provided badge to gate on, so the text/title match
must be specific):

- `_parse_edition_bundle_components(title: str, html: str) -> list[str]`:
  1. Match `title` against `r"^(.+) - (.+ Edition)$"` (case-insensitive on "Edition"); if it
     doesn't match, return `[]`. Capture `base_title`, `edition_name`.
  2. Extract the plain text of the description's **first two** `<p>` elements only (small
     `HTMLParser`, similar shape to `_DlcPackDetailsParser` but collecting paragraph text
     instead of `<ul>/<li>`).
  3. First paragraph, stripped of trailing `:`, must casefold-equal `edition_name`; if not,
     return `[]`.
  4. Second paragraph must start with `"Includes:"` (case-insensitive) and end with `.`; if not,
     return `[]`. Split the remainder on `" + "`, strip trailing `.` from the last piece.
  5. For each piece: if it casefold-equals `"base game"`, substitute `base_title`. Else if it
     case-insensitively ends with `" DLC"`, strip that suffix and prefix with
     `f"{base_title} - "`. Else (unrecognized piece shape) bail out and return `[]` entirely —
     stay narrow rather than guess, per this project's "verify, don't guess" approach; an
     unmatched shape should fall through to today's normal single-title resolution/prompt.
  6. Return `[base_title, *dlc_titles]` in order.

Wire into `_bundle_item` (near the existing `base_game_url, bundled_dlc_names = ...` line):

```python
edition_component_titles = (
    _parse_edition_bundle_components(title, raw.get("description_text") or "")
    if "dlc" not in tags
    else []
)
```

(computed after `title` is known; pass `edition_component_titles=edition_component_titles` into
the `HumbleItem(...)` call).

### 3. `resolver.py` — treat edition components the same as DLC-pack splits

- `resolve_item` (line 315): change
  `if item.bundled_dlc_names:` → `if item.bundled_dlc_names or item.edition_component_titles:`,
  and resolve `component_titles = item.bundled_dlc_names or item.edition_component_titles` (the
  two are mutually exclusive by construction) in place of the current `item.bundled_dlc_names`
  loop target. `requires` stays exactly as computed today (from `base_game_url`, so `[]` for
  edition-bundle items — correct, since owning the base isn't a precondition here).
- `resolve_archive` (line 366): same condition update, so it writes `HumbleResolution(splits=...)`
  for edition-bundle items too.

## Tests (using the real, verified Steelrising data)

### `tests/test_humblebundle_parser.py`

1. `test_parse_edition_bundle_components_extracts_base_and_dlc_titles` — unit test calling
   `_parse_edition_bundle_components("Steelrising - Bastille Edition", description)` with the
   real captured `description_text` (the two opening `<p>` tags shown above, plus the rest of the
   real blurb already fetched), asserting the result equals
   `["Steelrising", "Steelrising - Discus Chain", "Steelrising - Cagliostro's Secrets"]`.
2. `test_bundle_page_wires_edition_bundle_components_onto_the_item` — integration test building a
   minimal `tier_item_data` payload for `steelrising_bastilleedition` (real field shapes:
   `cta_badge: None`, `item_content_type: "game"`, `availability_icons.delivery_icons:
   ["hb-steam"]`, the real `description_text`), run through `parse_bundle_page`, asserting
   `item.edition_component_titles == [...]` and `item.tags == []` / `item.base_game_url is None`
   (unaffected).
3. A false-positive guard test, mirroring
   `test_bundle_page_ignores_dlc_pack_shape_on_a_non_dlc_item`: a normal item whose title has a
   `" - "` and whose description happens to contain an unrelated "Includes: ..." sentence that
   doesn't match the exact opening-paragraph shape — assert `edition_component_titles == []`.

### `tests/test_humblebundle_resolver.py`

4. `test_resolve_item_splits_an_edition_bundle_without_requires` — mirroring
   `test_resolve_item_splits_a_dlc_pack_and_attaches_requires`: build a `HumbleItem` directly with
   `edition_component_titles=["Steelrising", "Steelrising - Discus Chain", "Steelrising -
   Cagliostro's Secrets"]`, `base_game_url=None`, a fake `fetch` returning distinct Steam app
   links per searched title (same style as `test_choosing_multiple_splits_a_title_into_separate_resolved_games`'s
   `fetch`), call `resolve_item`, and assert 3 `ResolvedGame`s each with `requires == []` and the
   expected `steam:<appid>` per title.

## Verification

```console
env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_humblebundle_parser.py tests/test_humblebundle_resolver.py -q
env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q
```

No schema regeneration is needed (new field is a plain `list[NonEmptyString]` on an existing
model, but `schemas/humblebundle-archive.schema.json` is generated from Pydantic and
`tests/test_schema.py` will fail if it drifts) — regenerate via
`env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections schema` if that test fails, and commit the
updated schema file alongside the code change.
