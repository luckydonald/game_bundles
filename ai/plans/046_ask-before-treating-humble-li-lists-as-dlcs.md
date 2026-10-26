# Ask before treating Humble `<li>` lists as DLCs

## Context

`scrape humblebundle` turns the first `<ul>` of every `dlc`-badged item into separate DLC games (`bundled_dlc_names`, split in `resolver.resolve_item`).
This was added in `cfe06cb4b` / `cc35d006a` for real DLC packs such as Dagon (`dagon_byhplovecraftdlcpack`) and Our Life, whose `<ul>` is a bare list of full Steam titles plus a free base-game Steam link.
The badge is the only gate, so explainer lists get split too.
Example: `dyinglight2stayhuman_breckenbundle` has `<li>Brecken Outfit — lead the way…</li>` bullets, which became three bogus splits that all resolved to `steam:2269820`.
Other affected items are `monstertrain_thelastdivinitydlc`, `warhammer_*collectorseditionupgrade`, `agameofthrones_*` and `gloomhaven-soloscenarios_*`.

Goal: decide per `<ul>` whether it is a DLC list, ask the user when unsure, default to "no" non-interactively, and auto-answer "yes" when the evidence is strong.

## Decisions (confirmed with the user)

- Every `<ul>` of a `dlc`-badged item is its own candidate list, and each is decided on its own, never merged.
- Lists with obvious prose bullets are auto-"no" without a prompt.
- Non-interactive mode answers "no" (explainer text) whenever the auto-yes heuristic does not pass.

## Changes

1. `humblebundle/parser.py`: replace `_DlcPackDetailsParser`'s first-`<ul>`-only logic with one that collects every `<ul>` as a `list[str]`, and keep `base_game_url`.
   `_parse_dlc_pack_details` returns `(base_game_url, dlc_lists)`.
   `_bundle_item` (still gated on the `dlc` badge, parser.py:473) stores them on the item.
2. `humblebundle/models.py`: add `dlc_lists: list[list[str]]` to `HumbleItem`, replacing `bundled_dlc_names`.
   Bump the metadata version envelope and add a step in `migrations/schema_versions.py` that wraps an old non-empty `bundled_dlc_names` as a single list, so `migrate --type metadata` keeps old archives valid.
   Regenerate `schemas/humblebundle-archive.schema.json` via `game-collections schema`.
3. New module `humblebundle/dlc_lists.py` (no private-prefixed names, per the repo rules):
   - `looks_like_prose(text)`: true for ` — `/` – ` separators or more than about 8 words.
   - `classify_list(items, base_game_url, search) -> Literal["yes", "no", "ask"]`:
     - "no" if any bullet looks like prose.
     - "yes" if there is a Steam base-game link and a Steam search for the first `<li>` returns exactly one candidate whose `normalized_title` equals the `<li>` text (`StorefrontResolver._search_steam`).
       This implements the idea of matching the Humble DLC item against the search result of the first `<li>`: a real DLC pack's `<li>` is a full storefront title, while an explainer line never exact-matches.
     - Otherwise "ask".
   - `DlcListChooser` callable type, so the CLI can inject the prompt or the non-interactive default.
4. `sources/prompting.py`: add `confirm_dlc_list(item_title, items) -> bool`, a yes/no question that shows the item title and the list's bullets ("Are these separate games/DLCs, or just explainer text?"), default "no".
   It follows the existing `choose_store_candidate` style.
5. `humblebundle/resolver.py`:
   - `StorefrontResolver.__init__` gets a `confirm_dlc_list` callable, mirroring `collect_name` / `announce_exact_match`.
   - `resolve_item` (resolver.py:434) first reduces `item.dlc_lists` to confirmed lists (classify, then ask only on "ask").
     Components are the concatenation of the confirmed lists, and the `::N` indexing stays contiguous.
   - Answers are cached in `HumbleResolutionMap` as an optional `dlc_lists: dict[str, bool]` keyed `<machine_name>::list<N>`.
     The field is optional, so existing `config/humblebundle-store-ids.yml` files stay valid under `schema_version` 1.
   - Update the `resolve_archive` split condition (resolver.py:498) to use the confirmed lists instead of `bundled_dlc_names`.
   - `requires` (base game) is only attached to split components.
     A rejected pack stays a single game and gets no `requires` from the list.
6. `cli.py` `scrape_humblebundle_command` (cli.py:828-833): `--non-interactive` passes `lambda *_: False`, the interactive path passes `prompting.confirm_dlc_list`.
   Auto-"yes" still applies in both modes, since it needs no user.
7. Docs: `src/game_collections/sources/README.md` (DLC pack paragraph and the `--non-interactive` note at line 42) and root `README.md` if it mentions DLC splitting.

## Cleanup of already-wrong data

The Dying Light 2 cosmetic bundles already have bogus `::1/::2/::3` keys in `config/humblebundle-store-ids.yml` (lines 359-364 and the chicken bundle).
After the change, re-scraping would reuse them from the cache.
Only a note is needed here: list the affected keys for the user to review, and do not rewrite the config unasked.

## Tests

Existing tests to adapt: `tests/test_humblebundle_parser.py` (lines 154-252), `tests/test_humblebundle_resolver.py` (lines 348-537), `tests/test_prompting.py`.
New cases:
- Dagon fixture HTML gives one list, which classifies as "yes" with a stubbed exact-match search.
- Brecken fixture HTML classifies as "no" without a prompt (prose bullets).
- An ambiguous list asks once per list, caches the answer, and does not ask again on the next run.
- Non-interactive mode makes an ambiguous list "no".
- Our Life's feature `<ul>`s trigger no prompts.
- A migration test for `bundled_dlc_names` becoming `dlc_lists`.
Use the real archived HTML from `archives/humblebundle/bundle/2026-08-21_love-letter-to-lovecraft` and `2026-09-30_dying-light-2-stay-human-complete-dlc-bundle`, not invented samples.

## Verification

- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_humblebundle_parser.py tests/test_humblebundle_resolver.py tests/test_prompting.py tests/test_schema.py -q`, then the full suite.
- `game-collections schema` produces no further drift.
- `game-collections migrate --type metadata --dry-run` shows the new step for the affected archives.
- `game-collections validate` passes.
- Commit with the `commit-with-lplp-style` flow (explicit paths, message via `ai/git/pending-commit.md`).
