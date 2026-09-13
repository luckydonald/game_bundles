---
name: feedback-live-validation-runs-fix-bugs-found
description: "when a plan includes an explicit live-run validation step, treat real bugs it surfaces as in-scope to fix immediately, not just report back"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 220d4473-eea2-4366-b9bb-ac6d404ff8dc
  modified: 2026-08-18T00:34:27.526Z
---

A plan item was "run both scrapers against real data and compare/diff the output, fixing anything the diff surfaces as a follow-up commit within this same task rather than opening a new todo item." When the live run actually surfaced a real correctness bug (a fuzzy-matching false positive that corrupted a committed list into invalid duplicate-name YAML), the right move — already spelled out in the approved plan, and confirmed correct by proceeding without pushback — was to: reproduce it in isolation, root-cause it precisely (not just patch symptoms), fix the underlying logic, add a regression test, then repair the actual corrupted data in the repo (including cleaning up an unrelated stray duplicate the same live run produced from a flaky upstream date field), all as one more commit in the same session.

**Why:** the plan explicitly authorized this ("write files ... let --git make its own commits ... fix anything the diff surfaces ... rather than opening a new todo item"), and the value of a live validation step is exactly to catch things unit tests miss — deferring the fix to "report and let the user handle it" would waste the point of running it live.

**How to apply:** when a plan or the user explicitly schedules a live/real-data validation pass, budget for it to find something, and treat fixing what it finds (with a regression test, and repairing any data it already corrupted) as part of completing that plan item — don't stop at reporting the finding unless the fix is clearly out of scope or high-risk enough to need a separate confirmation.
