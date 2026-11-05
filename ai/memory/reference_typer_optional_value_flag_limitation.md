---
name: reference-typer-optional-value-flag-limitation
description: "Typer 0.26 (this repo's version) does not support Click's is_flag+flag_value combo for an \"optional-value\" CLI flag like --git=auto/--git=manual/bare --git"
metadata: 
  node_type: memory
  type: reference
  originSessionId: 220d4473-eea2-4366-b9bb-ac6d404ff8dc
  modified: 2026-08-18T00:34:14.633Z
---

Confirmed via a runtime test (both through `typer.Option(..., is_flag=False, flag_value="manual")` and by trying to reach the vendored click layer directly) that Typer 0.26 does not wire Click's `is_flag`/`flag_value` option combo through to actual parsing, even though `typer.Option()` exposes both parameters (its own docstring already hedges: "inherited from Click... however not fully functional"). A flag defined that way rejects a bare `--git` with "Option '--git' requires an argument" instead of falling back to the `flag_value`.

Also: this Typer version has no separate `click` package installed at all — it vendors its own core under `typer._click`, which doesn't expose the decorator-based `click.command`/`click.option` API, only `Context`/`Command`/`Parameter`/etc. So there's no easy escape hatch to hand-roll a raw Click option either without much deeper surgery.

**How to apply:** don't attempt `--flag=value` where a bare `--flag` should imply a default value, in this codebase's Typer version. Use two separate options instead (e.g. a boolean `--git` plus a `--git-style manual|auto` choice option) — same expressiveness, fully supported, no custom parsing needed.
