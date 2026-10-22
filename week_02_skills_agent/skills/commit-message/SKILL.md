---
name: commit-message
description: Writes git commit messages in the team's Conventional Commits style. Use when the user asks for a commit message, a summary of a code change for git, or a changelog line.
license: MIT
allowed-tools: load_skill
---

# Commit message style

1. First line: `<type>(<scope>): <summary>`, at most 60 characters, imperative mood, no period.
   Types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`.
2. Leave one blank line, then a short body explaining why, wrapped at 72 characters.
3. If the change fixes an issue, end with a line `Refs: #<number>`.

Example:

```
fix(parser): reject frontmatter without a closing line

An unclosed block used to swallow the whole file as metadata.

Refs: #42
```

Reply with the commit message only, inside one code block.
