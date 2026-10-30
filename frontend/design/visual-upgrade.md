# Visual Task UI — incremental integration

2026-10-30. Audience and visual language remain those in `brief.md` and `decisions.md`.

The user explicitly requires an optional Visuals panel, recommendations, plan approval, result approval, and proposal preparation while preserving the existing inquiry workbench. Existing tokens, sidebar, case navigation, form and button patterns therefore take precedence over the design skill's default exploration of alternative visual directions. No fonts, palette, or core workbench layout were replaced.

The new flow separates three user decisions: product/reference authorization, exact plan and budget approval, and image business approval. Saving a plan never approves it. The approved plan checkbox is bound to its hash. Original source images and generated assets use separate authenticated routes. Old-plan or stale-truth assets cannot be selected for delivery. Source facts, output concept identity, mock provenance and business approval are presented separately.

The API is authoritative. Recommendations are optional and a missing Visual service does not prevent loading the ordinary inquiry, evidence, compliance or draft views. The UI never requests a mail send, auto-approves a plan, or dispatches generation while merely opening the case.

Verification uses the dedicated local API and persisted database with an explicitly simulated Creative Engine. Browser E2E covers product and source uploads, exact plan authorization, polling, decoded image display, asset approval, proposal ZIP, draft revision, reload persistence, unchanged Evidence, no outbound actions, and narrow-screen overflow. Test and screenshot artifacts remain local per the user's request not to submit test sets. Root's upgrade acceptance report records final executed counts and environment limits.

This is an implementation review record, not a claim of user-approved visual design or actual image-generation quality. The pre-existing workbench direction remains provisional; no new human design baseline is asserted.

Final UI execution: three real local API browser scenarios passed (including decoded mock image `naturalWidth > 0`); eleven existing safety/draft/SSE regressions passed. Static audits of the captured runtime DOM at 1440×900 and 390×844 ended with zero failures and seven warnings. Two inherited accessibility defects revealed by the new case state were corrected: the Decisions link now derives its name from visible text and pending count, and the draft tab badge uses the existing ink color for contrast. Remaining warnings concern existing token/grid conventions, compact mobile targets and multiple action buttons; no overflow, clipped text, invisible focus or axe violation remained. This audit does not validate image quality, real engine availability or user design approval.
