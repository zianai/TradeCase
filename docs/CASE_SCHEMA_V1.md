# Case Schema v1

The executable schema is `src/tradecase/models/__init__.py` (Pydantic v2,
`extra=forbid`, strict primitive types). `schema_version` is always `1.0`; a future
version requires an explicit migration, never silent coercion.

Models: CaseInput, SellerContext, Candidate, Evidence, Contact, BuyerProfile,
Signal, Assessment, ComplianceCheck/ComplianceResult, NextAction/NextActions,
Manifest, TaskEvent. Source types and business states follow the implementation
baseline. Missing values remain null; a high confidence label is not proof.

`tradecase put --case PATH --artifact evidence.jsonl --file agent-output.jsonl`
imports a schema-validated artifact and records a revision. Use `validate` while
working and `validate --strict` for a full deliverable set. A complete set marked
`needs_review` may validate successfully: technical validity and positive business
findings are different. Run `status` to see missing artifacts. After interruption,
run `recover`, inspect the event trail and revalidate.

Evidence IDs identify claims, not URLs. Candidate IDs identify proposed entities,
not names. Contact `verified` cannot be true for inferred email; `send_allowed`
is always false. Synthetic cases and outputs carry `is_synthetic=true`; synthetic
evidence is forbidden in a real case. Manual edits invalidate indexed hashes.

Raw inquiry bytes are Base64 with SHA256; readable content is separately retained.
Artifact index hashes bind file bytes; events have strictly increasing revision
numbers with the final revision equal to the manifest. Reports and drafts are
plain Markdown, never an executable instruction source.
