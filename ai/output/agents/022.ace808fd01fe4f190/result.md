Now I have the full picture. Report below.

## Findings

**1. `merge_game_list()` — `/home/user/git/luckydonald/game_collections/src/game_collections/sources/common.py:72-91`**

```python
def merge_game_list(existing: GameList | None, fresh: GameList) -> GameList:
    if existing is None:
        return fresh
    existing_by_name = {game.name.casefold(): game for game in existing.games}
    fresh_names = {game.name.casefold() for game in fresh.games}
    merged_games = [existing_by_name.get(game.name.casefold(), game) for game in fresh.games]
    merged_games.extend(game for game in existing.games if game.name.casefold() not in fresh_names)
    return fresh.model_copy(update={"games": merged_games})
```
This is confirmed additive-only: it explicitly `extend`s in every existing game whose name isn't in the fresh crawl (line 89), so nothing is ever dropped. Docstring says "never removes an existing game absent from the fresh crawl" — that is exactly what the requested policy needs to override, but only for the humblebundle path.

**2. `write_humble_offer()` / `_write_merged_game_list()`** — `humblebundle/crawler.py:249-260` (helper) and `263-368` (two call sites at lines 314 and 364, for Choice-picks and classic-tier lists respectively). `_write_merged_game_list()` loads existing list via `load_game_list()`, calls `merge_game_list(existing, fresh)`, then `atomic_write`s. Both call sites are the only writers into `lists/humblebundle/...`.

**3. ITAD's skip logic** — `isthereanydeal/crawler.py:422-441`. `write_itad_offer()` checks `_existing_choice_match()` (376-400, humblebundle-only, matches Choice `YYYY-MM.yml` naming) and `_existing_list_match()` (402-419, substring match against `lists_root / provider_slug`) before ever building a list; if either matches, it logs "Skipped … already covered by …" and returns without writing (436-441). So confirmed: ITAD **never overwrites** `lists/humblebundle/...` when a dedicated-scraper file already exists there. However, note `provider_slug` (`isthereanydeal/models.py:112`) is resolved per-bundle and can itself be `"humblebundle"` (`isthereanydeal/crawler.py:242,385`); if a Humble-sourced bundle on ITAD is *not yet* covered by the dedicated scraper, ITAD *would* write into `lists/humblebundle/bundle/...` itself (line 445) — i.e., `lists/humblebundle/` isn't exclusively written by `humblebundle/crawler.py`, just never overwritten once populated. Any "humble authoritative, remove absent" policy should be scoped by call site (only `write_humble_offer`'s merge), not by directory prefix alone.

**4. `Game` model** — `models.py:63-87`. Fields: `name`, `ids: list[str]`, `group: GameGroup | None`. **No manual/provenance flag exists.** There is no `source`, `manual`, `added_by`, or timestamp field on `Game` or `GameList` to distinguish a hand-added entry from a scraped one. The comment "manual `ids:`/`group` edits" (commit `51183026`, `common.py:75`) refers to editing fields *on an existing scraped game* (fixing its `ids:`/`group`), not to a wholly separate manually-inserted `Game` entry — and even that distinction (edited-scraped-game vs. fresh-scraped-game) isn't tagged anywhere; `merge_game_list` just treats "any name already present" as "keep as-is," whether the edit was manual or not.

**5. Manual-edit plausibility** — CLAUDE.md:61 confirms the project's general philosophy explicitly protects "manually added games in retained collections" elsewhere (Steam local collections), and commit `51183026`'s own message is explicit: the merge exists specifically because a re-crawl was "silently los[ing]" "manual `ids:`/`group` fixes" — i.e., humans are known to hand-edit `lists/humblebundle/*.yml` files. No README/todo text restricts this to field-edits-only vs. whole-new-entries; a human manually adding an extra `Game` entry to a humblebundle list (e.g., a bonus/soundtrack item, or a game omitted by the resolver) is plausible and, since there's no flag, indistinguishable from a scraped one.

## Conclusion

Yes — direct conflict. `merge_game_list` is called only from `write_humble_offer`/`_write_merged_game_list` (humblebundle), so scoping "remove absent games" to just that call site is structurally easy (it wouldn't touch ITAD or other sources' merges, since none of them currently even call `merge_game_list`). But there is **no field to distinguish manually-added/edited games from scraped ones** in `Game`/`GameList`. Implementing "not on Humble anymore → remove" as-is would risk deleting legitimate manual additions with no way to protect them, unless a new marker (e.g., `manual: true` or a provenance tag) is introduced first, or removal is limited to games that still carry only Humble-origin `ids:` and no `group`/manual marker — none of which exists today.