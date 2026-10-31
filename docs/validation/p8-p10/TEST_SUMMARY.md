# Final test evidence

All following commands ran at `381fbc182429562046461dd518bcb4d8851ff77e` with empty inherited service credentials, disabled tracing and public outbound denied by the coordinator macOS sandbox. Tracked patch digest is the empty SHA-256 in each result. Only task evidence remained untracked.

| Run | Result | Record |
|---|---|---|
| make check | exit 0; 509 passed, 4 infrastructure opt-in skipped; compile/lint/licenses/source manifest passed | evidence/final-v2-check/result.json |
| make contract | exit 0; 43 passed; frozen 1.0.0 hashes preserved | evidence/final-v2-contract/result.json |
| verify_infrastructure.py | exit 0; 4 passed against actual PostgreSQL/Redis | evidence/final-v2-infrastructure/result.json |
| npm run build | exit 0, Next production build/typecheck | evidence/final-v2-frontend-build/result.json |
| p8_browser_acceptance.py, six suites | exit 0; 18 passed; real API flows plus explicitly isolated UI fixtures | evidence/final-v2-browser/result.json |
| p8_tls_acceptance.py | exit 0; trusted local certificate, unauthorized routes, unknown CA refusal | evidence/final-v2-tls/result.json |

Screenshots are hashed in render-manifest.json. Local health latency measurements are in evidence/final-v2-browser/render/runtime.json. Unit/scripted-provider tests prove engineering behavior only. No new real model, provider bill, human business review or production effect is implied.
