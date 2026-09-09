# Fix: HTML entities left in GreenManGaming bundle/game titles

## Context

`scrape greenmangaming` writes bundle names, item titles, and product
metadata (DRM/platform/developer/publisher/description) straight from
regex matches over the raw HTML source. Unlike the other sources
(`humblebundle`, `dailyindiegame` use `HTMLParser(convert_charrefs=True)`;
`isthereanydeal` uses BeautifulSoup's `get_text()`), GreenManGaming's
parser never decodes HTML character references, so entities like
`&#x27;` and `&amp;` survive into the archived/list YAML titles (e.g.
"Kena: Bridge of Spirits&#x27;s Soundtrack" instead of the apostrophe).

## Root cause

`src/game_collections/sources/greenmangaming/parser.py`'s `_strip_tags`
helper (line 56) only strips tags via regex and collapses whitespace —
it never calls `html.unescape()`. Every text field in this parser
(`name`, `GmgItem.title`, `drm`, `platform`, `developer`, `publisher`,
`description`) is derived from `_strip_tags(...)`, so fixing this one
helper fixes all of them.

## Fix

In `src/game_collections/sources/greenmangaming/parser.py`:
- Add `import html` (stdlib) alongside the existing imports.
- Update `_strip_tags` to unescape entities after stripping tags and
  before collapsing whitespace:
  ```python
  def _strip_tags(value: str) -> str:
      return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value)).split())
  # end def _strip_tags
  ```
  (Unescape after tag-stripping, not before, so an entity like `&lt;`
  can't be misread as a tag delimiter.)

No other call sites need touching — `ITEM_PATTERN`/`H1_PATTERN`/
`DRM_PATTERN`/etc. all feed into `_strip_tags`.

## Out of scope

- `isthereanydeal/parser.py` has its own separate `_strip_tags` with
  the same shape, but its inputs come from BeautifulSoup `get_text()`
  which already unescapes entities, so it's not affected by this bug
  and is left alone.
- Existing archived/list YAML files already written with escaped
  entities are not backfilled by this change (no re-scrape triggered
  here); only future scrapes will produce clean text.

## Verification

- Add/extend a case in `tests/test_greenmangaming_parser.py`: include
  an entity (e.g. `&#x27;` or `&amp;`) in the `BUNDLE_PAGE` H1 title
  and/or an item title, and assert the parsed `GmgArchive.name` /
  `GmgItem.title` contain the decoded character instead of the raw
  entity. Do the same for one `PRODUCT_FRAGMENT` field (e.g. developer
  or publisher) to cover `parse_product_fragment`.
- Run `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_greenmangaming_parser.py -q`.
- Run the full suite once: `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q`.
