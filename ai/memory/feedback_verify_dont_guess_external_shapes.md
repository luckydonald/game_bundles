---
name: feedback-verify-dont-guess-external-shapes
description: Verify third-party URL/API shapes live before writing parsers; never ship a generic fallback in place of a verified rule
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 5277c033-a084-4c25-b5b6-197c6dd0a893
---

Never write a parser for an external site/API's URL or response shape from memory or guesswork. Fetch it live (curl/WebFetch) first, confirm the actual shape, then implement exactly that. If a shape isn't verified yet, skip/log it rather than guessing a "probably close enough" generic fallback.

**Why:** During the isthereanydeal per-game solver work, I proposed a generic fallback (last URL path segment) for storefronts with no confirmed URL shape (Amazon, Fanatical, itch.io, etc.). The user rejected this explicitly: "URL parsers needs to be added still" — meaning add real, verified parsers incrementally, don't paper over unknowns with a guess. I then live-fetched real ITAD deal redirects for several stores (Steam, GOG, Epic, Humble, Microsoft, 2game, Blizzard) and found real bugs this way (Epic actually redirects to `www.epicgames.com`, not just `store.epicgames.com` as the existing code assumed — a genuine latent bug caught only by checking live data). Blizzard turned out to be unresolvable at all anonymously (auth-walled redirect), which a guessed fallback would have silently gotten wrong (storing a meaningless login URL as if it were a product id).

**How to apply:** Whenever building a URL/response parser for a specific external service (not just isthereanydeal — any scraper/source in this repo, or any repo), fetch a few real live examples first via curl or WebFetch before writing the regex/host-check logic. Treat an unverified case as "skip and log," never as "guess a plausible pattern." This matches the project's own stated philosophy in CLAUDE.md ("treat unknown external fields and format changes as errors"), extended to unverified URL shapes too.
