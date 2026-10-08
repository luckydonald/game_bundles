Findings (read-only; nothing modified):

**Model**: `/Users/user/Documents/programming/Python/game_bundles/src/game_collections/sources/humblebundle/models.py:33-39`
```python
class HumbleLink(StrictModel):
    """A named external party such as a developer or publisher."""
    name: NonEmptyString
    url: HttpUrl | None = None
```
Used by `HumbleItem.developers` and `.publishers` (models.py:78-79). `HttpUrl` is imported at line 8. Other `HttpUrl` fields in the same file (lines 76, 77, 92, 127, 129, 186) take values from the same sort of raw scraped strings, so they could hit the same problem. `HumbleCharity.url` (127) and `logo_url` (129) go through the same `_optional_url`.

**Parser**: `/Users/user/Documents/programming/Python/game_bundles/src/game_collections/sources/humblebundle/parser.py`
- `_links` is at line 393. It is called at lines 476-477:
  ```python
  developers=_links(raw.get("developers"), "developer-name", "developer-url"),
  publishers=_links(raw.get("publishers"), "publisher-name", "publisher-url"),
  ```
  ```python
  links.append(HumbleLink(name=raw[name_key], url=_optional_url(raw.get(url_key))))
  ```
- `_optional_url` is at line 306. It only strips whitespace and returns `None` if the result is empty. It does no scheme handling.
  ```python
  def _optional_url(value: object) -> str | None:
      if not isinstance(value, str): return None
      stripped = value.strip()
      return stripped or None
  ```
- Other callers of `_optional_url`: line 595 (charity `url`), 597 (charity `logo_url`), 716 (`cover_art_url`), 740 (charity logo). So a fix inside `_optional_url` would cover all of them.
- `urljoin` is imported at line 11 and used once, at line 605 (`urljoin(HUMBLE_ROOT, page_url)`).

**Existing normalization helpers**: none. A grep for `normalize.*url` or `scheme` found nothing reusable. The only scheme checks are host allowlists in the crawlers (`humblebundle/crawler.py:137`, `greenmangaming/crawler.py:123`, `dailyindiegame/crawler.py:150`). `src/game_collections/models.py:132` has `url: AnyHttpUrl | None`, which is a different model.

**Tests**: `/Users/user/Documents/programming/Python/game_bundles/tests/test_humblebundle_parser.py`
- Line 59 is the only link fixture: `"developers": [{"developer-name": "Example Dev", "developer-url": "https://dev.example/"}]`. It is in `test_bundle_page_normalizes_metadata_and_cumulative_tiers` (line 51).
- The other fixtures use `"developers": []` and `"publishers": []`.
- There is no test for a scheme-less, empty or invalid URL.
- The `starlight` string doesn't appear in `tests/`. `tests/fixtures/` contains only a `steam` directory.
- My `grep -l starlight` over `archives` and `ai` matched nothing under humblebundle, though it did print three `archives/isthereanydeal/bundle/...` files. Those files are unrelated to this error, and I didn't check which ones contain "starlight".

**Archive schema**: `/Users/user/Documents/programming/Python/game_bundles/schemas/humblebundle-archive.schema.json`
- The `HumbleLink` definition is at lines 326-355.
- Its `url` is `anyOf [{"format":"uri","maxLength":2083,"minLength":1,"type":"string"}, {"type":"null"}]`.
- It is referenced at lines 176 and 250.
- The schema is generated from the pydantic models (see `src/game_collections/schema.py`). A change to the type, such as a `BeforeValidator`, shouldn't change the schema, but the schema would need regenerating if the type did change.

**Suggested fix location**: make `_optional_url` prepend `https://` (or `http://`) when the value has no scheme and looks like a host. For example, treat `www.starlight.org` as `https://www.starlight.org`, and handle `//host` as well. Drop values that are still invalid, so a bad vendor link doesn't fail the whole page. Add parser tests in `tests/test_humblebundle_parser.py` for a scheme-less developer URL.