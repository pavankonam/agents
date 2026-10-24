---
name: ticket-checksum
description: >
  Complete or validate a team ticket ID such as HX-40217 by computing its check
  letter with a bundled script. Use when the user asks for the full ticket ID,
  the check letter, or whether a ticket ID with a letter is valid.
license: MIT
allowed-tools: run_skill_script(scripts/check_letter.py)
metadata:
  author: pavankonam
  version: "1.0"
---

# Ticket check letters

Every ticket ID ends with a check letter, for example `HX-40217-?`. Never compute
it yourself: the weights change between projects and mental arithmetic is error prone.

1. Call `run_skill_script` with skill `ticket-checksum`, script
   `scripts/check_letter.py` and the ticket ID as the only arg
   (for example `["HX-40217"]` or `["HX-40217-Q"]` to validate).
2. Copy the script's first output line into your answer exactly.
3. If the script exits with code 2, tell the user the ID format is wrong and show
   the expected format `XX-NNNNN`.
