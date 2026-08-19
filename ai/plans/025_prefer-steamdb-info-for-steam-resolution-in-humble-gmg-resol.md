# Prefer steamdb.info for Steam resolution in Humble/GMG resolvers

## Context

`StorefrontResolver.search("steam", title)` (in both
`src/game_collections/sources/humblebundle/resolver.py` and the near-duplicate
class in `src/game_collections/sources/greenmangaming/resolver.py`) currently
only searches `store.steampowered.com/search/?term=...`. For titles like
Humble's `Primordialis` or `GRIME - Deluxe Edition`, that search is often noisy
or misses the exact product, forcing manual review via `--non-interactive`'s
`unresolved:` markers or the interactive chooser prompt.

The user wants `steamdb.info`'s own app search tried first for the `steam`
provider, since it's usually better at finding the exact product. Confirmed
live during planning:

- `curl -A "<Chrome UA>" https://steamdb.info/search/?a=app&q=Primordialis` → `403` (Cloudflare-gated), and `WebFetch` on the same URL also 403s.
- A real (extension-connected) browser tab loads it fine and returns a results table, e.g. for `q=Primordialis`: rows `3011360 Primordialis`, `4228830 Primordialis Soundtrack`, `3267910 Primordialis Demo`. Each result row has a `Name` link `<a href="/app/<id>/">Name</a>` (this is the page's own internal link, not the Steam store URL) and, when the app still has a live store page, a separate `This app has a store page` link to `https://store.steampowered.com/app/<id>/...`.
- Checked `~/git/github.com/SteamDatabase/BrowserExtension` at the user's request: it has no lightweight/API bypass for this page — its `background.js` only calls per-appid endpoints (`extension.steamdb.info/api/ExtensionApp` etc.), none of which do title search. `manifest.json`'s `host_permissions` for `steampowered.com`/`steamcommunity.com` are for unrelated content-script features (badges injected into Steam's own pages), not a way to reach steamdb.info search cheaply. So this needs the same approach as the `dailyindiegame` source: a real, **headed** browser session (`patchright`, `headless=False`) — a plain `httpx`/`curl` fetch or a headless browser both get blocked.

Decisions from the user (via AskUserQuestion):
- Wire in a headed-browser client, always attempted, mirroring `DigBrowserClient` — no new CLI flag. If the browser can't launch (e.g. `patchright` unavailable, or on a headless CI runner), log a warning and fall back to steampowered.com-only, exactly like today.
- Order: try steamdb.info first; only fall back to `store.steampowered.com` search when steamdb doesn't yield a unique exact-title match (not a full replacement).
- Apply to both `humblebundle` and `greenmangaming` resolvers (GMG already reuses Humble's `STORE_SEARCH_URLS`/`StoreCandidate`/`parse_store_candidates`, so the new steamdb pieces live in Humble's package and GMG imports them the same way).

## Implementation

1. **New module `src/game_collections/sources/humblebundle/steamdb.py`:**
   - `STEAMDB_SEARCH_URL = "https://steamdb.info/search/?a=app&q={query}"`.
   - `SteamDbBrowserClient`, modeled directly on `dailyindiegame/crawler.py`'s `DigBrowserClient` (lazy `patchright` import so importing this module never requires the dependency; `launch_persistent_context(..., headless=False, no_viewport=True)`; a `fetch(url) -> str` method with the same poll-past-challenge/retry approach; a `close()`).
   - `parse_steamdb_candidates(html: str) -> list[StoreCandidate]`: parse the results table's rows into `StoreCandidate(title=..., url=f"https://store.steampowered.com/app/{appid}/", qualified_id=f"steam:{appid}")`, taking the appid straight from each row's `/app/<id>/` link (steamdb's own appid *is* the Steam appid — corroborated by the separate "This app has a store page" link when present) rather than round-tripping through `parse_store_identity`. Reuse the existing `_StoreLinkParser`-style approach (or a small dedicated `HTMLParser`) — **before finalizing this parser, fetch one real results page's HTML through a headed browser session and confirm the exact row/column markup** (this plan only confirmed the rendered text/links via the accessibility tree, not raw table HTML/classes). Cap results the same way `parse_store_candidates` does (e.g. 10) and dedupe by appid.
   - No change needed to filter out DLC/Soundtrack/Demo rows by type: the existing exact-title-match logic in `resolve_item` already only accepts a candidate whose title exactly matches the source title, same safety net as today's steampowered.com search.

2. **`humblebundle/resolver.py`:**
   - Import `STEAMDB_SEARCH_URL`, `parse_steamdb_candidates` from the new module.
   - `StorefrontResolver.__init__` gains `steamdb_fetch: Fetcher | None = None`.
   - Add `_search_steam(self, title: str) -> list[StoreCandidate]`: if `steamdb_fetch` is set, fetch `STEAMDB_SEARCH_URL.format(query=quote_plus(title))`, parse candidates, and return them if exactly one has a normalized-title exact match; otherwise (or on `OSError`/`RuntimeError`) fall through to the existing `self.search("steam", title)` steampowered.com path.
   - In `resolve_item`, replace the direct `self.search(typed_provider, item.title)` call with a branch: use `self._search_steam(item.title)` when `typed_provider == "steam"`, else the existing `self.search(...)`.

3. **`greenmangaming/resolver.py`:** mirror the same three changes in its own `StorefrontResolver` (it doesn't subclass Humble's, so the constructor/`_search_steam`/`resolve_item` edits are duplicated the same way the rest of this class already duplicates Humble's), importing `STEAMDB_SEARCH_URL`/`parse_steamdb_candidates`/`SteamDbBrowserClient` from `humblebundle.steamdb` alongside its existing `humblebundle.resolver` imports.

4. **CLI wiring (`src/game_collections/cli.py`):** in `scrape_humblebundle_command` and `scrape_greenmangaming_command`, after constructing the existing HTTP client, try to construct a `SteamDbBrowserClient`; on any exception (missing dependency, launch failure) catch it, `typer.echo` a one-line warning to stderr, and proceed with `steamdb_fetch=None`. Pass `steamdb_fetch=steamdb_client.fetch if steamdb_client else None` into both `StorefrontResolver(...)` construction sites per command (note `scrape_humblebundle_command` currently constructs the resolver twice — once for a pre-check and once for the real crawl at line ~510 — apply consistently). Close the steamdb client in the existing `finally: client.close()` block alongside the HTTP client, if one was created.

5. **Tests:** mirror `tests/test_humblebundle_resolver.py`'s structure — add cases for `_search_steam`/`parse_steamdb_candidates` using an injected fake `steamdb_fetch` (inline fixture HTML built from the real table markup confirmed in step 1), covering: unique exact match on steamdb wins outright; no/ambiguous steamdb match falls back to the steampowered.com fetch; `steamdb_fetch=None` behaves exactly as today. Same pattern for `test_greenmangaming_resolver.py`. No live network/browser access in tests, consistent with every other source.

6. **Docs:** update the "Humble Bundle" and "Green Man Gaming" sections of `src/game_collections/sources/README.md` to mention the steamdb-first, steampowered-fallback search order and the headed-browser requirement/graceful-degradation, following the existing prose style for each source's resolver description.

## Verification

- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_humblebundle_resolver.py tests/test_greenmangaming_resolver.py -q`
- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q` (full suite, confirm no regressions)
- Manual: `env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections scrape humblebundle --non-interactive --refresh --url <a current Choice URL>` (or a small fixture) and confirm the log shows a steamdb-first resolution for a known-tricky title (e.g. a `Primordialis`/`GRIME - Deluxe Edition`-style case) without requiring `patchright`'s browser binary to hang the run if it's unavailable in this environment.
