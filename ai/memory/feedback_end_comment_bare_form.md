---
name: feedback_end_comment_bare_form
description: "\"# end def\"/\"# end class\" comments must be bare, never repeat the function/class name"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 3a903f4c-3b2e-42cd-863c-9672ea1fdf8c
---

`# end <keyword>` closing comments (per CLAUDE.md's "close every indentation level" convention) must be bare — `# end def`, `# end class` — never followed by the function/class name.

**Why:** user explicitly corrected this mid-session: "When doing `# end def` etc. never include the function/class name etc. Just `# end <word>`." This matches CLAUDE.md's own literal wording (which lists `# end def`/`# end class` unnamed), even though a lot of pre-existing code in this repo (written before this correction landed) includes the name (`# end def foo`, `# end class Foo`).

**How to apply:** always write bare closing comments (`# end def`, `# end class`, `# end if`, `# end for`, etc.) in new/edited code going forward. Don't mass-rewrite pre-existing named end-comments unprompted — only fix them where you're already touching that code, or if the user asks for a broader cleanup.
