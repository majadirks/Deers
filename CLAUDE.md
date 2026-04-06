# DEERS IN THE HEADLIGHTS — LLM Working Context

## Current Phase: Phase 7 (Claude — Dialogue)
## Last Completed Phase: Phase 6 (Claude — Narrator)
## Passing Tests: 290 passing (14 content, 61 model, 45 action, 24 condition, 32 state, 17 integration, 16 persistence, 39 parser, 42 narrator)
## Known Issues: None
## Next Action: Write deers/dialogue.py, topic detection, trust-gated knowledge, conversation close

## Key Design Decisions (do not relitigate)
- Event log is append-only; game state is projected from it
- Claude handles parsing, narration, dialogue ONLY — all logic is deterministic
- DEERS corruption is seeded; permanent_knowledge reduces corruption probability
- Auto-save on loop reset only
- In-game clock: 9am-4pm, lunch 11:30-12:30, actions cost minutes
- Gameplay days: Monday (loop 1) through Thursday (loop 4); Friday (loop 5+) = START_DATE_MISSED
- Day-of-week is derived from loop_number, not stored in GameClock
- Multi-turn ConversationBuffer per NPC, side effects committed on close
- Every Claude component has an authored fallback for API failures
- Exits and exit conditions are wired in locations.py as code (not TOML)
- Conditions contain lambdas and cannot be serialized; rebuilt from content on load

## Permanent Knowledge Key Registry

| Key | Unlocked By | Enables |
|-----|-------------|---------|
| WORKAROUND_KNOWN | E-7 trust >= 3, topic: workaround | Workaround win condition |
| LIBRARY_LOCATION_KNOWN | E-7 or contractor, topic: base_library_location | Photocopier access knowledge |
| CLERK_NAME_KNOWN | E-7 trust >= 1 | Better clerk dialogue options |
| SUPERVISOR_NAME_KNOWN | E-7 trust >= 2 | Supervisor's door interaction |
| DEERS_FIELD_last_name | Encountered and resolved last_name corruption | Reduced corruption probability |
| DEERS_FIELD_ssn_last4 | Encountered and resolved ssn_last4 corruption | Reduced corruption probability |
| DEERS_FIELD_dod_id | Encountered dod_id corruption | IMPOSSIBLE path awareness |
| DEERS_FIELD_clearance | Encountered clearance_level corruption | Reduced corruption probability |
| LAMINATION_RULE_KNOWN | Clerk rejected laminated document | Avoids lamination errors |
| PHOTOCOPY_TRICK_KNOWN | Used library photocopier successfully | Document workaround available |
| LUNCH_HOURS_KNOWN | Arrived at window during lunch | Correct timing knowledge |
| IMPOSSIBLE_SEEN | Encountered dod_id + clearance_level simultaneously | Transcendence path begins |
| TRANSCENDENCE_STEP_1 | Clerk trust >= 2 | Transcendence sequence |
| TRANSCENDENCE_STEP_2 | Fixed a DEERS bug by accident | Transcendence sequence |
| TRANSCENDENCE_UNLOCKED | All steps complete | Transcendence ending available |

## Content Authoring Status

| File | Status | Notes |
|------|--------|-------|
| content/deers_fields.toml | COMPLETE | 8 fields; dod_id is IMPOSSIBLE; contract_end is CONGRESSIONAL |
| content/documents.toml | COMPLETE | 10 documents; flaws distributed across all |
| content/locations.toml | COMPLETE | 7 locations with features |
| content/npcs.toml | COMPLETE | 5 NPCs with full knowledge maps |
| content/prompts.toml | COMPLETE | narrator, parser, dialogue, topic_parser |

## DEERS Fields Summary
- last_name: ON_SITE, blocking
- ssn_last4: HR, blocking
- dod_id: IMPOSSIBLE, blocking ← IMPOSSIBLE gate
- clearance_level: FSO, blocking ← IMPOSSIBLE gate (with dod_id)
- component: HR, non-blocking
- uic: ON_SITE, non-blocking
- rank_grade: HR, non-blocking
- contract_end: CONGRESSIONAL, non-blocking

## IMPOSSIBLE Combination
dod_id + clearance_level corrupted simultaneously = Transcendence gate.
dod_id alone = IMPOSSIBLE fix but not Transcendence.
clearance_level alone = FSO-fixable.

## NPC Summary
- clerk: not permanent, resets each loop, at queue_window
- e7: permanent, key knowledge gatekeeper, at waiting_room
- contractor: semi-permanent (same problem, different mood), waiting_room/vending_alcove
- queue_cutter: not permanent, random appearance
- supervisor: permanent, never present, known only through references

## Document Flaw Registry
- laminated: drivers_license, birth_certificate, two_forms_id_combo
- expired: passport, drivers_license, security_officer_letter, previous_cac, two_forms_id_combo
- maiden_name: passport, birth_certificate, contractor_letter
- wrong_address: drivers_license, appointment_email, vehicle_pass_request
- illegible_notary: security_officer_letter, previous_cac
- missing_page_2: sf86_extract, contractor_letter
- unofficial_copy: birth_certificate, sf86_extract, appointment_email, contractor_letter
