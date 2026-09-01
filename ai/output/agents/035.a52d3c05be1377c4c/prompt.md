In /home/user/git/luckydonald/game_collections, find every place in src/game_collections/sources/**/*.py that constructs a `GameList(...)` object (used to write a `lists/**/*.yml` file). This includes at least humblebundle/crawler.py, greenmangaming/crawler.py, dailyindiegame/crawler.py, isthereanydeal/crawler.py.

For each call site, report:
- file path and line number
- the surrounding function name
- whether it's for a fresh/authoritative crawl or something else

Also check tests/fixtures/ for any existing golden/snapshot YAML files representing scraped lists (e.g. under tests/fixtures/humblebundle, tests/fixtures/isthereanydeal, etc.) that assert exact YAML output, since adding a new field to the GameList model would change their expected output. List a few example fixture file paths and which test file(s) read them (grep for "fixtures" in tests/test_*.py touching these sources).

Keep the report under 350 words, just facts with file:line references, no analysis needed.