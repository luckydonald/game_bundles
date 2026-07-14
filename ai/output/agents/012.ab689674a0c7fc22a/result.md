Good, that confirms `load_bundle_metadata` is cheap (in-memory, no I/O). I have all needed info now.

## Report

**List-loading loop (the actual slow work):**
`src/game_collections/lists.py:73` — inside `discover_game_lists()`:
```python
loaded = [load_game_list(path, lists_root) for path in sorted(lists_root.rglob("*.yml"))]
```
This list comprehension iterates every `.yml` file under `lists_root` and calls `load_game_list(path, lists_root)` (`lists.py:51`) per file, which does `path.read_text()` + `yaml.safe_load()` + Pydantic `GameList.model_validate(raw)`. **No progress reporting, logging, or even a plain `for` loop exists here** — it's a bare comprehension, so there's no natural per-iteration hook point without refactoring it into a loop first.

**sync vs apply loading path:**
- `sync_command` (`cli.py:889`) calls `_discover_selected_game_lists(_lists_root(lists_root), selection_config)` → `cli.py:106` → calls `discover_game_lists(lists_root)` (same full-scan loop) then filters by `excluded` set (`cli.py:110`).
- `apply_command` (`cli.py:949`) calls `discover_game_lists(_lists_root(lists_root))` directly (no selection filter yet — filtering happens after the TUI, at `cli.py:963`), then passes result to `load_bundle_metadata(all_game_lists)` (`apply/metadata.py:47`) for the picker.
- Both commands hit the identical `discover_game_lists` full-scan; `apply` additionally runs `load_bundle_metadata`, but that loop (`metadata.py:49`) is pure in-memory (no I/O), so it's not a real slowdown — the shared bottleneck is `lists.py:73`.

**TUI structure (`src/game_collections/apply/tui.py`):**
- Single Textual `App` subclass: `ApplyPickerApp(App[ApplySelection | None])` at line 57 — no additional `Screen` subclasses, no `@work` workers, no async work at all.
- `compose()` (line 75) builds `Header`, filter `Horizontal` (`Select`/`Input`), a `VerticalScroll(id="rows")` with one `Checkbox` per bundle (line 89-95), an actions `Horizontal`, and `Footer`.
- `on_mount()` (line 125) just calls `_apply_filters()`; no loading happens inside the app — `bundles` are pre-loaded before `ApplyPickerApp(bundles, ...)` is constructed (`cli.py:950-953`), so a `ProgressBar` for list-loading would need to live in `cli.py` before/around the `discover_game_lists` call, not inside `tui.py`'s `compose`/`on_mount` (unless the loading itself is moved into the app, e.g. via a worker in `on_mount`).