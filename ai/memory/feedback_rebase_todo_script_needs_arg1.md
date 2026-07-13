---
name: feedback_rebase_todo_script_needs_arg1
description: "GIT_SEQUENCE_EDITOR script for interactive rebase must write to \"$1\", not a literal empty path"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: a808247f-045f-4315-84b5-49fb38c66f8e
---

When building the `commit-with-lplp-style` skill's rebase-cleanup todo script, the heredoc must target `"$1"`:

```bash
cat > "$1" << 'REBASE'
pick ...
REBASE
```

Not `cat > "" << 'REBASE'` (copying the skill doc's template literally without substituting the argument). `git rebase -i` invokes `GIT_SEQUENCE_EDITOR <todo-file-path>`, passing the path as `$1` — an empty target string fails with "No such file or directory" and aborts the rebase before it starts.

**Why:** hit this directly during a stray-`ai:`-commit cleanup ([[project_isthereanydeal_source_expansion]] session, 2026-07-13) — first rebase invocation failed on this exact mistake, had to fix the script and re-run.

**How to apply:** any time writing a `GIT_SEQUENCE_EDITOR` script for `git rebase -i` (this skill's cleanup procedure, or ad hoc), always use `"$1"` as the write target.
