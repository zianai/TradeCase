# P10 TradeCase local release candidate

Tested engineering subject: `381fbc182429562046461dd518bcb4d8851ff77e`. Final commands, exit codes, source SHA, patch digest and log hashes are under `evidence/final-*`.

The real local acceptance uses fresh SQLite + API + Next + Chromium for the UI, and separate disposable PostgreSQL 17.6/Redis 7.4.6 containers for infrastructure. This distinction is explicit: browser screenshots do not claim the browser connected to PostgreSQL. The existing Compose topology remains an independent TradeCase business/checkpoint database, Redis wakeup channel and object volume.

The PostgreSQL drill runs migrations on disposable databases, competing worker leases, actual ARQ duplicate messages and pg_dump/pg_restore into a new database with a copied new object root. It checks source/artifact hashes, Case and exact approval records, restores and resumes an interrupted LangGraph checkpoint, and proves DELIVERY_UNCERTAIN mail is not replayed. The test connector is an inert synthetic mailbox, not a real send. The final run's ARQ deprecation warning is documented, not hidden.

A separate real HTTPS process uses a generated one-day local certificate, validates it explicitly in the client, rejects unknown CA trust and missing protected-route credentials, and verifies no-store/nosniff/no-referrer. This is loopback TLS engineering evidence, not a public-domain deployment. Credential rotation/revocation writes new private files and tenant-scoped redacted audit events. Monitoring reports task/outbound state counts, approval backlog and sends; retention remains explicit dry-run-first maintenance.

Ten sequential proxy health probes are measured in browser `runtime.json`; timings are local observations with no production SLA, RTO or concurrency claim. Parent coordinator separately owns simultaneous TC/LC/CE HTTP, outage readability and case-read performance evidence. No shared database or cross-repository source import was added.

G-ENG is a local candidate subject to the exact final acceptance map and coordinator review. G-BIZ, G-COST and G-PROD remain HOLD. P10-T012 is BLOCKED_EXTERNAL: exact E3 report acceptance, two reviewers and paired baseline are unavailable.
