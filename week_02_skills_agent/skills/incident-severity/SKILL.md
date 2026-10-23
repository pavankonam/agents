---
name: incident-severity
description: >
  Classify a production incident or outage into the team's severity level
  (SEV-1 to SEV-4) and say who must be paged and how fast. Use when a user
  describes something broken in production and asks how serious it is.
license: MIT
metadata:
  author: pavankonam
  version: "1.0"
---

# Incident severity

The severity rules are long, so they live in a separate file.

1. Read `references/severity-matrix.md` with the read_skill_file tool. Do not guess the levels.
2. Pick the highest level whose condition matches the incident.
3. Answer in this format:

```
Severity: SEV-N (Code <colour>)
Page: <who> within <time>
Why: <one sentence that names the matching condition>
```
