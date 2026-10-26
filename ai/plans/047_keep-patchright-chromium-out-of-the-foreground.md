# Keep patchright Chromium out of the foreground

## Context

`DigBrowserClient` (`sources/dailyindiegame/crawler.py:57`) and `SteamDbBrowserClient` (`sources/humblebundle/steamdb.py:68`) both launch a headed `patchright` persistent context, which Cloudflare requires.
Each `fetch()` calls `context.new_page()` per attempt, and every new tab makes Chromium activate itself, so the window jumps to the front repeatedly during a scrape.
Goal: stay headed, but stop opening a new tab per fetch and start minimized.
Applies to both launch sites.

## Approach

1. New module `src/game_collections/sources/browser.py` (own concern, no private-prefixed names, bare `# end …` comments) holding the shared launch logic.
   - `launch_background_context(playwright, user_data_dir) -> BrowserContext` wraps `chromium.launch_persistent_context(..., headless=False, no_viewport=True, args=["--start-minimized"])`.
   - A comment explains why: Cloudflare needs headed, so we minimize rather than hide.
2. Reuse one page across fetches instead of `new_page()` per fetch.
   - Each client creates its page once (`context.pages[0]` if present, else `new_page()`) and `fetch()` navigates it with `goto`, so no new tab means no new activation.
   - Remove the `finally: page.close()`. Close the page only in the `except` path of a failed attempt, then open a fresh one for the retry, and close it in `close()`.
3. Update both clients to call the helper and drop the duplicated launch code.
   Update the docstrings and the headed-browser note in `sources/README.md` (minimized, one reused tab).

No `osascript` / focus-restore logic.

## Verification

- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests -q -k "dailyindiegame or steamdb"` (fake `fetch` injected, so the `patchright` import must stay lazy).
- Add a unit test for `browser.py` with a fake playwright object asserting `headless=False` and `--start-minimized` in `args`.
- Manual: `game-collections scrape dailyindiegame --refresh` while working in another app; confirm the window stays in the background across several pages.
- Commit per repo style (`commit-with-lplp-style`, explicit paths, message via `ai/git/pending-commit.md`).

## Risk

If Cloudflare rejects the minimized window, fall back to `--window-position=-2400,-2400` in the same helper.
