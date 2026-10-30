# TradeCase Skill catalog

Canonical portable Markdown remains in the original directories below, with an optional visual-opportunity skill for the Visual Domain.
No duplicate business Skill or prompt-owned business state is introduced. `SkillAdapter`
loads these files byte-for-byte and records their SHA-256; the platform supplies
bounded task context, available read-only tools and a typed result contract.

| Skill | Role and inputs | Outputs and handoff |
|---|---|---|
| [trade-inquiry](trade-inquiry/SKILL.md) | Coordinate inquiry analysis using the original CLI; inquiry, seller declarations, existing Case artifacts and unresolved questions. | Parsed inquiry, draft, report and manual follow-up tasks. Platform nodes call the same business functions and persist their outputs as versioned artifacts. |
| [buyer-research](buyer-research/SKILL.md) | Identity, background and purchasing-signal research; inquiry, separate entity candidates, prior source references and explicit gaps. | Candidate facts, profile, exact quotations and source links, conflicts and unknowns. The platform's three research Tasks share this method without creating three redundant Skills. |
| [trade-compliance](trade-compliance/SKILL.md) | Country and platform/terms review; product/market/channel context, current rule versions and official source evidence. | Scoped checks, severity, source/rule references and human review actions; existing deterministic rules compute the result. |

Platform research inputs/outputs are published in
[`contracts/agent-task-request.schema.json`](../contracts/agent-task-request.schema.json)
and [`contracts/agent-task-result.schema.json`](../contracts/agent-task-result.schema.json).
Evidence verification and conservative drafting remain existing kernel capabilities;
source authority and permission confirmations belong to reviewer-bound inputs,
never to a web page or model instruction.

The standalone Skill workflow and CLI still use filesystem Cases. The web
workbench uses PostgreSQL as the business truth and disposable filesystem
materializations solely to reuse the kernel. Never point standalone CLI writes at
a workbench materialization or treat its journal as a second scheduler.

`tradecase install-skills --target both --project .` installs the canonical files
for Codex and Claude without changing them. The hash parity result for this delivery
is in [`skill-install.json`](../docs/evidence/full-delivery/skill-install.json).
Skills grant no sending authority; the workbench's separately approved external
actions remain outside the read-only Agent tool registry.

| [visual-opportunity](visual-opportunity/SKILL.md) | Optional inquiry quotations and product context. | Ranked, schema-validated suggestions only; never execution, evidence promotion or sending authority. |
