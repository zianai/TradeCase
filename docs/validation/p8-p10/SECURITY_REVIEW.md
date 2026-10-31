# Security review

Subject: `381fbc182429562046461dd518bcb4d8851ff77e`. Scope: local engineering, synthetic inputs and owned temporary services. No high-impact external effect occurred.

Reviewed boundaries: no ambient model credentials/tracing; OS-level public-network denial in the evidence runner; independent tenant scope, RBAC, hash-addressed immutable objects, safe URL/redirect/DNS handling, exact approval invalidation, unknown-send reconciliation, read grants and retention, source provenance, public CI artifact contents and loopback service bindings. CI remains unexecuted remotely; local equivalents carry the recorded exit codes.

Fixed reproducible issues: request-validation input/key reflection; evidence conflict overwrite; expired source promotion; real pilot export grant/retention omission discovered by independent root review. Added role/tenant-scoped credential rotation and revocation. Neither token nor private values appear in audit data. CLI destination must be a new private file; if a disk failure happens after rotation, a separate admin must rotate again. Keep a second admin credential offline during rotation.

`acceptance-results.json` links the exact negative test nodes, actual TLS proof and final immutable-contract checks. Test operator grants are created only inside removed temporary synthetic test directories. They are not stored as active operator authority. Historical P7 evidence is immutable and its previously authorized synthetic smoke is not business validation.

Independent review: root agent inspected pilot/API/UI and requested two fixes recorded in P9_REPORT; this is agent engineering review, not professional security certification or human business acceptance. Production threat assessment, authentic data rights approval and remote access review remain BLOCKED_EXTERNAL.

Closed second-review finding: mixed manual source content no longer inherits Case.synthetic. Full source/claim/link/version and rights hashes are bound to a separate current export grant, with rechecks after snapshot reads. Scope metadata contains no private source titles or excerpts.
