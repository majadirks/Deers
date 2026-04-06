if name == “main”:
main()
Test Criteria
∙	Full game loop runs from parking_lot to queue_window and back
∙	WAIT 8 times triggers office closure and loop reset
∙	Loop reset correctly increments loop_number and regenerates DEERS
∙	All 3 win conditions are reachable via direct state manipulation in tests
∙	All 4 lose conditions fire correctly
∙	permanent_knowledge survives loop reset
∙	NPC trust survives loop reset for permanent NPCs
∙	Game never throws unhandled exception on any verb + target combination
Handoff Note
Update CLAUDE.md. Note which win conditions were verified and how. Note any action interactions that needed adjustment. Next: Phase 4, persistence.
Phase 4: Persistence
Goal: Save and load working reliably. Game state survives process restart.
Steps
4.1 — Write deers/persistence.py
import json
from pathlib import Path
from deers.state import GameState
SAVE_DIR = Path(“saves”)
def save_game(state: GameState, slot: str = “autosave”) -> None:
SAVE_DIR.mkdir(exist_ok=True)
path = SAVE_DIR / f”{slot}.json”
with open(path, “w”) as f:
json.dump(state.to_dict(), f, indent=2)
def load_game(slot: str = “autosave”) -> GameState | None:
path = SAVE_DIR / f”{slot}.json”
if not path.exists():
return None
with open(path) as f:
return GameState.from_dict(json.load(f))
def save_exists(slot: str = “autosave”) -> bool:
return (SAVE_DIR / f”{slot}.json”).exists()
4.2 — Wire auto-save into engine
Auto-save triggers exactly on:
∙	trigger_reset() — end of each loop
∙	Clean KeyboardInterrupt in main.py
Do NOT save on every action — this would be slow and undermines the loop-as-retry mechanic.
4.3 — Wire load into main.py
On startup, if autosave exists, offer to continue. If declined, start fresh (delete autosave).
4.4 — Write narrator cache persistence
The narrator description cache should persist to saves/narrator_cache.json so descriptions aren’t regenerated unnecessarily across sessions. Key format: “{location_id}:{loop}:{morale_bracket}”.
Test Criteria
∙	Save file is valid JSON
∙	Load → play 3 actions → save → load produces identical game state
∙	permanent_knowledge and NPC trust survive full save/load cycle
∙	Auto-save triggers on loop reset
∙	Narrator cache survives process restart
Handoff Note
Update CLAUDE.md. Note save file schema version (start at “v1”). Next: Phase 5, Claude integration — parser first.
Phase 5: Claude Integration — Input Parser
Goal: Replace keyword parser with Claude. All other output still static.
Steps
5.1 — Write deers/claude_client.py
Implement ClaudeClient and PromptLibrary as designed. Load prompts from content/prompts.toml.
Include retry logic for complete_json:
def complete_json(self, …, max_retries: int = 2) -> dict:
for attempt in range(max_retries + 1):
try:
raw = self.complete(…)
clean = re.sub(r”^json\s*|\s*$”, “”, raw.strip())
return json.loads(clean)
except json.JSONDecodeError:
if attempt == max_retries:
raise
continue
5.2 — Write deers/parser.py
Implement InputParser as designed. Key requirements:
∙	Temperature 0.1 for reliability
∙	Context includes: location id, NPCs present (with display names), inventory, exits, queue position
∙	Returns ParsedAction with clarification set if ambiguous
∙	On any API failure, falls back to _simple_parse()
def parse(self, raw: str, state: GameState) -> ParsedAction:
try:
context = self._build_context(state)
result = self.claude.complete_json(
system=self.prompts.parser_system,
messages=[{“role”: “user”, “content”: f”Context:\n{context}\n\nPlayer input: {raw}”}],
max_tokens=150,
temperature=0.1,
)
return ParsedAction(**result)
except Exception:
return self._simple_parse(raw)    # fallback
5.3 — Update engine.py
def init(self, player_name: str, api_key: str | None = None):
…
if api_key:
claude = ClaudeClient(api_key)
self.parser = InputParser(claude, prompts)
def handle_input(self, raw: str) -> str:
if self.parser:
parsed = self.parser.parse(raw, self.state)
else:
parsed = self._simple_parse(raw)
…
5.4 — Update main.py
import os
api_key = os.environ.get(“ANTHROPIC_API_KEY”)
engine = GameEngine(player_name=name, api_key=api_key)
Test Criteria
∙	“go north” parses to GO / north
∙	“chat with the old guy” parses to TALK / e7 when E-7 is present
∙	“look around” parses to EXAMINE / location
∙	“asdfgh” returns a clarification, not a crash
∙	API timeout falls back to keyword parser without crashing
∙	Parser never returns verb not in the valid set
Handoff Note
Update CLAUDE.md. Note any prompt adjustments needed to get reliable parsing. Next: Phase 6, narrator.
Phase 6: Claude Integration — Narrator
Goal: All location descriptions, event narration, and item examination are generated.
Steps
6.1 — Write deers/narrator.py
Implement NarratorEngine as designed. Requirements:
∙	Cache keyed on {location_id}:{loop_number}:{morale_bracket}:{time_bracket}
∙	time_bracket: “morning” (9-11:30), “lunch” (11:30-12:30), “afternoon” (12:30-16:00)
∙	Cache persisted to saves/narrator_cache.json
∙	describe_location(state) — full scene description
∙	describe_document(doc) — examination text, cached per doc instance
∙	narrate_event(event, state) — result of significant actions only
Define “significant” events — not every action needs narration. Significant: entering a new location, DEERS field checked, document accepted/rejected, queue advanced, morale milestone crossed, NPC trust threshold crossed.
6.2 — Write context builders
Each narrator call needs a rich context dict. Build helpers:
def _location_context(self, state: GameState) -> dict:
loc = state.current_location()
return {
“location_name”: loc.name,
“static_facts”: loc.static_facts,
“npcs_present”: [n.display_name(state) for n in loc.present_npcs(state)],
“features_present”: [f.name for f in loc.features],
“time_of_day”: state.clock.time_display(),
“time_bracket”: state.clock.time_bracket(),
“loop_number”: state.loop_number,
“morale_bracket”: state.morale.bracket(),
“queue_position”: state.queue_position,
“days_until_monday”: state.clock.days_until_monday,
}
6.3 — Tune narrator prompt
The narrator prompt in prompts.toml will almost certainly need tuning after seeing real output. Criteria for a good narrator response:
∙	Second person present tense throughout
∙	No “you should” / “you could” / “you might want to”
∙	No list of available actions
∙	Tone: dry, clinical, occasionally absurd
∙	Under 80 words for location description, under 40 for event narration
Iterate on the prompt until all criteria are met across all 7 locations. Document final prompt in CLAUDE.md.
6.4 — Update engine to use narrator
Replace all loc.static_description returns with self.narrator.describe_location(state) where the narrator is available.
Test Criteria
∙	All 7 locations generate descriptions without error
∙	Same location+state produces same output (cache working)
∙	Loop 3 waiting room description differs from loop 1 (loop number in context)
∙	Critical morale description differs from high morale description
∙	API failure returns loc.static_description without crash
∙	No description exceeds 100 words
Handoff Note
Update CLAUDE.md with final narrator prompt and any cache invalidation discoveries. Next: Phase 7, dialogue.
Phase 7: Claude Integration — Dialogue
Goal: Full multi-turn NPC conversations with generated responses.
Steps
7.1 — Write deers/dialogue.py
Implement DialogueEngine with ConversationBuffer integration.
Full flow:
player: TALK e7
engine: opens ConversationBuffer for e7
engine: displays available topics OR player types freely
player: asks about workaround
engine: _get_unlockable_content(e7, “workaround”, state) -> unlockable dict
engine: builds system prompt from CharacterCard + state
engine: sends history + unlockable content to Claude
engine: Claude generates response in character
engine: commits trust_delta, knowledge_gained, morale_delta to state
engine: checks if conversation should close (exhausted, player walks away)
7.2 — Implement topic detection
Player input during conversation should be parsed for topic, not verb/target:
TOPIC_PARSER_SYSTEM = “””
The player is in conversation with an NPC in a text adventure.
Identify which topic from the available list best matches their input.
If no topic matches, return “freeform”.
Respond only with JSON: {“topic”: “workaround”, “confidence”: 0.9}
“””
Topics not in the NPC’s knowledge map → NPC responds generically (Claude improvises within voice).
7.3 — Implement conversation closing
Conversation closes when:
∙	Player types LEAVE, BYE, WALK AWAY, or equivalent
∙	Buffer hits max_turns
∙	Player moves to different location
On close: commit all accumulated side effects atomically.
7.4 — Author all NPC dialogue seeds
For each NPC × topic combination, write the knowledge_map template string that Claude will be told it can reveal. These are facts, not prose — Claude writes the prose.
Example:
[knowledge_map]
workaround = “There is a phone number for the DEERS help desk that bypasses the local system. The E-7 knows it but will only share it with someone who has demonstrated patience and bought him a coffee.”
base_library_location = “The base library has a photocopier that accepts civilian ID. It is in building 47, across from the PX.”
7.5 — Tune dialogue prompt
Dialogue prompt must enforce:
∙	Character voice stays consistent (gruff E-7 ≠ apologetic clerk)
∙	NPC does not volunteer information above their trust threshold
∙	NPC does not break the fourth wall
∙	Responses under 3 sentences
∙	NPC reacts to player morale (exhausted players get less patience from the clerk)
Test Criteria
∙	E-7 refuses to share workaround at trust 0
∙	E-7 shares workaround at trust ≥ 3
∙	permanent_knowledge gains WORKAROUND_KNOWN key after workaround revealed
∙	Conversation buffer correctly limits to max_turns
∙	API failure returns NPC’s fallback_line
∙	Trust accumulates correctly across multiple loops for permanent NPCs
∙	Corrected-clerk lose condition fires from within dialogue
Handoff Note
Update CLAUDE.md with final dialogue prompt and trust threshold calibration notes. Next: Phase 8, integration and balance.
Phase 8: Integration, Balance, and Polish
Goal: A complete, playable, balanced game with all three win conditions reachable.
Steps
8.1 — Full integration test
Play through all three win conditions manually and record:
∙	Loop count required for each
∙	Morale state at win
∙	Which DEERS corruptions were encountered
∙	Which documents were the critical blockers
Target balance:
∙	Standard victory: achievable in 1-3 loops with correct play
∙	Workaround: requires 3+ loops and E-7 trust ≥ 3
∙	Transcendence: requires 5+ loops and specific event sequence
8.2 — Tune DEERS generator probabilities
After integration testing, adjust corruption_prob and mitigation values so:
∙	Loop 1 always has 2-3 corruptions (harsh start)
∙	Loop 3+ averages 1-2 with correct knowledge
∙	The IMPOSSIBLE combination appears roughly 1 in 8 loops (rare enough to feel special)
8.3 — Tune morale economy
Review all drain/restore rates. Target: a player who engages thoughtfully (talks to NPCs, uses the vending machine, doesn’t wait excessively) should arrive at the window with 40-60% morale. A player who just waits should collapse before reaching the window.
8.4 — Write all three ending sequences
Each win condition gets a hand-authored closing paragraph (not generated — these are too important):
∙	Standard: the single clinical sentence about temporary access expiring
∙	Workaround: a paragraph of deliberate ambiguity
∙	Transcendence: full credits sequence, you become the clerk
These are authored in content/endings.toml and returned verbatim.
8.5 — Add HELP command
Not generated. Static authored text explaining available verbs. Important for IF accessibility.
8.6 — Add status display
After every action, show a compact status line:
[Loop 2 | Thu 10:47 AM | Morale: ██████░░ 62% | Queue: 12]
This is pure formatting, no Claude involvement.
8.7 — Write tests/test_integration.py
def test_standard_victory_path():
“”“Simulate a clean run to standard victory.”””
state = GameState.new_game(“Test”)
# Manually set DEERS to issuable, inventory to valid
# Walk through action sequence
# Assert WinCondition.STANDARD reached
def test_loop_reset_preserves_knowledge():
…
def test_all_lose_conditions():
…
Test Criteria
∙	All 3 win conditions reachable without cheating
∙	All 4 lose conditions fire reliably
∙	No unhandled exceptions across 50-action random play sessions
∙	Status line displays correctly at all morale levels
∙	HELP returns useful output
∙	Transcendence path requires correct event sequence (not accidental)
Handoff Note
Update CLAUDE.md with final balance values. List any content gaps discovered during integration. Next: Phase 9, final polish.
Phase 9: Final Polish
Goal: Shippable. Consistent voice, no rough edges, clean cold start.
Steps
9.1 — Voice consistency pass
Read every static_description, fallback_line, flavor_text, and ending in sequence. Flag anything that breaks the Douglas Adams / government form tone. Fix in TOML — do not touch Python.
9.2 — Cold start experience
The first 10 player actions are the game’s most important. Play through them fresh (no save) and verify:
∙	The premise is clear without an info-dump
∙	The central paradox (need CAC to get on base to get CAC) is encountered naturally
∙	The player has a meaningful choice within 3 actions
9.3 — Error message audit
Every failure_message across all actions and conditions should be in voice. Review them all. A condition failure message like “You can’t do that” is unacceptable — it should be something the narrator would say.
9.4 — README
Write README.md covering:
∙	What the game is (one paragraph)
∙	Install and run instructions
∙	ANTHROPIC_API_KEY setup
∙	How to start a new game vs continue
∙	Known limitations
9.5 — Final CLAUDE.md update
Document final state of all design decisions, known issues, and any planned extensions.
Appendix: Permanent Knowledge Key Registry
Define these keys before Phase 3. Add to CLAUDE.md. Every key must be documented with: what unlocks it, what it enables.
WORKAROUND_KNOWN          — E-7 trust >= 3, topic: workaround
LIBRARY_LOCATION_KNOWN    — E-7 or contractor, topic: base_library_locationCLERK_NAME_KNOWN          — E-7 trust >= 1
SUPERVISOR_NAME_KNOWN     — E-7 trust >= 2
DEERS_FIELD_last_name     — Encountered and resolved this corruption
DEERS_FIELD_ssn_last4     — Encountered and resolved this corruption
DEERS_FIELD_dod_id        — Encountered this corruption
DEERS_FIELD_clearance     — Encountered this corruption
LAMINATION_RULE_KNOWN     — Learned birth certificate can’t be laminated
PHOTOCOPY_TRICK_KNOWN     — Learned photocopier workaround
LUNCH_HOURS_KNOWN         — Learned office closes for lunch
IMPOSSIBLE_SEEN           — Encountered the dod_id + clearance combination
TRANSCENDENCE_STEP_1      — Befriended clerk (trust >= 2)
TRANSCENDENCE_STEP_2      — Fixed a DEERS bug by accident
TRANSCENDENCE_UNLOCKED    — All steps complete; ending available
Appendix: Phase Completion Checklist
Before closing any session, verify:
∙	All tests pass (pytest tests/)
∙	main.py runs to a prompt without error
∙	CLAUDE.md updated with current phase, next action, known issues
∙	No uncommitted content changes (TOML files are source of truth)
∙	Narrator cache not corrupted (delete and regenerate if uncertain)
