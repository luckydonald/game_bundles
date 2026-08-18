---
name: feedback-plan-prose-formatting
description: "User's required line-break style for plan-mode markdown files (and by extension, other prose deliverables)"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 220d4473-eea2-4366-b9bb-ac6d404ff8dc
  modified: 2026-08-18T00:33:57.510Z
---

Rewrite plan-file (and likely other markdown deliverable) prose so line breaks only occur at sentence boundaries, never mid-sentence after a random word. Multiple sentences may share one line — breaking after every sentence is not mandatory. If a single sentence would make a line very long, it's acceptable (but not preferred) to break after a comma/dash instead. Target roughly a 140-character soft limit; a bit more or less doesn't matter.

**Why:** explicitly corrected on a plan file that used normal word-wrapped paragraphs (breaking mid-sentence at ~80-100 chars, typical prose-wrap style). The user rejected the plan via `ExitPlanMode` specifically to give this formatting instruction before approving.

**How to apply:** when writing or editing any `.md` file for this user — plan files, and probably README/doc updates too — write each paragraph as one long line (or a few sentence-boundary-broken lines) rather than traditional soft-wrapped prose. Don't rely on an editor's automatic wrapping; construct the text deliberately.
