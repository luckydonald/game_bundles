The error comes from a `DigParseError` that the crawler records as a per-bundle error and then carries on. I found nothing in the repo that says why 2420's page lacks the span. I didn't edit anything, and I ignored the plan-mode note about writing a plan file because I'm read-only.

## Where it is raised
- `src/game_collections/sources/dailyindiegame/parser.py:198`, in `parse_bundle_page` (starts at line 194). The first thing it does is search for the title:
  ```python
  title_match = TITLE_PATTERN.search(html)
  if not title_match:
      raise DigParseError("bundle page is missing its DIG-contentOrangeBIG title span")
  ```
- `DigParseError(ValueError)` is defined at line 53.
- `TITLE_PATTERN` is at lines 30-32. It is a plain regex over the raw HTML, not a DOM selector: `r'<span class="DIG-contentOrangeBIG">(.*?)</span>'` with `re.IGNORECASE | re.DOTALL`.
- It is strict. It needs exactly `class="DIG-contentOrangeBIG"` with double quotes and no extra classes or attributes, so any layout variation would miss.
- A separate error, `"bundle page title span is empty"` (line 201), covers a span that is present but blank.
- After the title, the parser requires the price summary sentence (`SUMMARY_PATTERN`, line 207) and at least one Steam-linked game (`"bundle page has no Steam-linked games"`). Those are the other ways a nonexistent or empty bundle page would fail.

## What the crawler does on this error
- In `src/game_collections/sources/dailyindiegame/crawler.py`, `crawl_dig_offers` (lines 182-250) wraps each bundle in its own `try`.
- The `except (OSError, ValueError, DigCrawlError)` at line 245 appends `f"{url}: {error}"` to `errors` and the loop continues, so one bad page does not abort the rest.
- That is exactly the line you saw: `<url>: bundle page is missing its ...`.
- The CLI (`src/game_collections/cli.py:954-968`) echoes each `error: ...` to stderr and still reports `Wrote N file(s)`.
- It then does `raise typer.Exit(1)` if `report.errors` is non-empty. So the run is marked failed, even though everything else was archived.
- The `finally` block still closes the browser and runs `finish_scrape_git_session`.
- Because nothing is written for a failed bundle, 2420 is re-fetched on every run. There is no negative cache.
- `ai/errors/9.md:27` holds your logged error. It is the only mention of 2420 outside the URL, and it is the only DIG error in that log.

## How 2420 gets targeted
- With no `--url`, targets come from the index page `site_content_bundles.html` (`INDEX_URL`, crawler.py:36).
- `parse_bundle_index_page` (parser.py:117-125) takes every `site_weeklybundle_N.html` link on that page, in order, deduplicated by `_BundleLinksParser` (lines ~92-115).
- So 2420 was listed on the live index but its detail page had no title span.
- There is no sequence or "end of sequence" detection in the DIG crawler. It only walks the index links, and my grep for sequence handling or logging/warnings in `sources/dailyindiegame/` and the Green Man Gaming crawler found nothing.

## Archives
- `archives/dailyindiegame/bundle/` holds 91 bundle directories (`metadata.json` and `source.json` each). There is no raw HTML cache, only normalized metadata plus a source dict.
- Bundle 2420 does not exist anywhere: `find . -name "*2420*"` found nothing, and `grep -rl 2420 archives/dailyindiegame` found nothing. `lists/dailyindiegame/bundle/` has no 2420.yml either.
- The archived numbers are 1, 2, 1230, 2135, 2330-2352, 2357-2378, 2390, 2391, 2393-2411, and 2421-2441. Everything from 2412 to 2420 is missing.
- The other gaps (2353-2356, 2379-2389, 2392) are probably numbers that were never public weekly bundles.
- 2421-2441 parse fine, so 2420 is likely the oldest or edge entry still linked on the index.

## Tests
- `tests/test_dailyindiegame_parser.py`:
  - `test_bundle_page_requires_a_title` (lines 96-103) asserts that `"<html>no title here</html>"` raises `DigParseError`. This is the test that pins the current hard-fail behavior.
  - The `{title}` fixture is at line 20, and `test_bundle_page_without_adult_suffix_is_not_flagged` is at line 86.
- `tests/test_dailyindiegame_crawler.py`:
  - `test_crawl_isolates_per_offer_failures` (lines 154-167) checks that a `ValueError("boom")` from fetch produces one `errors` entry and no offers.
  - The other crawler tests cover discovery from the index, explicit URL, cached skip, and stale-cache refetch.
  - No test covers a page that parses but lacks the title.
- Fixture markup is at line 109 of the crawler test.

## README
`src/game_collections/sources/README.md` lines 47-50 and 52-58 cover DailyIndieGame.
- Point 1 says the site sits behind a Cloudflare managed challenge.
- Point 3 says the title is read from the first `DIG-contentOrangeBIG` span because the name varies ("DIG Bundle N - ADULT", "FRIDAY BARGAIN N", "presumably others not yet seen").
- It says nothing about nonexistent, expired or empty bundle pages.

## Likely causes
1. **Cloudflare challenge or interstitial page.** `DigBrowserClient.fetch` (crawler.py:84-123) stops polling when the tab title no longer contains "Just a moment" or starts with "Loading ". It then waits a bounded 8 seconds for network idle and a fixed 3 seconds, and returns `page.content()` without checking it. A challenge page or "Loading..." shell that outlasts that wait would produce this exact error. It would be intermittent, so a rerun, or `--url .../site_weeklybundle_2420.html` with `--refresh`, would show it.
2. **Expired, withdrawn or nonexistent bundle.** The site may serve a stub or redirect page, or an "ended" layout, for an old bundle still linked from the index. I think this is the most likely cause given the 2412-2420 gap, but it isn't verified, since it needs a live fetch.
3. **A layout variation.** A different promotion type could use another class or a changed attribute (for example `class="DIG-contentOrangeBIG x"`). The strict regex would miss it, and the README already admits unseen naming schemes.

## Graceful handling options
- Add a dedicated exception, for example `DigBundleUnavailableError(DigParseError)`, raised when the title span is missing, and optionally when the price summary or games are also missing.
- Catch it in `crawl_dig_offers` (around crawler.py:245) before the generic handler and log it as `log(f"Bundle {index}/{total}: {number} skipped (no title span)")`. Don't append it to `errors`, so the CLI exit code stays 0.
- Distinguish a challenge page from an empty bundle page first:
  - Check for "Just a moment", "cf-challenge" or "Attention Required" markers, or a very short body.
  - Treat a challenge page as a real error or retry, as `fetch` does.
  - Treat a clean DIG page that lacks the span as a skip with a warning.
- To keep the skip from repeating every run, optionally persist a negative marker or an index-based cutoff.
- Update `test_bundle_page_requires_a_title` and add a crawler test where `fetch` returns a page without the span and the report has no errors.
- Add a README note about the skip.
- Start by fetching 2420 once and saving the HTML, to tell the three causes apart.