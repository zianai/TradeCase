# Inbound inquiry SOP

The Case, not a chat, is the source of business state. Keep UTC capture times,
explicit synthetic flags, source excerpts/locators, stable evidence/candidate IDs
and conflicts. Search summaries can discover sources but cannot establish buyer
identity, purchasing role or compliance. User materials are declarations, not
certification. Match a legal entity and inquiry relationship using source facts;
never merge by name alone or assume a free mailbox is a company website.

Begin with two research rounds of four to eight focused queries; stop a path when
it provides no new evidence. The local reader caps fifteen page attempts and
forty requests per Case; dynamic browser research is optional, at most three sites
initially and only in authorized public/new tabs. A blocked source is a reportable
result. Do not bypass login, paywalls, anti-bot restrictions or DNS safety checks.
Log host queries and captures with their actual tools/times; do not label imported
snapshots as current fetches. No private inquiry is uploaded to an external reader.

CLI order is a menu of deterministic operations selected by the host, not a new
execution loop: doctor; init/status/recover; research; put candidate/evidence/profile
and discrete signals; assess; compliance; draft; report; validate --strict;
transition to needs_review or completed. Use .history and events for inspection.
Do not silently overwrite completed or human-reviewed artifacts; reopen explicitly.

Drafts and next_actions remain local. Unknown pricing, payment, lead time, MOQ,
stock and qualification terms require human confirmation. Draft review hashes bind
body and input/seller basis; changing them invalidates the previous review. A
technically complete Case may still require human follow-up. No SMTP credentials
are required or loaded. The CLI has no send operation.

For procurement notices, set `case_type=procurement` during init (or in the
input JSON) and supply the deadline evidence ID. Deadline evidence must cite
the complete relevant deadline declaration line in a supported official-source
record and an indexed JSON snapshot with matching `source_url` and
`selected_lines`. The parser supports numeric GMT/UTC offsets, IANA zones and documented explicit
city/US time aliases. Ambiguous abbreviations, DST folds/gaps and conflicting
statements require human review. Date-only notices never imply a precise time:
only after a conservative end-of-date bound is reached may they be marked expired.
Source snapshots can be stale or lack later amendments; a locally open deadline
is not permission to submit. Expired and unverified notices cannot transition
to completed. Drafts and reports must be regenerated if their source changes or
the deadline passes. The CLI never sends messages or bids.
