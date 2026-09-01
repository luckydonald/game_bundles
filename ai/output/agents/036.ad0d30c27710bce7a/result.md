I have everything needed. Here is the full report.

## 1. `complete_command` — `src/game_collections/cli.py:350-432`

```python
@app.command("complete")
def complete_command(
    file: Annotated[Path, typer.Argument(help="Draft YAML game list to complete in place.")],
    providers: Annotated[
        list[str] | None,
        typer.Option(
            "--provider",
            "--store",
            "-p",
            help="Storefront(s) to search; repeat or comma-separate. Defaults to steam.",
        ),
    ] = None,
    mode: Annotated[
        str,
        typer.Option(
            "--mode",
            help="Selection mode: blank, missing, unresolved, or refetch_all.",
        ),
    ] = "blank",
    archive_root: Annotated[Path, typer.Option("--archive-root")] = Path("archives"),
    game_alias_config_path: Annotated[Path, typer.Option("--game-alias-config")] = Path(
        "config/isthereanydeal-game-aliases.yml"
    ),
) -> None:
    """Complete storefront IDs in a draft YAML game list."""
```

Body (lines 375-432): opens `HumbleHttpClient()`; `itad_client: ItadHttpClient | None = None`; in a `try/finally`:
- `selected = selected_providers(providers, default="steam")`
- `selected_mode = completion_mode(mode)`
- builds a `StorefrontResolver(client.fetch, lambda _title, _provider, _candidates: None)` — the "choose" callback is a **no-op that always returns `None`**, i.e. `complete` today is effectively non-interactive/best-effort: ambiguous candidates and "Multiple…" splits are simply skipped (never chosen), not prompted. (There is no `--non-interactive` flag; the CLI command has no interactive prompting at all currently — `choose_store_candidate` imported from `sources.prompting` is passed to `complete_game_list` as the `choose` callable in the signature, but the lambda literal above is what's actually wired to `StorefrontResolver`; the interactive `choose_store_candidate` is passed separately as the `choose` param to `complete_game_list` itself — see below.)
- if `"isthereanydeal" in selected`: opens `ItadHttpClient()`, loads `load_game_alias_config(game_alias_config_path)`, defines `resolve_one`/`itad_resolve` closures that call `resolve_game(...)` and write an ITAD per-game archive via `write_itad_game_archive(resolution, archive_root)`.
- Reads and `yaml.safe_load`s **exactly one file** (`file.read_text(...)`) — line 403.
- Calls:
```python
completed, unresolved = complete_game_list(
    raw, selected, resolver, choose_store_candidate, selected_mode,
    itad_resolve=itad_resolve,
)
```
  Note: `choose_store_candidate` (imported from `game_collections.sources.prompting`) is the actual interactive chooser passed into `complete_game_list` — it's what prompts on ambiguous matches. There's no flag to disable it (no `--non-interactive`).
- Writes the completed dict back with `yaml.safe_dump(..., sort_keys=False, allow_unicode=True)` to the **same file** (in place).
- `typer.echo(f"Updated {file}.")`; echoes `unresolved: {title}` to stderr for each unresolved name; if any unresolved, `raise typer.Exit(1)`.
- Catches `(OSError, ValueError, RuntimeError, yaml.YAMLError)` → echoes to stderr, `raise typer.Exit(1)`.
- `finally`: closes `client` and `itad_client` if opened.

**Key constraint for an `--all` flag**: this command is hard-wired to a single `file: Path` positional argument (line 352) and does everything (yaml load, complete_game_list, yaml dump, echo, exit-code) inline for that one file — no loop, no per-file try/except, no progress callback. There is currently **no flag at all** resembling `--all`, `--non-interactive`, `--refresh`, or `--no-cache` in this command.

## 2. `src/game_collections/search.py`

- `Provider = StoreName | Literal["isthereanydeal"]`, `CompletionMode = Literal["blank","missing","unresolved","refetch_all"]`, `COMPLETION_MODES` tuple (lines 27-37).
- `selected_providers(values, *, default)` (40-61): accepts `str | list[str] | None`, splits on commas, expands `"all"` to `ALLOWED_STORES` (storefronts only — `isthereanydeal` is never included by `"all"`), validates against `ALLOWED_STORES + ("isthereanydeal",)`, dedupes preserving order, raises `ValueError` on empty/unknown.
- `completion_mode(value)` (64-71): raises `ValueError` if not one of the 4 modes; otherwise casts/returns it.
- `_should_search(ids, provider, mode)` (84-97) — the actual mode semantics:
  - `blank`: true only if **no** id in the list is a "proper" (non-`unresolved:`) id — i.e. blank applies per-game, not per-provider (checked once via `blank_eligible`, not through this helper for blank — see below).
  - `refetch_all`: always `True`.
  - `missing`: `True` iff provider has neither an existing `{provider}:` id nor an existing `unresolved:store:{provider}:` failure marker for this game.
  - `unresolved` (the `else` branch, i.e. not blank/refetch_all/missing): `True` iff provider has no existing `{provider}:` id (this **includes** retrying `unresolved:store:{provider}:*` failures, since only a successful `{provider}:` id blocks it).
- `resolve_title(title, providers, resolver, choose)` (100-139): for each provider, searches candidates, auto-accepts a unique exact-normalized-title match; otherwise calls `choose(title, provider, candidates)` — `None` means skip, `ChosenNames` means the title actually represents multiple sub-titles (each recursively re-resolved across **all** providers from scratch, function returns early with those results instead of one `ResolvedGame`).
- `complete_game_list(raw, providers, resolver, choose, mode="blank", itad_resolve=None)` (142-265): the core routine.
  - Requires `itad_resolve` if `"isthereanydeal"` is selected.
  - `raw` must be a `Mapping`; deep-copies it; requires non-empty `games` list.
  - Per game: validates `name` non-empty str, `ids` is list of strings; parses/compacts each via `QualifiedGameId.parse(value).compact()`.
  - `blank_eligible = not any(_is_proper_id(value) for value in current)` computed **once per game** (not per provider) — this is what implements `blank` mode’s should-search (`should_search = blank_eligible if mode == "blank" else _should_search(...)`).
  - For provider `"isthereanydeal"`: only acts if an `ITAD_UNRESOLVED_PREFIX` marker exists in current ids; calls `resolve_isthereanydeal_markers(current, itad_resolve)`; marks `failed=True` if unresolved markers remain.
  - For store providers: strips old `unresolved:store:{provider}:` markers before searching; in `refetch_all` mode also strips existing `{provider}:*` ids before re-searching. Calls `resolve_title`. If result splits (`len(results) > 1`) → builds a `multiple:` group and appends separate game entries to `games_out`, `continue`s outer loop (skips normal single-game append).
  - If a title resolved successfully this pass, all `unresolved:source:*` markers are stripped (line 253-254) — but note this only fires for the *current* game (not for isthereanydeal-only games unless `resolved_any` explicitly set, which only store search sets — ITAD path doesn't set `resolved_any`).
  - Appends `name` to `unresolved` output list if `searched and failed`.
  - Final: `completed["games"] = games_out`; **re-validates** via `GameList.model_validate(completed)` (line 263) — this means a file with any remaining `unresolved:` ids or blank fields will still validate as a `GameList` (the schema apparently permits `unresolved:*` strings as valid IDs — confirm via `models.py` `QualifiedGameId`), so successful `complete_game_list` calls don't themselves fail even when things remain unresolved; only the CLI's own exit-code check (`if unresolved: raise typer.Exit(1)`) signals incompleteness.
  - Returns `(completed_dict, unresolved_names_list)`.

**Error propagation**: `complete_game_list` raises on structural problems (bad YAML shape, non-string ids, missing name) — these are hard stops, not per-game skips. Per-game *resolution* failures (no match found) are **not** exceptions — they're recorded as `unresolved:store:...` markers and returned in the `unresolved` list; processing continues for all other games in the same file. So within one file, failures don't abort the run; across multiple files (if you build a loop yourself) you'd need to decide whether one file's `ValueError`/`OSError`/`yaml.YAMLError` aborts the whole `--all` run or is caught per-file and reported, matching the `migrate-tiers` pattern below.

## 3. `src/game_collections/lists.py` — discovery functions

- `derive_list_id(path, lists_root)` (33-49): requires `.yml` suffix, rejects symlinks, requires path be inside `lists_root`, returns `vendor/name` id via `validate_list_id(relative.with_suffix("").as_posix())`.
- `load_game_list(path, lists_root)` (52-69): loads+validates one file into `LoadedGameList(id, path, data: GameList)` via `GameList.model_validate` — **raises `ListLoadError` on any invalid list** (including presumably drafts with blank/`unresolved:` ids, if disallowed by schema — needs checking, see below).
- `discover_game_lists(lists_root, on_progress=None)` (72-101): `sorted(lists_root.rglob("*.yml"))`, loads each via `load_game_list` (raising `ListLoadError`/`OSError`/`yaml.YAMLError` immediately on the first bad file — **no continue-on-error**, no partial results returned), then checks for case-insensitive id collisions across the whole set, and returns `list[LoadedGameList]`. Supports an `on_progress(index, total, path)` callback for progress reporting (used via `_echo_list_progress` in cli.py:135-137, wired into `validate`... actually `validate_command` doesn't pass `on_progress`; only `_discover_selected_game_lists` (cli.py:119-132) accepts and forwards `on_progress`, but even that helper is never called with `_echo_list_progress` anywhere I found in the grep — check further if needed).

**Critical finding for the "--all draft/incomplete" requirement**: `lists/README.md:35` explicitly states drafts must live **outside the validated `lists/` tree**:
> "To create a list from names first, omit `ids` (or use an empty list) in a draft outside the validated `lists/` tree, then complete it in place"

This means there is **no existing discovery function that enumerates draft/incomplete files** — `discover_game_lists` walks `lists_root` (default `./lists`) and calls `GameList.model_validate` on every file, which is the validated/committed tree, not a draft staging area. Draft files by convention live elsewhere (e.g. repo root or an ad hoc path) precisely because they may not pass full `GameList` validation. So implementing `complete --all` cannot simply reuse `discover_game_lists`/`_discover_selected_game_lists` semantics unless:
  - (a) the intended behavior changes to also tolerate/complete files under `lists/` that still contain blank/`unresolved:` ids (need to check whether `GameList`/`QualifiedGameId` schema actually rejects blank or `unresolved:` ids — if it accepts them, `discover_game_lists` could double as the enumerator and "still needs complete" could be detected by scanning `LoadedGameList.data.games[*].ids` for blank/`unresolved:` prefixed values), or
  - (b) `--all` is meant to take a **root directory** of loose/unvalidated draft files (glob `*.yml` under it, e.g. via `Path.rglob("*.yml")` directly, bypassing `GameList.model_validate`) rather than reusing `discover_game_lists`.

I checked `models.py` briefly — `QualifiedGameId` (line 30) and `GameList` (line 129) are defined there; I did not find any explicit rejection pattern for `unresolved:`-prefixed ids in the grep of "unresolved" in models.py (no hits), meaning the schema likely allows `unresolved:*` as a syntactically valid qualified id (validated generically as `provider:id` shaped strings), so option (a) above is plausible — draft files with `unresolved:` markers or files already under `lists/` could pass `GameList.model_validate` and thus `discover_game_lists`. But files with a fully **empty** `ids: []` — need to double check `QualifiedGameId`/`GameList` won't choke on an empty list; recommend reading `src/game_collections/models.py` lines ~30-178 directly before finalizing the plan, since I did not fully read that file (only grepped it).

## 4. `validate` and `migrate-tiers` patterns (cli.py)

- `validate_command` (140-152): single call to `discover_game_lists(_lists_root(path))` wrapped in `try/except (OSError, ValueError, ListLoadError)` → echo error to stderr + `typer.Exit(1)`. **Fails fast on the very first bad file** (since `discover_game_lists` itself has no continue-on-error). Success path just echoes a count.
- `migrate_tiers_command` (172-213): the actual "loop over all lists, report per-item, continue-ish" pattern to reuse:
  1. Compute `lists_root` and `repository_root`.
  2. `plan_migration(lists_root)` — builds all `steps` up front (single call, can raise).
  3. `for step in steps:` — inside the loop, a nested `try/except (OSError, ValueError, ListLoadError, TierMigrationError)` that **still aborts the whole command on the first error** (`typer.echo(...); raise typer.Exit(1)` inside the loop body — not a `continue`). So despite being "per-item", it does **not** actually continue past failures; it's fail-fast per item just like validate, but with a bit more up-front batching. This is the closest existing pattern to a multi-file operation but it is *not* an example of "continue on error and report a summary at the end" — there is no such pattern currently in this codebase for list-processing commands.
  4. Per-item: computes `relative_old`/`relative_new`, echoes `"migrated: {old} -> {new} ({tier_note})"` or `"would migrate: ..."` (dry-run by default, `--apply` to write) — this is the progress-reporting style to imitate (`typer.echo` per item, no counters like "x/y" here).
  5. Final summary line: `f"Migrated {changed} list(s)."` or dry-run variant.

- `_echo_list_progress(index, total, path)` (135-137) is the one existing "x/y" progress-style helper — `typer.echo(f"Loading list {index}/{total}: {path.name}")` — designed to be passed as `discover_game_lists`'s `on_progress` callback, but note **no command currently wires it in** (I didn't find a call site passing `_echo_list_progress` into `discover_game_lists` or `_discover_selected_game_lists` in the visible cli.py; worth grepping again before relying on it as "existing, in-use" pattern — it may be dead/unused scaffolding, or used only in the `apply`/`sync` commands further down which I did not fully read).

Other multi-item progress style elsewhere (scrape commands, e.g. `scrape humblebundle`/`greenmangaming`/`isthereanydeal` around lines 511-801): pattern is `typer.echo(f"Archived {offer.archive.name}: {len(paths)} file(s)")` per item inside a loop, `typer.echo(f"unresolved: {x}", err=True)` / `typer.echo(f"error: {error}", err=True)` per failed item (these DO continue past per-item errors, unlike validate/migrate-tiers), and a final summary `typer.echo(f"Wrote {written_count} file(s) for {len(report.offers)} offer(s).")`. This scrape-command style (continue on per-item error, collect an unresolved/error list, echo per-item, single summary line at the end) is the better model to imitate for a `complete --all` that shouldn't abort on the first unresolved file — it more closely matches how `complete_game_list` itself already tolerates unresolved games within one file.

## 5. Tests

- `tests/test_cli.py`: no existing tests reference the `complete` command at all (confirmed via grep for `"complete"` — zero hits). Uses `CliRunner()` from `typer.testing`, imports `app` from `game_collections.cli`, patterns like `CliRunner().invoke(app, ["scrape", "humblebundle", "--git", "--non-interactive"])`. Any new `complete --all` tests would need to be added fresh, following this `CliRunner().invoke(app, ["complete", ...])` idiom, likely with `tmp_path` fixtures for draft files and monkeypatching `HumbleHttpClient`/`StorefrontResolver`/network calls.
- `tests/test_search.py`: this is where `complete_game_list`, `selected_providers`, `completion_mode`, `_should_search`/mode behavior are actually unit-tested today (not at the CLI layer). Any new mode/discovery logic belongs there for the search.py pieces, and in test_cli.py only for the new `--all` orchestration/CLI wiring.

## 6. Docs to update for a new `--all` flag

- `README.md`: only generic "complete" mentions found are unrelated prose ("complete file envelopes") — no dedicated `complete` command section found in the root README via grep; the command's user-facing docs live in `lists/README.md`.
- `lists/README.md:29-45`: this is the section to update. Key existing text to amend:
  - Line 35: "omit `ids` ... in a draft **outside the validated `lists/` tree**" — this line is exactly what constrains/foils a naive "reuse discover_game_lists" implementation and should inform whatever `--all` semantics are decided (either changing this convention, or making `--all` take an explicit draft-directory argument rather than defaulting to `./lists`).
  - Lines 37-41: the `game-collections complete ...` examples — add a `--all` example here.
  - Line 43: the mode-semantics paragraph — reuse this exact language for any new help text/docs since it precisely matches `_should_search`'s real behavior.

## Summary of line numbers for the plan file

| Item | File | Lines |
|---|---|---|
| `complete_command` | `src/game_collections/cli.py` | 350-432 |
| `_lists_root` | `src/game_collections/cli.py` | 114-116 |
| `_discover_selected_game_lists` | `src/game_collections/cli.py` | 119-132 |
| `_echo_list_progress` (possibly unused) | `src/game_collections/cli.py` | 135-137 |
| `validate_command` | `src/game_collections/cli.py` | 140-152 |
| `migrate_tiers_command` | `src/game_collections/cli.py` | 172-213 |
| `selected_providers` | `src/game_collections/search.py` | 40-61 |
| `completion_mode` | `src/game_collections/search.py` | 64-71 |
| `_should_search` (mode semantics) | `src/game_collections/search.py` | 84-97 |
| `resolve_title` | `src/game_collections/search.py` | 100-139 |
| `complete_game_list` | `src/game_collections/search.py` | 142-265 |
| `derive_list_id` | `src/game_collections/lists.py` | 33-49 |
| `load_game_list` | `src/game_collections/lists.py` | 52-69 |
| `discover_game_lists` | `src/game_collections/lists.py` | 72-101 |
| draft-outside-lists-tree convention | `lists/README.md` | 35 |
| `complete` CLI examples | `lists/README.md` | 37-41 |
| mode semantics prose | `lists/README.md` | 43 |

Two open items I'd flag for the plan before implementing: (1) I did not fully read `src/game_collections/models.py` (only grepped it) — confirm whether `GameList`/`QualifiedGameId` actually accept blank/`unresolved:`-prefixed ids, since that determines whether `discover_game_lists` can double as the "find incomplete lists" enumerator or whether `--all` needs its own raw-glob/raw-yaml-load path independent of `GameList` validation; (2) no existing CLI tests for `complete` exist, so test coverage for `--all` will be net-new rather than an extension of an existing suite.