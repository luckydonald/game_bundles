---
name: project-isthereanydeal-source-expansion
description: "Status of the isthereanydeal source's ongoing expansion (per-game solver, storefront generalization, shop config v2)"
metadata: 
  node_type: memory
  type: project
  originSessionId: 5277c033-a084-4c25-b5b6-197c6dd0a893
---

As of 2026-07-13, the isthereanydeal source (`src/game_collections/sources/isthereanydeal/`) gained a per-game detail-page solver (`resolver.py`: `resolve_game`, `resolve_game_with_aliases`, `resolve_isthereanydeal_markers`), reachable via `game-collections complete FILE --provider isthereanydeal --mode unresolved`, plus a generalized storefront-id matcher in `sources/storefronts.py` (`match_store`, `qualified_ids_from_urls`, `EXTRA_STORE_PARSERS`) shared between the bundle parser and the new solver.

**Why:** `config/isthereanydeal-shops.yml` had ~4,548 list files with unsolved `unresolved:source:isthereanydeal:<bundle-id>:<slug>` markers from bundle detail pages with no recognized storefront link. The new solver fetches each game's own ITAD detail page + cross-store deals API to solve these later, on demand (not backfilled automatically — forward-only per the user's explicit choice: re-run `complete` per file, or delete-and-recrawl).

**Known follow-up work still open** (per the plan doc, not yet done): most of `config/isthereanydeal-shops.yml`'s shop slugs (Amazon/`asin`, Fanatical, itch.io, Blizzard, Oculus, EA, Razer, WinGameStore, MacGameStore, App Store, Google Play, ~15 more) have no verified URL-parsing rule yet in `storefronts.py` — only Steam/GOG/Epic/Ubisoft/Humble (existing) plus Microsoft Store and 2game (added this session, both live-verified) are wired up. Adding more requires fetching a real ITAD deal for a game sold there and inspecting the resolved redirect (see [[feedback_verify_dont_guess_external_shapes]]) — the archived `deals_resolved` output in `archives/isthereanydeal/game/<slug>/source.json` makes this self-bootstrapping.

Also open: Blizzard's shop cannot be resolved at all anonymously (its redirect lands on an auth-walled OAuth login page with no product id) — this is a permanent limitation, not a TODO, unless a future authenticated-session approach is built.

See `config/isthereanydeal-game-aliases.yml` for the reviewed cross-platform-duplicate-game config (currently only the MLP Pinball Steam/Epic pair) — add more entries here as other ITAD duplicate-listing cases are found.
