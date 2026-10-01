# Local GenAI security workshop

Inspired by the [Auxin Azure GenAI Security Workshop](https://github.com/Auxin-io/Azure-GenAI-Security-Workshop). These are original local adaptations of its learning patterns. They do not run the Azure notebooks or require workshop credentials.

Start the existing stack with `docker compose up --build -d`, then open http://localhost:8080 and sign in as requester. Switch to approver when reviewing a pending action, or administrator when changing policy. Choose exercises under **Local security workshop**. Langfuse is at http://localhost:3000. Your Qwen model remains under 1 GB; all agents share it.

| Source session | Local equivalent | Difference |
| --- | --- | --- |
| [1: Architecture and data](https://github.com/Auxin-io/Azure-GenAI-Security-Workshop/tree/main/Session1) | Model-only answer versus cited synthetic HR retrieval | Keyword retrieval with deterministic answers; no embedding model, fine-tuning, or from-scratch training |
| [2: Threat modeling](https://github.com/Auxin-io/Azure-GenAI-Security-Workshop/tree/main/Session2) | Local trust-boundary worksheet and facilitator notes | An exercise for our Docker architecture, not their Azure diagram |
| [3: Secure developer harness](https://github.com/Auxin-io/Azure-GenAI-Security-Workshop/tree/main/Session3) | Synthetic expense reads, argument checks, threshold denial, approval queue, actual tool-budget exhaustion | Tools execute locally; no payment or Azure agent runtime |
| [4: Governance and observation](https://github.com/Auxin-io/Azure-GenAI-Security-Workshop/tree/main/Session4) | Distinct task/compliance verdicts and basic/strict input-policy comparison | Deterministic checks and response fixtures; no Azure content filters, LLM judge, or Foundry version service |

## Session 1: Where facts come from

Choose **Compare model answer and cited retrieval**, with “How many days of annual leave?” The baseline model receives no company documents. The retrieval path returns 20 days and `[hr-leave.txt]`. Inspect the generation and retrieval observations in Langfuse.

Repeat with “What is the company pension policy?” The local corpus has no pension document; retrieval refuses. The model may behave differently. Only the baseline response uses real inference here. Retrieval returns trusted document text directly, rather than claiming a model verified a citation.

The three synthetic documents live in `app/workshop.py`: leave, expense receipts, and remote work. Facts can change without retraining. This demonstrates the data boundary; it does not reproduce the source's finance adapter or tiny from-scratch employee model.

## Session 2: Threat modeling

Open [threat-model.md](threat-model.md). Fill in the boundary/control/evidence table before reading the facilitator notes. Identify what the model can suggest, what the harness alone can authorize, and who can approve. Look for controls demonstrated in traces and gaps that require additional architecture.

## Session 3: Read tools versus write tools

Keep tool budget at 2 and publishing enabled in **Governance policy**.

1. **Read an expense**: EXP-001 returns synthetic employee, amount, currency, and purpose without human approval.
2. **Approve a $250 expense**: a policy check creates a pending action. Review its exact ID, amount, and currency in the human queue. Reject one draft and approve another.
3. The local action receipt records the approved request. No payment occurs. Retrying the same approval ID fails.
4. **Deny a nonexistent expense**: argument validation rejects MISSING-999 before creating a human request.
5. **Deny $1,500**: EXP-002 exceeds the fixed $1,000 threshold. It is denied before human approval can override it.
6. **Stop a real sequence at the tool budget**: this exercise repeatedly proposes the same read. With budget 2, two reads execute; the third proposal is denied. Unlike the original team's budget fixture, this exercise consumes real tool calls.
7. Save a changed governance policy after drafting. The stale approval is invalidated. Creating a new draft demonstrates approval against current policy.

Expense scenarios use predefined proposals labeled in the agent span; they do not claim the model selected those actions. The expense agent also accepts custom real-model requests in the team panel. Both paths use the same server-side permission, argument, threshold, and approval gates.

The local implementation limits one specialist action in custom runs, model context/output, and HTTP timeout. It does not reproduce Azure's 6-step/20k-token/180-second agent turn budget. The repeated-read workshop demonstrates enforcement of consumed tool calls; cumulative token budgets and multi-write pause/resume remain extensions.

## Session 4: Two different verdicts

Run **Task passes while compliance fails**. A labeled synthetic response repeats `DEMO_INTERNAL_POLICY`. Task adherence scores exact expected output (1/1); compliance detects the forbidden marker (1/5, fail). Neither value is an overall security/compliance certification. Inspect `evaluation.task_and_compliance` in Langfuse: both verdicts are recorded as evaluator observation output.

Run **Compare basic and strict input policies**. Both receive the same fixed attack string and the same demonstration agent version. Basic has no marker rule and allows the input; strict matches the marker and denies it. No prompt reaches the model in this comparison. This explains policy placement without claiming a deterministic string match can replace Azure's jailbreak classifier.

The existing live agent prompt/policy versions are visible through trace metadata. The workshop comparison records the fixed label `workshop-v1`; it is not an agent version registry.

## Evidence and limits

Every executed lab stores a local trace and exports it to Langfuse. Governance checks include reasons and policy versions; expense actions nest below their specialist. Approval decisions use separate traces linked to the original run. Evaluator verdicts are in observation output, not Langfuse's native score table.

Reviewers now sign in through Keycloak; OPA separates requester, approver, and administrator roles and denies self-approval. Model output is untrusted. Approval storage is persistent SQLite, not a tamper-proof audit system. The model and deterministic fixtures must be distinguished when presenting results. Do not use real expenses, employee records, secrets, or payments in this demo.
