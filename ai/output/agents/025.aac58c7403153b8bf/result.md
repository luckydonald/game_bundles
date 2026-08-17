## Findings

**1. `search.py`** does not define its own normalizer — it imports and reuses `normalized_title` from `sources/storefronts.py` (via `sources/humblebundle/resolver.py` re-export). It's used for exact-match resolution only:

```python
# search.py:108-112
exact = [c for c in candidates if normalized_title(c.title) == normalized_title(title)]
if len(exact) == 1: ...
```

No fuzzy/similarity scoring anywhere in `search.py` — ambiguous cases (0 or >1 exact matches) fall through to the `choose` callback (human/CLI disambiguation), not an algorithm.

**2. `sources/storefronts.py:36-41`** — the actual normalization function, source of truth, used by three resolvers (humblebundle, greenmangaming, and reused in search.py):

```python
def normalized_title(value: str) -> str:
    """Normalize storefront punctuation and spacing for exact title comparison."""
    without_marks = value.translate(str.maketrans({"™": "", "®": "", "©": ""}))
    normalized = unicodedata.normalize("NFKD", without_marks).casefold()
    return "".join(character for character in normalized if character.isalnum())
```

Strips trademark/copyright marks, NFKD-normalizes + casefolds, then keeps only alnum chars (drops all spaces, punctuation, dashes, colons). It does **not** strip "the"/edition suffixes or do fuzzy matching — it's exact-match-after-normalization only, used for equality checks (`==`), not similarity scoring.

**3. `models.py:123`** — `GameList.validate_games` uses only `game.name.casefold()` as the uniqueness key. No richer normalize helper exists in the models layer; `casefold()` is the sole normalization there.

**4. `sources/common.py:72-91`** `merge_game_list` matches purely by `game.name.casefold()` (confirmed, docstring says "the same uniqueness key `GameList` itself enforces"). Grepping `src/` for normalize/fuzzy/similar/match_name/slugify/levenshtein/difflib turned up nothing else relevant — the only other "slugify" is `sources/isthereanydeal/provider_config.py:49` `slugify_provider_name`, which normalizes *shop/provider* names for config lookup, unrelated to game titles.

**5. `pyproject.toml`** — no fuzzy-matching library installed. Dependencies are `httpx`, `markdownify`, `patchright`, `pydantic`, `PyYAML`, `typer`, `vdf` (+ test/tui extras). No `rapidfuzz`/`thefuzz`/`python-Levenshtein`/`difflib`-based helper anywhere.

## Reusability

`storefronts.normalized_title` is a solid drop-in for a "normalized name" tier in a matching cascade (ids match > exact `name` == > `normalized_title(a) == normalized_title(b)` > ???). Nothing existing covers a fuzzy/"probably the same game" tier — that would be new, and would require adding a dependency (rapidfuzz is the modern standard) since none is present.