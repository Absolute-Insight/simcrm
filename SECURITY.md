# Security Policy

## Reporting a vulnerability

Please **do not open a public issue** for anything you believe is a security
problem. Use GitHub's private vulnerability reporting instead:

**[Report a vulnerability](https://github.com/Absolute-Insight/simcrm/security/advisories/new)**

Include what you can: affected endpoint or doctype, the role you reproduced it
with, and steps to reproduce. Reports are acknowledged within 5 working days.
Please allow a fix to ship before disclosing publicly.

## Supported versions

| Version | Supported |
| ------- | --------- |
| 3.x     | ✅        |
| 2.x     | ❌ (superseded by 3.0.0; upgrade) |
| < 2.0   | ❌ (pre-release history; no fixes) |

## Scope notes for researchers

- Vectora is a Frappe application. Vulnerabilities in the Frappe framework
  itself are best reported to [Frappe's security process](https://frappe.io/security)
  — we will pass framework reports along, but the fix will land there.
- The permission model worth probing: rep-level users must not read or write
  other reps' plans, quotas, suggestions, or deal aggregates outside their
  hierarchy subtree. Anything that breaks that contract is in scope and
  taken seriously.
- Model-generated (agent tier) content is treated as untrusted input by
  design: no model output may reach a write API without an explicit human
  confirmation step. A bypass of that property is a vulnerability.

## Secrets

Secret scanning and push protection are enabled on this repository. The one
historical alert (a Twilio credential in a 2023 commit) is inherited from
upstream frappe/crm's public history, is absent from every current branch,
and cannot be rotated from this repository.
