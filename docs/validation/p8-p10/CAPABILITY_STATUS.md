# Capability status

| Capability | State | Evidence / limitation |
|---|---|---|
| Existing Agent SDK, Skills, LangGraph and TaskManager | tested_offline | Full regression; real SDK with scripted local Model is not paid inference |
| Pilot import, frozen provenance export | tested_offline | P8/P9 synthetic and grant-bound negative regressions; real business data absent |
| Source expiration / conflict drill-down | tested_offline | Real API/browser, desktop 1440 and mobile 390 |
| Exact draft/source approval invalidation | tested_offline | API regression and browser workflow |
| PostgreSQL/Redis lease / checkpoint / object restore | tested_offline | Actual disposable services, no production data |
| Loopback TLS, credential rotation, redacted metrics | tested_offline | Actual local TLS process and database-backed tests |
| TC→CE HTTP 1.0.0 consumer | implemented; local coordinator validation | Parameterized loopback smoke; frozen contract unchanged |
| Real inquiry/quality/time baseline | blocked | Requires scoped data and independent human reviewers |
| New paid model or public source acquisition | blocked | No explicit new authorization or budget |
| Public deployment / real sending / remote Git write | blocked | No environment/operator authorization |
| Human design/business approval | blocked | Screenshots and synthetic test actors are not human approval |
