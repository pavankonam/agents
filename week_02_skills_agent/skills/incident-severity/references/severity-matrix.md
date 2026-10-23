# Severity matrix

Pick the highest level that matches. When two levels fit, choose the more severe one.

| Level | Code | Condition | Page | Within |
| --- | --- | --- | --- | --- |
| SEV-1 | Code Crimson | Checkout or login down for more than 25% of users, or any data loss | Incident commander and on call lead | 5 minutes |
| SEV-2 | Code Amber | A core feature is degraded for more than 5% of users, or checkout errors above 2% | On call engineer | 15 minutes |
| SEV-3 | Code Teal | A non core feature is broken, a workaround exists | Owning team channel | 4 business hours |
| SEV-4 | Code Slate | Cosmetic problem or a typo, no user impact on money or data | Ticket in the backlog | Next sprint |

Notes:

* "Core features" are checkout, login, search and the order history page.
* Data loss is always SEV-1, even for a single user.
