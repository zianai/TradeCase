# TradeCase compliance research and rule contract

The host Agent researches and explains requirements; `tradecase.compliance` validates structured inputs and applies fixed comparisons. No model API or Agent loop runs inside the rule engine.

## Source collection

For each proposed rule, preserve a regulator or platform official URL, actual retrieval time, quoted excerpt or locator, and an Evidence ID. `source_type` must be `government` for a country rule and `platform_official` for a platform rule. Supporting rule evidence must match the exact source URL, use `assertion_status: supported`, and have the same synthetic status as the rule. A supplied source classification is a claim to review, not independent proof that an arbitrary URL is authoritative.

Government guidance can explain a requirement without establishing the exact effective date or all legal exceptions. A public platform blog can explain a workflow without replacing product-specific Seller Central policy. If the relevant body is blocked, record that restriction. Do not bypass authentication or pretend the page was read.

`rules/live-research-2026-10-27.json` deliberately leaves current-law/policy sufficiency unconfirmed. It can demonstrate traceable research but cannot produce a passing check. `rules/synthetic-demo-v1.json` is fabricated test data and is usable only in a synthetic Case.

## JSON rule fields

A rule set is `{"schema_version":"1.0","rules":[...]}`. Each rule has:

- Identity and scope: `rule_id`, `check_type` (`country` or `platform`), `version`, `product_scope`, `applicability`.
- Comparison: nonempty `attributes_required` and `required_values`. Every comparison key must appear in the required-attribute list. Values are typed strings or booleans; the string `"true"` is not boolean `true`.
- Provenance: `source_url`, `source_evidence_ids`, `effective_date`, `reviewed_at`, `valid_until`, `source_current`, `is_synthetic`.
- Human explanation: `severity`, `rationale`, `suggested_action`.

Country rules must specify `applicability.target_country`; platform rules must specify `applicability.platform`. The keys `target_country`, `origin_country`, `sales_channel`, and `platform` read CaseInput fields. All other applicability keys read `seller_context.product_attributes`, e.g. `children_product: true`. Product category matching is exact; the engine does not infer a regulatory classification from free text.

Required values also read seller product attributes. `false` is an observed value and never treated as missing. Missing or explicitly unknown attributes lead to `needs_context`. An explicit scope mismatch leads to `not_applicable` with the mismatched fields shown. If no supplied rule covers the declared country/platform, a separate `needs_verification` check records that research gap.

## Gates and timestamps

A passing check requires complete applicability context, observed required attributes, exact expected values, current official source evidence, an effective date not in the future, a review timestamp not in the future, and a `valid_until` timestamp not in the past. All rule source evidence must have been captured at or before the check time. Reserved example domains cannot support real evidence. Unknown or false `source_current` never passes.

`check_case` uses the current UTC clock for real Cases. An explicit `checked_at` is accepted only when the Case and every rule are synthetic, so offline fixtures can run reproducibly at their declared demonstration time. Validator replay uses the saved check timestamp: it verifies the historical result, not ongoing legal validity. Before a new commercial decision, research current sources and run a new check.

The engine preserves a canonical `rules_snapshot.json` and SHA256 in `compliance.json`; validation recomputes the entire result from that snapshot, source evidence, Case context and check timestamp. Changing only a status, rule value, explanation or hash cannot turn a failed evaluation into a valid passing evaluation. Someone with unrestricted filesystem access can replace the whole Case; this is an audit aid, not a tamper-proof authorization service.

## CLI and review

```sh
tradecase compliance --case cases/example --rules rules/live-research-2026-10-27.json
tradecase report --case cases/example
tradecase validate --case cases/example --strict
```

For the synthetic fixture, use the synthetic rule file and the demo's fixed timestamp. Do not supply synthetic rule evidence to a real Case. After a rule or seller attribute changes, rerun compliance before rendering the final report. Preserve previous revisions in the Case history.

A report needs two feedback forms: narrative annotations explaining scope and missing information, and JSON risk markers (`status`, `severity`, `missing_items`, `suggested_action`). Any unresolved or adverse check requires `needs_review`; the CLI does not approve publication or send messages.
