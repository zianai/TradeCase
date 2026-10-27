# priority-v1: follow-up priority, not creditworthiness

| Signal | Points |
|---|---:|
| verified_identity | 20 |
| buyer_role_evidence | 25 |
| product_fit_evidence | 25 |
| inquiry_specificity | 20 |
| contactability | 10 |

The host Agent supplies discrete signals and evidence IDs, not final numeric
scores. Code validates those references and calculates the same result for the
same inputs. Supported earns its fixed weight; contradicted earns no points but
counts toward known coverage; unknown earns nothing and reduces coverage.
Coverage below 0.6 makes score null. Identity/role gaps, unresolved candidates or
entity conflicts force needs_review. A high score cannot remove these gates.

Publicly observed email is a contact channel, not a verified mailbox. Inferred
email has no contactability points. Search snippets and directory entries remain
research leads. These weights and thresholds are product hypotheses, not a
statistically calibrated probability or company credit rating.
