# Resolve Humble "Edition" items that bundle a base game + DLCs into one Steam purchase

## Context

`scrape humblebundle` crawled `dread-and-dark-fantasies-rpg-collection`, which contains the item
**"Steelrising - Bastille Edition"**. There is no single Steam app or bundle page titled exactly
that, so it fell through to the interactive "Multiple…"/"Other…" prompt with **zero** candidates
shown at all (see `ai/errors/3.txt` lines 84-88). While diagnosing this, a second, more general
UX problem in the interactive resolve prompt itself surfaced. This plan covers three things:

1. A parser-side fix so Humble's own description text resolves this exact shape without any
   prompting at all.
2. A steamdb-fallback fix so a Steam *package* ("Sub") result — invisible today — expands into
   its real per-app members instead of contributing nothing.
3. A redesign of the interactive "Multiple…" flow so it searches/resolves each declared name
   immediately, one at a time, instead of collecting all names first and resolving them
   afterward.

I fetched the bundle's live `webpack-bundle-page-data` JSON directly (`curl`, not WebFetch, which
is blocked for humblebundle.com/steamdb.info — steamdb.info itself is Cloudflare-gated and 403s
even to `curl`) and confirmed the real item shape. Its `cta_badge` is `null` (i.e. **not**
Humble's own `"dlc"` badge, so it never goes through today's "DLC pack" gating in `parser.py`).
Its `description_text` starts with:

```html
<p><strong>Bastille Edition:</strong></p>
<p>Includes: Base game + Discus Chain DLC + Cagliostro's Secrets DLC.</p>
...
```

I also confirmed live against store.steampowered.com/search that both components already exist as
their own separately searchable, exact-title Steam store pages — `Steelrising - Discus Chain`
and `Steelrising - Cagliostro's Secrets` — and that plain `Steelrising` itself already resolves
cleanly today (`lists/humblebundle/bundle/2024-05-07_may-2024/bundle.yml`,
`.../2025-12-15_humbling-soulslike-bundle-encore/bundle.yml`).

Per `src/game_collections/completion.py:29-53`, a bare `steam:bundle/<id>` (Steam retail bundle)
is explicitly **skipped** for ownership matching — "no single AppID the Web API's owned-games
list can match against" — so a hypothetical `steam:sub/<id>` identity would be equally useless on
its own. The only useful fix is to resolve each component (base game + every DLC) to its own real
`steam:<appid>`, the same way the existing "DLC pack" split mechanism already does.

## Part 1 — Parser: detect the "Edition bundle" description shape

### Existing mechanism being extended

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

Since `resolve_item`/`resolve_archive` only care about "is there a list of titles to resolve
independently, with `requires` from `base_game_url` (empty if unset)", the resolver changes are
small: extend the existing `bundled_dlc_names` branch conditions to also fire for the new field.

### 1a. `models.py` — new field on `HumbleItem`

Add, next to `base_game_url`/`bundled_dlc_names` (lines 81-84), with a comment distinguishing the
two split reasons:

```python
# Populated for "Edition" items whose title ends "- <Edition> Edition" and whose description
# states "Includes: Base game + <DLC> + <DLC>." (no `cta_badge`, unlike a "DLC pack" - Steam
# only sells the base game + DLCs together via this edition, with no single matching app page).
# Each component (including the base game itself) is resolved independently, with no `requires`.
edition_component_titles: list[NonEmptyString] = Field(default_factory=list)
```

### 1b. `parser.py` — detect the shape

Add a narrow, conservative detector (mirroring `_parse_dlc_pack_details`'s caution about false
positives — this one has no site-provided badge to gate on, so the text/title match must be
specific):

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
     stay narrow rather than guess; an unmatched shape falls through to normal single-title
     resolution (now backstopped by Part 2's steamdb sub expansion).
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

### 1c. `resolver.py` — treat edition components the same as DLC-pack splits

- `resolve_item` (line 315): change
  `if item.bundled_dlc_names:` → `if item.bundled_dlc_names or item.edition_component_titles:`,
  and resolve `component_titles = item.bundled_dlc_names or item.edition_component_titles` (the
  two are mutually exclusive by construction) in place of the current `item.bundled_dlc_names`
  loop target. `requires` stays exactly as computed today (from `base_game_url`, so `[]` for
  edition-bundle items — correct, since owning the base isn't a precondition here).
- `resolve_archive` (line 366): same condition update, so it writes `HumbleResolution(splits=...)`
  for edition-bundle items too.

### Tests

`tests/test_humblebundle_parser.py` (using the real, verified Steelrising data):
1. `test_parse_edition_bundle_components_extracts_base_and_dlc_titles` — unit test calling
   `_parse_edition_bundle_components("Steelrising - Bastille Edition", description)` with the
   real captured `description_text`, asserting the result equals
   `["Steelrising", "Steelrising - Discus Chain", "Steelrising - Cagliostro's Secrets"]`.
2. `test_bundle_page_wires_edition_bundle_components_onto_the_item` — integration test building a
   minimal `tier_item_data` payload for `steelrising_bastilleedition` (real field shapes:
   `cta_badge: None`, `item_content_type: "game"`, `availability_icons.delivery_icons:
   ["hb-steam"]`, the real `description_text`) through `parse_bundle_page`, asserting
   `item.edition_component_titles == [...]`.
3. False-positive guard, mirroring `test_bundle_page_ignores_dlc_pack_shape_on_a_non_dlc_item`: a
   normal item whose title has a `" - "` and whose description contains an unrelated "Includes:
   ..." sentence not matching the exact opening-paragraph shape — assert
   `edition_component_titles == []`.

`tests/test_humblebundle_resolver.py`:
4. `test_resolve_item_splits_an_edition_bundle_without_requires` — mirroring
   `test_resolve_item_splits_a_dlc_pack_and_attaches_requires`: build a `HumbleItem` directly with
   `edition_component_titles=["Steelrising", "Steelrising - Discus Chain", "Steelrising -
   Cagliostro's Secrets"]`, `base_game_url=None`, a fake `fetch` returning a distinct Steam app
   link per searched title, call `resolve_item`, assert 3 `ResolvedGame`s each with
   `requires == []` and the expected `steam:<appid>` per title.

## Part 2 — steamdb fallback: recognize and expand a Sub (package) result

### The gap

`src/game_collections/sources/humblebundle/steamdb.py:39`'s `_RESULT_LINK_HREF` only matches
`/(app|bundle)/(\d+)/` — a steamdb.info `/sub/<id>/` result row (like `sub/729916`, the actual
package backing "Buy Steelrising - Bastille Edition") is silently dropped from search results.
This is very likely *why* the live run showed **zero** candidates for "Steelrising - Bastille
Edition" (`ai/errors/3.txt` line 84-86): steampowered.com's own search has no page titled that
exactly, and steamdb's fallback search (`resolver._search_steam`) would find the Sub row but
throw it away before it ever reaches `choose_store_candidate`.

Per `completion.py`'s existing precedent (`steam:bundle/<id>` can't drive ownership on its own), a
`steam:sub/<id>` identity would be equally inert — the fix must expand a matched Sub into its
real per-app members (base + every DLC), the same "independently-resolved splits, no `requires`"
shape as Part 1, discovered from the *Steam side* this time instead of the *Humble side*.

### Verified live (headed `patchright` session, `SteamDbBrowserClient`)

Fetched both pages for real and confirmed the exact markup:

**Search results** for `Steelrising Bastille Edition` return exactly one row — a `package` (Sub)
row, no competing `app`/`bundle` rows:

```html
<tbody><tr class="package" data-subid="729916">
<td class="dt-type-numeric"><a href="/sub/729916/">729916</a></td>
<td class="applogo dt-type-numeric" data-sort="-1">
<a href="/sub/729916/"><img src="..." ...></a>
</td>
<td>
<a href="/sub/729916/"><mark>Steelrising</mark> - <mark>Bastille</mark> <mark>Edition</mark></a>
<i class="stype">Package</i>
</td>
...
</tr></tbody>
```

Same three-`<a href="/sub/729916/">`-per-row shape as today's `app`/`bundle` rows (id-column,
image-only applogo-column, name-column with `<mark>` highlight spans nested inside). The existing
`_SteamDbLinkParser` already handles this correctly once `_RESULT_LINK_HREF` recognizes the
`/sub/` prefix: it collects `handle_data` regardless of nested tags (so the `<mark>`-wrapped
"Steelrising - Bastille Edition" reconstructs correctly), and the empty-text applogo link is
already dropped by the existing `if text:` check in `handle_endtag`.

**The sub detail page** (`https://steamdb.info/sub/729916/`) has an "Apps in this package" table
under `<div class="tab-pane" id="apps">` — a **different, simpler** shape than search results:
name is plain text, not a link:

```html
<table class="table table-bordered table-hover table-sortable table-responsive-flex">
<thead>...</thead>
<tbody>
<tr class="app" data-appid="2021370">
<td><a href="/app/2021370/">2021370</a></td>
<td>DLC</td>
<td>Steelrising - Discus Chain</td>
<td>...</td><td>...</td><td>...</td>
</tr><tr class="app" data-appid="2004261">
<td><a href="/app/2004261/">2004261</a></td>
<td>DLC</td>
<td>Steelrising - Cagliostro's Secrets</td>
...
</tr><tr class="app" data-appid="1283400">
<td><a href="/app/1283400/">1283400</a></td>
<td>Game</td>
<td>Steelrising</td>
...
</tr></tbody>
</table>
```

Confirms the exact 3-app split (base game + 2 DLC) from a canonical, Humble-independent source.
Each row is `<tr class="app" data-appid="N">` with the AppID (redundant with the attribute), Type
("Game"/"DLC", not needed), and plain-text Name as its first three `<td>`s, in that fixed order.

### Implementation

- `steamdb.py`:
  - Extend `_RESULT_LINK_HREF` to `^/(app|bundle|sub)/(\d+)/$`, tagging Sub search results as
    `sub/<id>` in `parse_steamdb_results` (mirroring the existing `bundle/<id>` convention) — no
    other change needed there, the existing link-collection logic already handles this row shape.
  - Add a new small `HTMLParser`, `_SteamDbSubAppsParser`, plus
    `parse_steamdb_sub_apps(html: str) -> list[tuple[int, str]]`: track `<tr class="app"
    data-appid="...">` start tags to capture the appid, then collect the **third** `<td>`'s text
    content within that row as the name (skip the first two `<td>`s — id link and Type). Return
    `(appid, name)` pairs in document order.
- `resolver.py`'s `_search_steam`/`_resolve_title`: when steamdb's fallback search's exact-title
  match is a `sub/<id>` result (rather than an `app`/`bundle` one), instead of accepting it as a
  single `qualified_id`, fetch that sub's own page (via the same injected fetch function already
  used for steamdb pages, i.e. `https://steamdb.info/sub/<id>/`) and parse it with
  `parse_steamdb_sub_apps`, producing one `ResolvedGame` per app in the package — `name` from the
  parsed row, `ids=[f"steam:{appid}"]`, `requires=[]` (same reasoning as Part 1's edition
  components: owning the sub grants every listed app at once, nothing is a precondition of
  another).
- This becomes a second, independent way to reach the same "several `steam:<appid>` splits, no
  requires" outcome as Part 1 — useful as a fallback for editions whose Humble description text
  doesn't match Part 1's narrow "Includes: Base game + X DLC + Y DLC." shape, since steamdb's Sub
  page is a canonical, Humble-independent source of the same information.

### Tests

Real captured HTML (`steamdb_search.html` for the "Steelrising Bastille Edition" query,
`steamdb_sub.html` for `sub/729916`) is available in the scratchpad from this investigation and
should be trimmed down to right-sized fixtures (same style as the existing `_script(...)`-built
fixtures — keep only the relevant `<tr>` markup, not the full page) rather than committed verbatim:

- `tests/test_humblebundle_steamdb.py` (check the exact existing filename holding steamdb parser
  tests first): unit tests for `_RESULT_LINK_HREF`/`parse_steamdb_results` recognizing a trimmed
  real Sub row (asserting the pair `("sub/729916", "Steelrising - Bastille Edition")`), and
  `parse_steamdb_sub_apps` against a trimmed real "Apps in this package" table, asserting it
  yields `[(2021370, "Steelrising - Discus Chain"), (2004261, "Steelrising - Cagliostro's
  Secrets"), (1283400, "Steelrising")]` (order as they appear in the table).
- `tests/test_humblebundle_resolver.py`: a resolver-level test with a fake steamdb fetch
  returning the trimmed search-results HTML (containing the Sub row) and the trimmed sub-page
  HTML, asserting `_resolve_title("Steelrising - Bastille Edition", ...)` returns 3 splits with
  `requires == []`, without any interactive prompt.

## Part 3 — Redesign the interactive "Multiple…" flow to resolve names immediately, one at a time

### Current behavior (the friction the user hit)

`src/game_collections/sources/prompting.py`'s `choose_store_candidate`, on "Multiple…", loops
purely collecting *names* (blank ends it), then returns `ChosenNames(names=[...])` — only *after*
that does `resolver._resolve_title` (line 298-303) go back and independently search/resolve each
collected name, one after another, each potentially triggering its own full
"Multiple…"/"Other…" prompt. This means: no feedback while typing names (you don't find out a
name was ambiguous, or matched instantly, until the whole list is already typed), and a nested
ambiguity re-offers "Multiple…" again, which makes no sense one level in.

### Desired flow (from the user's own spec)

Confirmed with the user (`AskUserQuestion`, ambiguity resolved: "Skip this (unresolved)" is not a
new menu row — it's just today's existing "Other… + blank = unresolved" behavior, described in
words):

1. Top-level prompt is unchanged: `Resolve '<title>' on <provider>:` with numbered candidates (if
   any) + `Multiple…` + `Other…`.
2. Choosing `Multiple…` starts a loop prompting
   `Name of one separate game (<count so far>) (blank to finish):` (no default value — the
   running count replaces today's "defaults to the outer title" convenience). A blank entry ends
   the loop; if zero names were collected, fall back to re-showing the top-level menu (unchanged
   `if not names: continue` behavior).
3. **Each name is searched and resolved immediately**, before asking for the next name:
   - If it resolves to a unique exact match, print a short confirmation —
     `Exact match found — <qualified_id>` then the URL on the next line — and move straight to
     prompting for the next name. (Today this happens silently with no feedback at all.)
   - If it's ambiguous, show the same `Resolve '<name>' on <provider>:` candidate menu — but
     **without a `Multiple…` row** (you're already inside a Multiple… collection; nesting another
     "split this into several" makes no sense) — just numbered candidates + `Other…`. Picking a
     candidate or pasting a URL/leaving `Other…` blank behaves exactly as it does today.
4. When the name-collection loop ends (blank entry), the collected per-name resolutions are
   combined into the split result, same as today.

### Implementation shape

- `prompting.py`: give `choose_store_candidate` an `allow_multiple: bool = True` parameter that
  omits the `Multiple…` row (and its handling branch) when `False`. Replace the internal
  name-collection loop's prompt text/default per the new wording above. Add a small
  `announce_exact_match(qualified_id: str, url: str) -> None` helper (a `typer.echo`) for step 3's
  confirmation line.
- `resolver.py`'s `_resolve_title`: thread an `allow_multiple: bool = True` parameter through to
  the `self._choose(...)` call. Restructure the "Multiple…" handling (today: collect all names
  from `ChosenNames`, then resolve each afterward) into: on receiving the "enter multiple mode"
  signal from the chooser, drive a loop that (a) prompts for one name via a newly injected
  "collect one name" callback (analogous to today's `CandidateChooser`, e.g.
  `NameCollector = Callable[[int], str | None]`, returning `None` on blank), and (b) immediately
  calls `self._resolve_title(name, stores, f"{cache_key}::{count}", mapping, allow_multiple=False)`
  for that name before asking for the next one — printing the exact-match confirmation (via a
  similarly injected `announce` callback) when that nested call's own exact-match branch is hit.
  `StorefrontResolver.__init__`'s constructor signature grows these two new injected callbacks
  (with `prompting.py`'s real implementations wired in production, and simple stub
  lambdas/fakes in tests — mirroring how `_choose`/`search`/`fetch` are already injected today).

### Tests

`tests/test_humblebundle_resolver.py`:
- Update/extend `test_choosing_multiple_splits_a_title_into_separate_resolved_games` (or add a
  sibling test) to inject the new name-collector and announce callbacks, asserting: (a) the
  per-name search happens interleaved with collection (e.g. by asserting call order via a
  recorded list), (b) a nested ambiguous name's chooser call receives `allow_multiple=False`
  (no `Multiple…` row offered), and (c) the announce callback fires with the right id/url for a
  name that resolves via unique exact match.

`tests/test_prompting.py` (new, if one doesn't already exist — check first): drive
`choose_store_candidate` with `allow_multiple=False` and assert the rendered menu never contains
a `Multiple…` line; with `allow_multiple=True` (default) assert it does.

## Verification

```console
env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_humblebundle_parser.py tests/test_humblebundle_resolver.py tests/test_prompting.py -q
env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q
```

Regenerate `schemas/humblebundle-archive.schema.json` if `tests/test_schema.py` flags drift from
the new `HumbleItem.edition_component_titles` field:
`env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections schema`, and commit it alongside the code
change.

For an end-to-end sanity check once implemented, re-run
`uv run game-collections scrape humblebundle --refresh --url
https://www.humblebundle.com/games/dread-and-dark-fantasies-rpg-collection` and confirm
"Steelrising - Bastille Edition" resolves to 3 `steam:` ids with no interactive prompt.
