# DEERS IN THE HEADLIGHTS — Game Specification

## Overview

A text adventure game about bureaucratic horror. The player is a contractor who needs a Common Access Card (CAC) to start their job on Monday — but getting a CAC requires going through DEERS (Defense Enrollment Eligibility Reporting System), and DEERS has errors in your record that may or may not be fixable.

**Tone:** Douglas Adams meets government memoranda. Second person present tense. Dry, clinical, occasionally absurd. The humor is the humor of accurate description.

---

## Project Structure

```
deers/
├── content/
│   ├── locations.toml
│   ├── npcs.toml
│   ├── documents.toml
│   ├── deers_fields.toml
│   └── prompts.toml
├── deers/
│   ├── __init__.py
│   ├── content.py          # loaders for content/
│   ├── models.py           # all dataclasses
│   ├── deers_record.py     # DEERSRecord + DEERSGenerator
│   ├── inventory.py        # Document + Inventory
│   ├── morale.py           # MoraleMeter
│   ├── clock.py            # GameClock
│   ├── npcs.py             # NPC + ConversationBuffer
│   ├── locations.py        # Location + Feature
│   ├── actions.py          # Action + ActionResolver
│   ├── conditions.py       # ConditionScheduler + all checks
│   ├── state.py            # GameState
│   ├── engine.py           # GameEngine (top-level orchestrator)
│   ├── claude_client.py    # ClaudeClient + PromptLibrary
│   ├── parser.py           # InputParser
│   ├── narrator.py         # NarratorEngine
│   ├── dialogue.py         # DialogueEngine + ConversationBuffer
│   └── persistence.py      # save/load
├── tests/
│   ├── test_content.py
│   ├── test_models.py
│   ├── test_actions.py
│   ├── test_conditions.py
│   ├── test_state.py
│   └── test_integration.py
├── saves/
├── main.py
├── pyproject.toml
├── CLAUDE.md               # LLM working context
└── GAME_SPEC.md            # this file
```

---

## Core Loop

The game is a **time loop**. Each loop represents one day. The office opens at 9:00 AM and closes at 4:00 PM. The player starts each loop in the parking lot with a fresh DEERS record (same seed = same corruptions per loop+knowledge combination) and must navigate to the processing window before the office closes.

**Start date:** Monday. The player starts on Thursday (4 days). Each loop consumes one day. If Monday arrives without a CAC, the player loses.

**Auto-save:** Triggers only on loop reset (office close). Not every action.

---

## Game Clock

- **Hours:** 9:00 AM – 4:00 PM (office hours)
- **Lunch:** 11:30 AM – 12:30 PM (window closed)
- **Action costs (minutes):**
  - GO: 5, WAIT: 30, TALK: 10, EXAMINE: 2, USE: 5, TAKE: 2, READ: 8, DROP: 1

---

## DEERS Fields

| Field | Fix Method | Blocking | Notes |
|-------|-----------|----------|-------|
| last_name | ON_SITE | Yes | Fixable with passport/DL/birth cert |
| ssn_last4 | HR | Yes | Requires HR office visit |
| dod_id | IMPOSSIBLE | Yes | Cannot be fixed — Transcendence gate |
| clearance_level | FSO | Yes | Requires FSO/JPAS — Transcendence gate (with dod_id) |
| component | HR | No | Non-blocking |
| uic | ON_SITE | No | Non-blocking |
| rank_grade | HR | No | Non-blocking |
| contract_end | CONGRESSIONAL | No | Non-blocking |

**IMPOSSIBLE combination:** `dod_id` + `clearance_level` corrupted simultaneously = Transcendence gate. Probability ~1/8 loops.

---

## Documents (10 types)

| ID | Fixes Fields | Photocopiable | Possible Flaws |
|----|-------------|---------------|----------------|
| passport | last_name, dod_id | Yes | expired, maiden_name |
| drivers_license | last_name | Yes | laminated, expired, wrong_address |
| birth_certificate | last_name, ssn_last4 | No | laminated, maiden_name, unofficial_copy |
| sf86_extract | clearance_level, ssn_last4, rank_grade | Yes | missing_page_2, unofficial_copy |
| appointment_email | uic, component, rank_grade | Yes | wrong_address, unofficial_copy |
| security_officer_letter | clearance_level | No | illegible_notary, expired |
| vehicle_pass_request | (none) | Yes | wrong_address |
| contractor_letter | component, uic, rank_grade, ssn_last4 | Yes | maiden_name, unofficial_copy, missing_page_2 |
| two_forms_id_combo | last_name | Yes | expired, laminated |
| previous_cac | dod_id, last_name | No | expired, illegible_notary |

**Blocking flaws** (prevent document from being accepted): laminated, expired, missing_page_2, illegible_notary

**Non-blocking flaws**: maiden_name, wrong_address, unofficial_copy

---

## Locations (7)

| ID | Name | Notes |
|----|------|-------|
| parking_lot | Installation Parking Lot | Start location |
| installation_gate | Installation Gate | Requires documents to enter |
| waiting_room | DEERS Office Waiting Room | E-7, contractor here; number dispenser |
| queue_window | DEERS Processing Window | Clerk here; final goal |
| vending_alcove | Vending Alcove | Coffee (+15 morale), water (+5 morale) |
| base_library | Base Library | Photocopier; requires LIBRARY_LOCATION_KNOWN |
| supervisors_door | Supervisor's Office (Exterior) | Requires SUPERVISOR_NAME_KNOWN |

**Exit conditions (notable):**
- `installation_gate → waiting_room`: requires ≥1 document AND office not closed
- Entering without valid photo ID sets `tailgating_detected` → lose
- `waiting_room → queue_window`: requires queue number taken
- `waiting_room → base_library`: requires LIBRARY_LOCATION_KNOWN
- `waiting_room → supervisors_door`: requires SUPERVISOR_NAME_KNOWN

---

## NPCs (5)

| ID | Archetype | Permanent | Location | Notes |
|----|-----------|-----------|----------|-------|
| clerk | Clerk | No | queue_window | Resets each loop |
| e7 | Veteran | Yes | waiting_room | Key knowledge gatekeeper |
| contractor | Contractor | No | waiting_room / vending_alcove | Same problem, different mood each loop |
| queue_cutter | Queue Cutter | No | waiting_room / queue_window | Random appearance |
| supervisor | Supervisor | Yes | (never present) | Known only through references |

**Trust levels:** 0 (stranger) → 4 (confiding). Permanent NPCs retain trust across loops.

---

## Morale Economy

| Event | Delta |
|-------|-------|
| deers_field_rejected | −8 |
| document_rejected | −6 |
| queue_advanced_past (queue cut) | −10 |
| office_closed | −5 |
| wait | −3 |
| action_failed | −2 |
| loop_reset | −5 |
| coffee_consumed | +15 |
| water_consumed | +5 |
| document_accepted | +8 |
| deers_field_fixed | +12 |
| knowledge_gained | +6 |
| npc_helpful | +5 |
| chips_consumed | +8 |

**Morale brackets:** high (>75%), medium (51–75%), low (26–50%), critical (≤25%)

**Morale modifier:** scales dialogue option quality (1.0 → 0.75 → 0.5 → 0.25)

---

## Win Conditions (3)

### Standard Victory
- At `queue_window`
- DEERS record is issuable (no blocking corruptions)
- Player has taken a queue number
- Clerk issues CAC; narrative notes 90-day expiration

### Workaround Victory
- `WORKAROUND_KNOWN` in permanent_knowledge
- `workaround_called` flag set (player called DEERS help desk with E-7's number)
- Deliberate narrative ambiguity about whether this actually worked

### Transcendence
- `TRANSCENDENCE_UNLOCKED` in permanent_knowledge
- Requires completing the full sequence:
  1. `TRANSCENDENCE_STEP_1`: Clerk trust ≥ 2
  2. `TRANSCENDENCE_STEP_2`: Fixed a DEERS bug by accident
  3. `IMPOSSIBLE_SEEN`: Encountered dod_id + clearance_level combination
- Player becomes the clerk; full credits sequence

---

## Lose Conditions (4)

| Condition | Trigger |
|-----------|---------|
| MORALE_COLLAPSE | Morale hits 0 (coffee consumed this loop grants reprieve) |
| START_DATE_MISSED | `clock.days_until_monday <= 0` |
| TAILGATING | Entered installation without valid photo ID |
| CORRECTED_CLERK | Player was confrontational with the clerk |

---

## Permanent Knowledge Keys

| Key | Unlocked By | Enables |
|-----|-------------|---------|
| WORKAROUND_KNOWN | E-7 trust ≥ 3, topic: workaround | Workaround win condition |
| LIBRARY_LOCATION_KNOWN | E-7 or contractor, topic: base_library_location | Base library access |
| CLERK_NAME_KNOWN | E-7 trust ≥ 1 | Better clerk dialogue |
| SUPERVISOR_NAME_KNOWN | E-7 trust ≥ 2 | Supervisor's door exit |
| DEERS_FIELD_last_name | Resolved last_name corruption | Reduced future corruption prob |
| DEERS_FIELD_ssn_last4 | Resolved ssn_last4 corruption | Reduced future corruption prob |
| DEERS_FIELD_dod_id | Encountered dod_id corruption | IMPOSSIBLE path awareness |
| DEERS_FIELD_clearance | Encountered clearance_level corruption | Reduced future corruption prob |
| LAMINATION_RULE_KNOWN | Clerk rejected laminated document | Avoid lamination errors |
| PHOTOCOPY_TRICK_KNOWN | Used library photocopier | Document workaround available |
| LUNCH_HOURS_KNOWN | Arrived at window during lunch | Correct timing knowledge |
| IMPOSSIBLE_SEEN | Encountered dod_id + clearance_level | Transcendence path begins |
| TRANSCENDENCE_STEP_1 | Clerk trust ≥ 2 | Transcendence sequence |
| TRANSCENDENCE_STEP_2 | Fixed DEERS bug by accident | Transcendence sequence |
| TRANSCENDENCE_UNLOCKED | All steps complete | Transcendence ending available |

---

## DEERS Generator

- **Seeded deterministic:** `hash(f"{loop}|{sorted(permanent_knowledge)}")` → same inputs always produce same record
- **Base corruption probability:** 45% per field
- **Knowledge mitigation:** −12% per resolved field key in permanent_knowledge
- **Loop 1 guarantee:** ≥ 3 corruptions
- **Always ≥ 1 corruption** (forced if none generated)
- **IMPOSSIBLE combination:** ~1/8 probability when rolling

---

## Claude Integration (Phases 5–7)

Three Claude-powered components, each with authored fallbacks:

### InputParser (Phase 5)
- Temperature 0.1 for reliability
- Parses natural language to `ParsedAction(verb, target, confidence, clarification)`
- Falls back to keyword parser on any API failure
- Context: location, NPCs present, inventory, exits, queue position

### NarratorEngine (Phase 6)
- Cache key: `{location_id}:{loop_number}:{morale_bracket}:{time_bracket}`
- Cache persisted to `saves/narrator_cache.json`
- Falls back to `loc.static_description` on API failure
- Significant events narrated: location entry, DEERS check, document accept/reject, queue advance, morale milestone, trust threshold

### DialogueEngine (Phase 7)
- Multi-turn `ConversationBuffer` per NPC
- Topic detection via separate Claude call (temperature 0.3)
- Trust-gated knowledge reveals
- Side effects committed atomically on conversation close
- Falls back to `npc.card.fallback_line` on API failure

---

## Implementation Phases

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Project scaffold + content authoring | ✅ Complete |
| 2 | Core data models | ✅ Complete |
| 3 | Game logic (deterministic core) | ✅ Complete |
| 4 | Persistence (save/load) | — |
| 5 | Claude — input parser | — |
| 6 | Claude — narrator | — |
| 7 | Claude — dialogue | — |
| 8 | Integration, balance, polish | — |
| 9 | Final polish | — |

---

## Design Decisions (Do Not Relitigate)

- Event log is append-only; game state is projected from it (in practice: effects mutate state directly, events are logged for history)
- Claude handles parsing, narration, dialogue ONLY — all logic is deterministic Python
- DEERS corruption is seeded; permanent_knowledge reduces corruption probability
- Auto-save on loop reset only
- In-game clock: 9am–4pm, lunch 11:30–12:30, actions cost minutes
- Multi-turn ConversationBuffer per NPC, side effects committed on close
- Every Claude component has an authored fallback for API failures
- Exits and exit conditions are wired in `locations.py` as code (not TOML)
- Conditions contain lambdas and cannot be serialized; rebuilt from content on load
- `GameState.to_dict()` saves only permanent state (player_name, loop_number, permanent_knowledge, NPC relationships)
