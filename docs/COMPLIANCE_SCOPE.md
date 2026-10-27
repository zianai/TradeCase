# V1 compliance scope and limits

Status: rule engine **implemented / tested_offline**. The sources collected separately in `rules/live-research-2026-10-27.json` are a research snapshot. Their current product-specific rule sufficiency is unconfirmed, so those checks remain `needs_verification`. This document does not claim a legal or platform-policy approval.

V1 covers two independently recorded categories:

| Category | Offline exercise | Public research scope | Output |
|---|---|---|---|
| Destination country | Synthetic US children's-product tracking-label attribute | CPSC tracking-label guidance; exact effective/version date and actual product application require review | Country check with source, applicability, status and severity |
| Sales platform | Synthetic Amazon US listing-safety review attribute | Amazon public listing guidance; relevant current product-specific Seller Central policy body remains needed | Platform check with source, missing context and corrective action |

The synthetic rules are not transcriptions of actual legal or platform requirements. They use reserved domains, synthetic Evidence records and conspicuous Case labels to exercise the complete deterministic pipeline. Their pass/fail outcomes validate program behavior only.

Real-source records preserve actual URLs, capture timestamps and excerpts or locators. `source_current`, `effective_date`, `reviewed_at` and `valid_until` are explicit, reviewable inputs. The evaluator does not invent missing values. It also cannot independently establish that a claimed official source is genuine, that a legal interpretation is correct, or that every applicable rule has been found. Professional review remains necessary for consequential product-safety, import/export, sanctions or contractual decisions.

The rule engine compares exact typed fields in `seller_context.product_attributes`. It does not infer product classification, certification authenticity, platform approval or material safety from prose or uploaded files. User-supplied attributes are declarations, not certification. False is a known value; unknown is not optimistic evidence.

Every evaluation produces both country and platform coverage records, including explicit `needs_context`/`needs_verification` checks where information is missing. A specific out-of-scope rule is marked `not_applicable` with its mismatch. Missing coverage for the declared destination/platform is not silently treated as success. Empty rule sets generate review checks; individual rules cannot use empty requirements to obtain a vacuous pass.

The report renders text annotations plus structured status/severity risk flags. A Case with unresolved or adverse checks stays `needs_review`. Neither the engine nor the report grants permission to send email, submit a listing, edit an account or make a purchase.

The canonical rule snapshot and its hash are preserved in each Case. Validation checks the snapshot hash and recomputes the entire compliance result at its recorded timestamp, including explanatory fields. Historical validation is not a claim that a rule is still current today. Use a new evaluation after reviewing new sources or changing product attributes. The only fixed-time override is for an entirely synthetic Case and rule set.

Validation evidence is recorded under `docs/evidence/P4/` and the P4 phase report. All automated rule tests run without a network or paid service. Live source collection and provider execution are reported separately from the offline rule-engine tests.
