Good — this confirms and completes the picture. Here's the answer to the follow-up:

## Where the "DLC" badge/flag comes from, data-wise

**Raw source field:** in the embedded `webpack-bundle-page-data` JSON for each bundle tier item, Humble includes an optional `cta_badge` object:

```json
"cta_badge": {"badge": "dlc"}
```

Confirmed live in the repo's own archived fixtures, e.g. `archives/humblebundle/bundle/2026-08-12_handsome-husbandos/source.json` → `bundle_data.tier_item_data.adatewithdeathdeluxedlcpack.cta_badge == {"badge": "dlc"}` and `...ourlife_beginningsandalways_dlcpack.cta_badge == {"badge": "dlc"}` — these are exactly the two items the original parser commit was built/tested against. Across all archived bundles the observed `badge` values are only `"dlc"`, `"coupon"`, and `"coming_soon"` (this is presumably also what renders the little "DLC"/"COUPON"/"COMING SOON" pill badges on the actual Humble Bundle web page UI).

**Where it's already parsed (but only into a general-purpose tag, and only for bundle pages, not Choice pages):**
`src/game_collections/sources/humblebundle/parser.py`, `_bundle_item()`, lines 318–321:
```python
badge = raw.get("cta_badge")
tags: list[str] = []
if isinstance(badge, dict) and isinstance(badge.get("badge"), str):
    tags.append(badge["badge"].title())
```
So `HumbleItem.tags` already ends up containing `"Dlc"` (title-cased) for exactly the items Humble itself flags as DLC. This happens in the same function (`_bundle_item`) as the unconditional `_parse_dlc_pack_details(...)` call (line 369) — the two pieces of information (the reliable `"Dlc"` tag and the heuristic HTML-structure extraction) are computed side by side but never cross-checked against each other.

**Where "Dlc" is/isn't currently used elsewhere:**
- `is_game = item_type == "game" and "Coupon" not in tags` (line 366) — only excludes coupons, never checks for `"Dlc"`.
- Grepping the whole `src/game_collections` tree, `tags`/`"Dlc"` is otherwise **completely unused** — no gating in `parser.py`'s `_bundle_item`, no gating in `resolver.py`'s `resolve_item`, and nothing downstream (CLI/crawler) branches on it either. `models.py`'s own docstring for `base_game_url`/`bundled_dlc_names` (line 81) claims the fields are "Populated for 'DLC pack' items (see `cta_badge`/`tags == 'Dlc'`)" — but that's aspirational/stale; the actual code never enforces it.
- `parse_choice_page()` (Humble Choice month pages) never reads `cta_badge` at all — it derives `tags` only from a `"coupon"` substring match on the machine name/title (line 601), so Choice items have no DLC signal parsed today even though `cta_badge`/`badge` might exist in that page's data too (worth checking if Choice ever bundles DLC packs — untested in this repo either way).

## Implication for the bug/fix

This confirms there is a ready-made, reliable, already-parsed signal (`"Dlc" in item.tags`, sourced from `cta_badge.badge == "dlc"`) that isn't being used to gate either:
1. `_parse_dlc_pack_details()`'s invocation in `_bundle_item` (`parser.py:369`), or
2. `resolve_item`'s branch condition `if item.bundled_dlc_names:` (`resolver.py:326`).

Adding a check like `if "Dlc" in tags:` before running/trusting the HTML-structure heuristic (in either or both places) would directly fix the false-positive class of bug (a normal game like "Whisper Mountain Outbreak" whose description happens to contain a Steam link + an early bullet list) without needing to change the structural extraction heuristic itself, since Humble's own badge is the ground truth for "this item actually is a DLC pack."