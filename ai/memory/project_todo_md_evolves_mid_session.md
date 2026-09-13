---
name: project-todo-md-evolves-mid-session
description: "ai/todo.md in game_collections is a living document the user edits while an agent is mid-implementation, not a static snapshot taken at planning time"
metadata: 
  node_type: memory
  type: project
  originSessionId: 220d4473-eea2-4366-b9bb-ac6d404ff8dc
  modified: 2026-08-18T00:34:06.426Z
---

`ai/todo.md` in this repo is not fixed once a plan is approved and implementation starts. During one session, after a 4-item plan was approved and all 4 items were implemented/committed, re-reading `ai/todo.md` for an unrelated reason revealed the user had appended much more specific requirements to one of the *already-implemented* items (a `--git` flag) mid-session, while implementation was underway — including a `manual`/`auto` message-style split and "keep the old manual-commit code as a safety net" — none of which had been visible during the original planning/approval pass.

**Why:** this wasn't communicated via a chat message; it only showed up as a diff in the todo file itself, discovered incidentally. Treating the file as read-once-at-planning-time would have silently under-delivered against the user's actual (updated) intent.

**How to apply:** for any task anchored to `ai/todo.md` (or likely any user-maintained task/spec file), re-read the file before considering a todo item done — not just once at plan time — especially before a final "checked off" commit. If new detail appears that changes the shape of already-built work, treat it as in-scope follow-up work in the same session rather than a separate future task, and note in the commit message that the file was updated mid-implementation.
