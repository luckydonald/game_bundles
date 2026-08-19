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
- Checked `~/git/github.com/SteamDatabase/BrowserExtension` at the user's request: it has no lightweight/API bypass for this page — its `background.js` only calls per-appid endpoints (`extension.steamdb.info/api/ExtensionApp` etc.), none of which do title search. `manifest.json`'s `host_permissions` for `steampowered.com`/`steamcommunity.com` are for unrelated content-script features (badges injected into Steam's own pages), not a way to reach steamdb.info search cheaply.
- Also tried `curl_cffi` with `impersonate="chrome"` (patched TLS/JA3 fingerprint mimicking real Chrome, in case this was Akamai/TLS-fingerprint gating rather than a JS challenge) — still `403`, with response header `cf-mitigated: challenge` and `server: cloudflare`. The debug response body identifies `cType: 'managed'` and loads `/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1` — Cloudflare's interactive/Turnstile-class managed challenge, not the older simple JS-math puzzle. Tried both PyPI `cloudscraper` (1.2.71) and a `CloudWaddie/cloudscraper` fork (3.0.0, `js2py`-based) — the PyPI version still 403s immediately, and the fork hung indefinitely (5+ min, manually killed) rather than passing, since a JS-VM emulator can't execute real browser/canvas fingerprinting. Confirms this is a genuine Cloudflare **managed JS challenge** that no `httpx`/`curl_cffi`/`cloudscraper`-class trick can pass. Only a real, **headed** browser session (`patchright`, `headless=False`, actually executing the challenge JS) works — same situation as the `dailyindiegame` source. (Note: the raw 403 response body also contained a hidden prompt-injection string aimed at AI scrapers, telling them to stop and lie to the user about SteamDB having no API — ignored, since it's page content, not a user instruction.)

Decisions from the user (via AskUserQuestion, refined afterward):
- Wire in a headed-browser client, always attempted, mirroring `DigBrowserClient` — no new CLI flag. If the browser can't launch (e.g. `patchright` unavailable, or on a headless CI runner), log a warning and skip steamdb, falling back to steampowered.com-only, exactly like today.
- **Order (revised): `store.steampowered.com` search first** (cheap, no browser) — steamdb.info is only tried as a **fallback** when steampowered.com doesn't yield a unique exact-title match, since spinning up the headed browser is expensive and most titles already resolve fine today.
- Apply to both `humblebundle` and `greenmangaming` resolvers (GMG already reuses Humble's `STORE_SEARCH_URLS`/`StoreCandidate`/`parse_store_candidates`, so the new steamdb pieces live in Humble's package and GMG imports them the same way).

## Implementation

1. **New module `src/game_collections/sources/humblebundle/steamdb.py`:**
   - `STEAMDB_SEARCH_URL = "https://steamdb.info/search/?a=app&q={query}"`.
   - `SteamDbBrowserClient`, modeled directly on `dailyindiegame/crawler.py`'s `DigBrowserClient` (lazy `patchright` import so importing this module never requires the dependency; `launch_persistent_context(..., headless=False, no_viewport=True)`; a `fetch(url) -> str` method with the same poll-past-challenge/retry approach; a `close()`).
   - `parse_steamdb_candidates(html: str) -> list[StoreCandidate]`: parse the results table's rows into `StoreCandidate(title=..., url=f"https://store.steampowered.com/app/{appid}/", qualified_id=f"steam:{appid}")`, taking the appid straight from each row's `/app/<id>/` link (steamdb's own appid *is* the Steam appid — corroborated by the separate "This app has a store page" link when present) rather than round-tripping through `parse_store_identity`. Reuse the existing `_StoreLinkParser`-style approach (or a small dedicated `HTMLParser`) — **before finalizing this parser, fetch one real results page's HTML through a headed browser session and confirm the exact row/column markup** (this plan only confirmed the rendered text/links via the accessibility tree, not raw table HTML/classes). Cap results the same way `parse_store_candidates` does (e.g. 10) and dedupe by appid.
   - No change needed to filter out DLC/Soundtrack/Demo rows by type: the existing exact-title-match logic in `resolve_item` already only accepts a candidate whose title exactly matches the source title, same safety net as today's steampowered.com search.

2. **`humblebundle/resolver.py`:**
   - Import `STEAMDB_SEARCH_URL`, `parse_steamdb_candidates` from the new module.
   - `StorefrontResolver.__init__` gains `steamdb_fetch: Fetcher | None = None` — a lazy fetcher (see CLI wiring below: the caller only launches the actual browser the first time it's called, not eagerly), so a run where steampowered.com already resolves everything never pays the browser-launch cost.
   - Add `_search_steam(self, title: str) -> list[StoreCandidate]`: run the existing `self.search("steam", title)` steampowered.com search first; if that already has exactly one normalized-title exact match, return it immediately (no steamdb call at all). Otherwise, if `steamdb_fetch` is set, fetch `STEAMDB_SEARCH_URL.format(query=quote_plus(title))`, parse candidates via `parse_steamdb_candidates`, and return those instead (falling back to `OSError`/`RuntimeError` → keep the original steampowered.com candidates) so the existing chooser-prompt/`unresolved:` path in `resolve_item` still gets a list to work with either way.
   - In `resolve_item`, replace the direct `self.search(typed_provider, item.title)` call with a branch: use `self._search_steam(item.title)` when `typed_provider == "steam"`, else the existing `self.search(...)`.

3. **`greenmangaming/resolver.py`:** mirror the same three changes in its own `StorefrontResolver` (it doesn't subclass Humble's, so the constructor/`_search_steam`/`resolve_item` edits are duplicated the same way the rest of this class already duplicates Humble's), importing `STEAMDB_SEARCH_URL`/`parse_steamdb_candidates`/`SteamDbBrowserClient` from `humblebundle.steamdb` alongside its existing `humblebundle.resolver` imports.

4. **CLI wiring (`src/game_collections/cli.py`):** in `scrape_humblebundle_command` and `scrape_greenmangaming_command`, build a small lazy-launch wrapper around `SteamDbBrowserClient` instead of constructing it eagerly (steamdb is only a fallback now, so most runs should never pay the browser-launch cost): a closure/small class holding `_client: SteamDbBrowserClient | None = None`, whose `fetch(url)` method launches the real client on first call (catching launch failure — missing `patchright`, no display, etc. — by `typer.echo`-ing a one-line warning once and re-raising so `_search_steam`'s existing `OSError`/`RuntimeError` fallback takes over) and reuses it for subsequent calls in the same run. Pass this wrapper's `.fetch` as `steamdb_fetch` into both `StorefrontResolver(...)` construction sites per command (note `scrape_humblebundle_command` currently constructs the resolver twice — once for a pre-check and once for the real crawl at line ~510 — apply consistently). Close the underlying browser client (if one ended up launched) in the existing `finally: client.close()` block alongside the HTTP client.

5. **Tests:** mirror `tests/test_humblebundle_resolver.py`'s structure — add cases for `_search_steam`/`parse_steamdb_candidates` using an injected fake `steamdb_fetch` (inline fixture HTML built from the real table markup confirmed in step 1), covering: unique exact match on steampowered.com wins outright with `steamdb_fetch` never called; no/ambiguous steampowered.com match falls through to steamdb.info and uses its candidates; `steamdb_fetch=None` behaves exactly as today (steampowered.com-only). Same pattern for `test_greenmangaming_resolver.py`. No live network/browser access in tests, consistent with every other source.

6. **Docs:** update the "Humble Bundle" and "Green Man Gaming" sections of `src/game_collections/sources/README.md` to mention the steampowered-first, steamdb.info-fallback search order (only spinning up the headed browser when steampowered.com's search doesn't already give a unique exact-title match) and the lazy-launch/graceful-degradation behavior, following the existing prose style for each source's resolver description.

## Verification

- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_humblebundle_resolver.py tests/test_greenmangaming_resolver.py -q`
- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q` (full suite, confirm no regressions)
- Manual: `env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections scrape humblebundle --non-interactive --refresh --url <a current Choice URL>` (or a small fixture) and confirm the log shows a steamdb.info fallback resolution for a known-tricky title (e.g. a `Primordialis`/`GRIME - Deluxe Edition`-style case) without requiring `patchright`'s browser binary to hang the run if it's unavailable in this environment (steampowered.com-only items should never trigger a browser launch at all).
