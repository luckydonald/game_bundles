---
name: user-isthereanydeal-domain-expertise
description: User does hands-on live verification of ITAD/storefront behavior himself and expects the same rigor
metadata: 
  node_type: memory
  type: user
  originSessionId: 5277c033-a084-4c25-b5b6-197c6dd0a893
---

The user actively does his own live research against isthereanydeal.com and storefront APIs/pages (checking actual JSON shapes, shop lists, redirect behavior) rather than relying on assumptions, and feeds concrete findings back mid-task (e.g. pointed out the `/api/game/info/` deals endpoint, the `deals[].shop`/`url` shape, that ITAD `url` fields redirect and need `url_resolved`, the real MLP Pinball cross-platform duplicate case, and that he'd reformatted `config/isthereanydeal-shops.yml` himself to schema v2 before I even knew).

**How to apply:** Treat his in-message technical claims about these external services as reliable leads worth verifying and building on directly, not as things to double-check skeptically from scratch — but still verify the exact shape myself (see [[feedback_verify_dont_guess_external_shapes]]) since he's pointing at *what to check*, not necessarily handing over exact verified schemas. Expect him to keep iterating scope mid-plan as he digs up more real data (this happened three times in one planning session: Fallout NV → MLP slugs → discovering the Pinball duplicate → the shops.yml storefront-expansion request).
