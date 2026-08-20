"""Fallback Steam title search against steamdb.info's own app search.

steamdb.info sits behind a Cloudflare *managed* challenge (confirmed live:
`cType: "managed"`, loading `/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1`) -
this is Cloudflare's interactive/Turnstile-class challenge, not the older
simple JS-math puzzle. Neither a plain `httpx`/`curl` fetch, TLS-fingerprint
impersonation (`curl_cffi` with `impersonate="chrome"`), nor a JS-VM emulator
(`cloudscraper`, in both its PyPI release and a third-party fork) gets past
it - all still 403, and the JS-VM fork just hangs indefinitely instead of
failing cleanly. Only a real, **headed** browser session actually executing
the challenge works, same as the `dailyindiegame` source's `DigBrowserClient`.
"""

from __future__ import annotations

import re
import time
from html.parser import HTMLParser


__all__ = [
    "STEAMDB_SEARCH_URL",
    "SteamDbBrowserClient",
    "SteamDbCrawlError",
    "parse_steamdb_results",
]


STEAMDB_SEARCH_URL = "https://steamdb.info/search/?a=app&q={query}"

# Matches a search result row's own permalink (e.g. "/app/1123050/"), not the
# absolute https://store.steampowered.com/app/<id>/... "store page" link that
# sits alongside it for apps that still have a live listing.
_APP_LINK_HREF = re.compile(r"^/app/(\d+)/$")


class SteamDbCrawlError(RuntimeError):
    """Fetching a steamdb.info page failed."""

# end class SteamDbCrawlError


class SteamDbBrowserClient:
    """Browser fetcher for steamdb.info's Cloudflare-gated pages.

    Modeled directly on `dailyindiegame.crawler.DigBrowserClient`: only a
    *headed* `patchright` context (not headless, and not stock Playwright)
    actually clears the challenge.
    """

    def __init__(self, timeout: float = 30.0, attempts: int = 3) -> None:
        # Imported lazily so importing this module (e.g. for unit tests that
        # inject a fake `steamdb_fetch`) never requires `patchright` or its
        # downloaded browser binary to be present.
        import tempfile

        from patchright.sync_api import sync_playwright

        self._attempts = attempts
        self._timeout_ms = timeout * 1000
        self._playwright = sync_playwright().start()
        self._user_data_dir = tempfile.mkdtemp(prefix="steamdb-patchright-")
        self._context = self._playwright.chromium.launch_persistent_context(
            self._user_data_dir,
            headless=False,
            no_viewport=True,
        )
    # end def __init__

    def close(self) -> None:
        """Close the browser and its Playwright driver."""
        import shutil

        self._context.close()
        self._playwright.stop()
        shutil.rmtree(self._user_data_dir, ignore_errors=True)
    # end def close

    def fetch(self, url: str) -> str:
        """Fetch one page's rendered HTML, waiting out the Cloudflare challenge."""
        last_error: Exception | None = None
        for attempt in range(1, self._attempts + 1):
            page = self._context.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=self._timeout_ms)
                deadline = time.monotonic() + self._timeout_ms / 1000
                while time.monotonic() < deadline:
                    title = page.title()
                    if "Just a moment" not in title and "Checking your browser" not in title:
                        break
                    # end if
                    time.sleep(1)
                # end while
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:  # noqa: BLE001 - timeout is expected, not fatal
                    pass
                # end try
                return page.content()
            except Exception as error:  # noqa: BLE001 - Playwright raises its own broad errors
                last_error = error
                if attempt == self._attempts:
                    break
                # end if
                time.sleep(0.5 * (2 ** (attempt - 1)))
            finally:
                page.close()
            # end try
        # end for
        raise SteamDbCrawlError(f"request failed for {url}: {last_error}") from last_error
    # end def fetch

# end class SteamDbBrowserClient


class _SteamDbLinkParser(HTMLParser):
    """Collect each result row's own `/app/<id>/` permalink and visible title.

    Confirmed live against a real results table: each row has an ID-column
    link (`<a href="/app/<id>/">1123050</a>`, text equal to the id itself) and
    a separate name-column link (`<a href="/app/<id>/">GRIME</a>`) - the type
    marker for non-Game rows (`Music`/`Demo`/DLC/...) is its own sibling
    `<i class="stype">...</i>`, never part of the anchor's own text, so no
    special handling is needed to keep it out of the title.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._appid: str | None = None
        self._parts: list[str] = []
        self.links: list[tuple[str, str]] = []
    # end def __init__

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        # end if
        href = dict(attrs).get("href") or ""
        match = _APP_LINK_HREF.match(href)
        if match is None:
            return
        # end if
        self._appid = match.group(1)
        self._parts = []
    # end def handle_starttag

    def handle_data(self, data: str) -> None:
        if self._appid is not None:
            self._parts.append(data)
        # end if
    # end def handle_data

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._appid is None:
            return
        # end if
        text = "".join(self._parts).strip()
        if text:
            self.links.append((self._appid, text))
        # end if
        self._appid = None
        self._parts = []
    # end def handle_endtag

# end class _SteamDbLinkParser


def parse_steamdb_results(html: str) -> list[tuple[str, str]]:
    """Extract ranked (appid, title) pairs from a steamdb.info search results page.

    Returns raw pairs rather than `resolver.StoreCandidate` to avoid a circular
    import (`resolver.py` imports this module, not the other way around); the
    caller builds `StoreCandidate(title=title, url=f"https://store.steampowered.com/app/{appid}/", qualified_id=f"steam:{appid}")`.
    """
    parser = _SteamDbLinkParser()
    parser.feed(html)
    results: list[tuple[str, str]] = []
    seen: set[str] = set()
    for appid, title in parser.links:
        if title == appid or appid in seen:
            # The ID-column link's own text is just the numeric id; skip it
            # so only the name-column link produces a result.
            continue
        # end if
        seen.add(appid)
        results.append((appid, title))
        if len(results) == 10:
            break
        # end if
    # end for
    return results
# end def parse_steamdb_results
