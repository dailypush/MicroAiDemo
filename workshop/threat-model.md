# Threat-model worksheet: our local agent lab

Draw: browser → HTTP server → specialist model → proposal → policy → tool/approval queue → SQLite. Add the OTLP path from server → Langfuse web → worker/storage. Mark where instructions, identities, approvals, and data move between systems.

For each boundary, record an attacker goal, a STRIDE category, likelihood/impact, the control, and a trace/test proving the control. Optionally rank damage, reproducibility, exploitability, affected users, and discoverability (DREAD); scores are discussion aids, not measured probabilities.

| Boundary | Attacker goal | Category / risk | Control | Evidence / remaining gap |
| --- | --- | --- | --- | --- |
| User → model | Change instructions to gain tools | Fill in | Fill in | Fill in |
| Model → harness | Invent a tool or expense ID | Fill in | Fill in | Fill in |
| Specialist → delegation | Request another agent's privileges | Fill in | Fill in | Fill in |
| Proposed write → reviewer | Alter amount after approval | Fill in | Fill in | Fill in |
| Reviewer → approval API | Replay or impersonate a reviewer | Fill in | Fill in | Fill in |
| Tool → local state | Bypass an amount ceiling | Fill in | Fill in | Fill in |
| App → telemetry | Disclose data in prompts or traces | Fill in | Fill in | Fill in |
| App → model/runtime | Exhaust resources | Fill in | Fill in | Fill in |

<details><summary>Facilitator notes — read after completing the table</summary>

- Model instructions are not authority. Server-defined tool and delegation permissions block privilege proposals.
- Expense IDs and canonical amounts are checked by the harness. Amounts above $1,000 are denied before human approval. Try an invented report and altered amount in the tests.
- Approval binds exact action text, hash, policy version, expiration, and remaining budget. SQLite transactions and single-use approval states block replay. Anyone who can edit the database remains trusted; a hash stored beside the payload is not protection against a database administrator.
- Browser cross-origin writes are rejected, but the local app has no authenticated reviewer identity. Local access means governance-admin and reviewer access. Separate authentication/authorization is an explicit missing control.
- Synthetic secrets are blocked by a narrow pattern and redacted from governance traces. Langfuse receives prompts/results; no general data classification or DLP is implemented.
- Tool-call budgets are enforced. Model HTTP timeout and output/context caps are bounded; cumulative model-token limits, trace retention, and rate limiting are not implemented.
- Langfuse makes evidence inspectable. It does not decide whether a tool may execute; enforcement belongs in the harness.

</details>
