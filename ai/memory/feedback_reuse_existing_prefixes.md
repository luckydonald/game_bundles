---
name: feedback-reuse-existing-prefixes
description: "When an external config's own naming differs from an established internal identifier, default to reusing the internal one"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 5277c033-a084-4c25-b5b6-197c6dd0a893
---

When a third-party config/API uses its own naming for something that already has an established identifier/prefix inside the codebase, default to reusing the existing internal name rather than adopting the external name verbatim — confirm with the user if genuinely ambiguous, but the reuse option is the safe default.

**Why:** `config/isthereanydeal-shops.yml` labels Epic Game Store and Humble Store with slugs `epicgames`/`humble-store`, but the rest of the repo already uses `epic`/`humble` as the `StoreName`/qualified-id prefix for the exact same real stores (used in `lists/` ids, launcher-sync code, etc.). Introducing `epicgames:`/`humble-store:` as new, separate provider prefixes would have split identity for the same store across two different id namespaces. Asked the user, confirmed: reuse `epic:`/`humble:`.

**How to apply:** Before wiring a new external data source's own naming/slugs directly into the codebase as qualified-id prefixes or enum values, check whether an equivalent internal name already exists for the same real-world entity. If so, map to it rather than introducing a parallel name — this matters most for identifiers that end up in persisted data (`ids:` lists in `lists/*.yml`), where a naming split would be a real inconsistency, not just cosmetic.
