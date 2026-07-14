Findings:

**Progress print statements** (not in cli.py itself — in the crawler/resolver modules cli.py invokes with `log=typer.echo`):

- `src/game_collections/sources/humblebundle/crawler.py:181`
```python
log(f"Offer {index}/{total}: {url}")
```
- `src/game_collections/sources/greenmangaming/crawler.py:143`
```python
log(f"  Game {index}/{total}: {item.title}")
```
- `src/game_collections/sources/humblebundle/resolver.py:268`
```python
log(f"  Game {index}/{total}: {item.title}")
```

In `cli.py`, the `log` param is wired at lines 464, 529, 630, 689, 704: `log=typer.echo,`.

**No rich console / shared print helper**: cli.py only imports `typer` (line 12) and `yaml` (13); all output uses plain `typer.echo`, no `rich`, no custom console wrapper.

**Top-of-file imports** (typer/rich related): only line 12 `import typer` — no `rich` import anywhere in cli.py.

Full `sync_command` (lines 858-915) and `apply_command` (lines 919-1002) shown above via the Read tool output — both follow the identical pattern: build a Steam adapter, plan, `_print_plan`, optional stage/apply, all output via `typer.echo`, errors caught and re-raised as `typer.Exit`.