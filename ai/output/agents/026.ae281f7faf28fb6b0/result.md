Now I have full picture. Here is the report.

## 1. `steamdb.py` — SteamDB search request

File: `/home/user/git/luckydonald/game_collections/src/game_collections/sources/humblebundle/steamdb.py`

```python
# lines 29-33
# `a=app` restricted the search to the Apps tab only, so a title whose closest
# Steam match is a bundle (e.g. a "Deluxe Edition" sold only as a bundle of the
# base app + DLC) never showed up. Dropping the `a` parameter runs steamdb's
# unfiltered "Everything" search instead, which also returns Bundle rows.
STEAMDB_SEARCH_URL = "https://steamdb.info/search/?q={query}"
```

- The request is a plain `GET https://steamdb.info/search/?q={query}` (fetched via `SteamDbBrowserClient.fetch`, `steamdb.py:84-116`, a headed `patchright` Chromium session that waits out Cloudflare's managed challenge).
- **This directly contradicts the suspicion in the task**: the code comment (lines 29-32) documents that an earlier version *did* restrict the search to `a=app` (apps-tab only) and that this was identified as the bug causing bundle-only titles to be missed — and it has already been fixed by dropping the `a` param, switching to SteamDB's unfiltered "Everything" search, which returns both App and Bundle rows.
- Result parsing (`_RESULT_LINK_HREF`, line 39: `^/(app|bundle)/(\d+)/$`) explicitly matches both `/app/<id>/` and `/bundle/<id>/` permalinks. `_SteamDbLinkParser.handle_starttag` (lines 139-155) tags bundle results as `f"{kind}/{raw_id}"` (i.e. `"bundle/46228"`) vs a bare numeric id for apps, and `parse_steamdb_results` (lines 178-205) returns these as raw `(id, title)` pairs, capped at 10, deduping against the id-column's self-referential link text.

So: **SteamDB search currently does NOT restrict to non-bundle apps** — it already includes bundles by design (with a code comment recording the historical bug and fix).

## 2. `resolver.py` — usage of steamdb.py and overall flow

File: `/home/user/git/luckydonald/game_collections/src/game_collections/sources/humblebundle/resolver.py`

- `_search_steam` (lines 212-247): tries `store.steampowered.com` search first (cheap, `self.search("steam", title)`, line 221); only falls back to steamdb.info if there isn't a unique exact-title match among the steampowered.com candidates AND a `steamdb_fetch` callable was supplied (lines 225-227). On fallback, it builds `STEAMDB_SEARCH_URL.format(query=quote_plus(title))` (line 229) and calls `parse_steamdb_results(self._steamdb_fetch(url))` (line 230).
- The steamdb results are turned into `StoreCandidate`s at lines 237-246:
```python
url=f"https://store.steampowered.com/{result_id if '/' in result_id else f'app/{result_id}'}/",
qualified_id=f"steam:{result_id}",
```
  So a bundle result (`result_id == "bundle/46228"`) becomes `url="https://store.steampowered.com/bundle/46228/"` and `qualified_id="steam:bundle/46228"` — bundle candidates flow through fully intact into the resolution pipeline.
- `resolve_item` (lines 249-290): for each store in `item.redeem_on` (filtered to `ALLOWED_STORES`), calls `_search_steam`/`search`, checks for a unique exact-title match (`exact`), else calls the injected `choose` callback (interactive prompt or `None` in non-interactive mode), and appends the resulting `qualified_id`/`parse_store_identity(...)` value to `ids`. If nothing resolved for any store, it appends `f"unresolved:source:humblebundle:{item.machine_name}"` (line 286).
- `resolve_archive` (lines 292-344): dedupes distinct games across bundle tiers, resolves each once via `resolve_item`, and propagates each resolved game's `ids` + `unresolved_stores` back onto every tier copy via `HumbleResolution`.

## 3. Unresolved markers and custom-link (manual paste) parsing

- `unresolved:source:<source>:<key>` markers are produced by each source's resolver (e.g. `humblebundle/resolver.py:286`, `isthereanydeal/resolver.py` `UNRESOLVED_PREFIX = "unresolved:source:isthereanydeal:"` at line 18, `greenmangaming/resolver.py:202`).
- `search.py` (`_store_unresolved_prefix`, line 72-74) also produces a second kind of marker, `unresolved:store:<provider>:<slug>`, when the generic title-search-based `complete_game_list` flow (used by `game-collections complete`) fails a search.
- **Custom-link entry point**: `cli.py:253-280` (`_choose_store_candidate`, reused by `_choose_search_candidate` at 283-297) and the near-identical `_choose_gmg_store_candidate` (`cli.py:669-696`). When the user picks "Other…", it prompts:
```python
manual = typer.prompt(
    "Paste the store URL or direct ID; leave blank for unresolved",
    default="",
    show_default=False,
)
return manual or None
```
  The returned string is passed straight into `parse_store_identity(typed_provider, selected)` — for Humble at `resolver.py:283`, for the generic completion path at `search.py` (`resolve_title`, line ~119 `parse_store_identity(provider, selected)`).

- **Actual URL parsing** happens in `parse_store_identity` in `/home/user/git/luckydonald/game_collections/src/game_collections/sources/storefronts.py:58-128`. For Steam specifically (lines 81-97):
```python
if provider == "steam":
    if host not in STORE_HOSTS["steam"]:
        raise ValueError("Steam URLs must use store.steampowered.com")
    app_match = re.search(r"/app/(\d+)(?:/|$)", path)
    if app_match:
        return f"steam:{int(app_match.group(1))}"
    # A bundle (e.g. a "Deluxe Edition" only sold as a bundle of the base
    # app + DLC) has no single AppID; kept as its own `bundle/<id>` value
    # rather than a plain int so ownership matching (which needs a real
    # AppID) can tell it apart - see `completion.evaluate_completion`.
    bundle_match = re.search(r"/bundle/(\d+)(?:/|$)", path)
    if bundle_match:
        return f"steam:bundle/{int(bundle_match.group(1))}"
    raise ValueError("Steam URL does not contain an AppID or bundle ID")
```

**Confirmation: bundle URLs ARE already handled, not a failure case.** A pasted URL like `https://store.steampowered.com/bundle/46228/Forgive_Me_Father_2_Deluxe_Edition/` matches the `bundle_match` regex (`/bundle/(\d+)(?:/|$)`) and resolves cleanly to `steam:bundle/46228`. Only a URL with neither `/app/<id>/` nor `/bundle/<id>/` in its path raises `ValueError`. A bare positive decimal string (no URL) is also accepted directly as a Steam AppID (lines 71-76), but there is no equivalent "bare bundle id" shorthand — only the qualified form `steam:bundle/<id>` (via the `":" in raw` qualified-id branch at lines 64-69) or a full bundle URL.

## 4. Data model for storefront IDs/links

File: `/home/user/git/luckydonald/game_collections/src/game_collections/models.py`

```python
# line 12
PROVIDER_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
# line 14
NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

# lines 30-51
class QualifiedGameId(StrictModel):
    """A storefront-qualified game identifier such as ``steam:440``."""

    provider: NonEmptyString
    value: NonEmptyString

    @classmethod
    def parse(cls, raw: str) -> Self:
        """Parse the public compact identifier form."""
        provider, separator, value = raw.partition(":")
        if not separator or not PROVIDER_PATTERN.fullmatch(provider) or not value:
            raise ValueError(f"invalid qualified game ID: {raw!r}")
        return cls(provider=provider, value=value)

    def compact(self) -> str:
        """Return the public compact identifier form."""
        return f"{self.provider}:{self.value}"
```

`Game` (lines 63-87) stores raw compact strings in `ids: list[NonEmptyString]` and exposes them parsed via `qualified_ids` property.

**There is no dedicated "kind" enum for bundle vs. single-app.** A Steam bundle is represented purely as a convention within the flat `provider:value` string shape: `provider == "steam"` and `value` starting with the literal prefix `"bundle/"` (e.g. `"steam:bundle/46228"`), as opposed to a plain numeric appid string (e.g. `"steam:440"`). This convention is enforced/consumed in exactly three places:
1. `storefronts.py:93-96` — produces `steam:bundle/<id>` from a `/bundle/<id>/` URL.
2. `storefronts.py:147-148` (`product_url`) — special-cases the `bundle/` prefix to build `https://store.steampowered.com/bundle/<id>` (skipping the normal `{root}{marker}/{value}` app-shaped template).
3. `completion.py:44-53` (`evaluate_completion`) — explicitly skips any Steam id whose `value.startswith("bundle/")` when computing owned/missing AppID counts, because Steam's Web API owned-games list has no concept of "bundle ownership," only per-AppID ownership; this is the one place that actually treats bundle vs. app differently downstream.

There's no separate `StoreName`-like literal for "bundle" as a provider, no `BundleId` model, and no schema-level distinction — it's a string-prefix convention layered on top of the generic `provider:value` `QualifiedGameId` shape, applying only to the `steam` provider.