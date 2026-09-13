---
name: feedback-real-examples-not-placeholders
description: "Use confirmed-real example data (slugs, IDs, URLs) in docs/tests/fixtures, not invented-looking placeholders"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 5277c033-a084-4c25-b5b6-197c6dd0a893
---

When a plan, doc, code comment, or test fixture needs a worked example (a game slug, product id, sample URL, etc.), use an example that is actually real and verified to exist/behave as described — not a plausible-sounding invented placeholder.

**Why:** I first used `no-mans-sky`/`wildstar` as example ITAD slugs in a plan doc. The user redirected me to use Fallout New Vegas or MLP games instead ("use fallout NV or MLP games for examples if they ever end up in documentations"). When I then picked Fallout NV slugs on my own without checking them, the user corrected again: "Use real placeholder, but of those games" — meaning specific MLP slugs he'd already identified via ITAD (`my-little-pony-a-zephyr-heights-mystery`, `my-little-pony-a-maretime-bay-adventure`, and the `pinball-fx-my-little-pony-pinball`/`my-little-pony-pinball` pair) which he'd confirmed himself. This wasn't just a style preference — the MLP pinball pair turned out to expose a genuine cross-platform duplicate-identity edge case (same real DLC, two separate ITAD entries, one per store) worth handling in the actual implementation, not just useful as a docs example.

**How to apply:** Before writing any example into a plan/doc/test, either use data the user has already given/confirmed, or verify it yourself (fetch the real page/API) rather than inventing something that merely looks plausible. This project in particular (`game_collections`) deals with real external services (ITAD, Steam, GOG, etc.) where "looks real" and "is real" diverge easily, and real examples sometimes surface real edge cases invented ones never would. See [[feedback_verify_dont_guess_external_shapes]].
