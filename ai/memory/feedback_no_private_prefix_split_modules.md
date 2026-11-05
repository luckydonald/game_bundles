---
name: feedback-no-private-prefix-split-modules
description: "New code should not use `_`-prefixed \"private\" classes/functions; split concerns into separate modules instead"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: c7490781-1b64-4b82-a230-ce3ff4adeea8
---

Don't use `_` prefixes to mark classes/functions as "private" in new code. Instead, when something is a distinct concern, split it out into its own module.

**Why:** User explicitly rejected a plan that added new underscore-prefixed helper classes (e.g. `_FilterFieldBehavior`, `_FilterInput`) into an existing file (`apply/tui.py`), even though that file's *existing* code already uses heavy underscore-prefixing (`_Filters`, `_NodeData`, `_BundleTree`, etc.). The correction was about new code, not a request to rewrite existing conventions.

**How to apply:** When adding new widget/helper classes or functions that would otherwise be tucked in as `_Something` inside an existing module, give them plain public names and put them in a new sibling module instead (e.g. `apply/filter_widgets.py` alongside `apply/tui.py`). Don't retroactively rename pre-existing underscore-prefixed code unless asked — this is about how *new* code should be structured, not a full-file style pass.
