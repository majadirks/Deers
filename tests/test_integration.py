"""Integration tests: full game loop scenarios."""

import pytest
from deers.actions import ActionResolver
from deers.conditions import ConditionScheduler
from deers.content import load_all
from deers.engine import GameEngine
from deers.models import DocumentType, LoseCondition, ParsedAction, WinCondition
from deers.state import GameState


@pytest.fixture
def content():
    return load_all()


@pytest.fixture
def state(content):
    return GameState.new_game("TestPlayer", content)


@pytest.fixture
def engine(content):
    return GameEngine.__new__(GameEngine)


def make_engine(content):
    eng = GameEngine("TestPlayer")
    eng.state.content = content
    return eng


class TestFullGameLoop:
    def test_parking_lot_to_queue_window_and_back(self, content):
        """Full traversal from start to window and back."""
        eng = make_engine(content)
        s = eng.state

        # parking_lot -> gate
        out = eng.handle_input("go gate")
        assert s.current_location_id == "installation_gate"

        # gate -> waiting_room
        out = eng.handle_input("go inside")
        assert s.current_location_id == "waiting_room"

        # Take a number
        out = eng.handle_input("take number")
        assert s.queue_position is not None

        # Wait down to 0
        s.queue_position = 0

        # waiting_room -> queue_window
        out = eng.handle_input("go window")
        assert s.current_location_id == "queue_window"

        # queue_window -> waiting_room
        out = eng.handle_input("go waiting_room")
        assert s.current_location_id == "waiting_room"

    def test_wait_enough_times_causes_loop_reset(self, content):
        eng = make_engine(content)
        s = eng.state
        loop_before = s.loop_number

        for _ in range(20):
            eng.handle_input("wait")
            if s.loop_number > loop_before:
                break

        assert s.loop_number > loop_before

    def test_loop_reset_resets_location_to_parking_lot(self, content):
        eng = make_engine(content)
        s = eng.state
        # Force clock to just before close, then wait
        from deers.clock import OFFICE_CLOSE_MINS
        s.clock.current_minutes = OFFICE_CLOSE_MINS - 29
        eng.handle_input("wait")
        assert s.current_location_id == "parking_lot"

    def test_loop_reset_increments_loop_number(self, content):
        eng = make_engine(content)
        s = eng.state
        from deers.clock import OFFICE_CLOSE_MINS
        s.clock.current_minutes = OFFICE_CLOSE_MINS - 29
        eng.handle_input("wait")
        assert s.loop_number == 2

    def test_permanent_knowledge_survives_loop_reset(self, content):
        eng = make_engine(content)
        s = eng.state
        s.permanent_knowledge.add("WORKAROUND_KNOWN")
        from deers.clock import OFFICE_CLOSE_MINS
        s.clock.current_minutes = OFFICE_CLOSE_MINS - 29
        eng.handle_input("wait")
        assert "WORKAROUND_KNOWN" in s.permanent_knowledge

    def test_e7_trust_survives_loop_reset(self, content):
        eng = make_engine(content)
        s = eng.state
        s.npcs["e7"].relationship.trust = 3
        from deers.clock import OFFICE_CLOSE_MINS
        s.clock.current_minutes = OFFICE_CLOSE_MINS - 29
        eng.handle_input("wait")
        assert s.npcs["e7"].relationship.trust == 3


class TestWinConditions:
    def test_standard_victory_reachable(self, content):
        eng = make_engine(content)
        s = eng.state
        scheduler = ConditionScheduler()

        # Set up win state directly
        s.current_location_id = "queue_window"
        s.queue_position = 0
        for f in s.deers.fields.values():
            f.is_corrupted = False

        result = scheduler.evaluate_all(s)
        assert result is not None
        assert result.kind == WinCondition.STANDARD

    def test_workaround_victory_reachable(self, content):
        eng = make_engine(content)
        s = eng.state
        scheduler = ConditionScheduler()

        s.permanent_knowledge.add("WORKAROUND_KNOWN")
        s.workaround_called = True

        result = scheduler.evaluate_all(s)
        assert result is not None
        assert result.kind == WinCondition.WORKAROUND

    def test_transcendence_victory_reachable(self, content):
        eng = make_engine(content)
        s = eng.state
        scheduler = ConditionScheduler()

        s.permanent_knowledge.add("TRANSCENDENCE_UNLOCKED")

        result = scheduler.evaluate_all(s)
        assert result is not None
        assert result.kind == WinCondition.TRANSCENDENCE


class TestLoseConditions:
    def test_morale_collapse_fires(self, content):
        eng = make_engine(content)
        s = eng.state
        scheduler = ConditionScheduler()

        s.morale.apply_delta(-1000)

        result = scheduler.evaluate_all(s)
        assert result is not None
        assert result.kind == LoseCondition.MORALE_COLLAPSE

    def test_start_date_missed_fires(self, content):
        eng = make_engine(content)
        s = eng.state
        scheduler = ConditionScheduler()

        s.loop_number = 5  # Friday — job start date

        result = scheduler.evaluate_all(s)
        assert result is not None
        assert result.kind == LoseCondition.START_DATE_MISSED

    def test_tailgating_fires(self, content):
        eng = make_engine(content)
        s = eng.state
        scheduler = ConditionScheduler()

        s.tailgating_detected = True

        result = scheduler.evaluate_all(s)
        assert result is not None
        assert result.kind == LoseCondition.TAILGATING

    def test_corrected_clerk_fires(self, content):
        eng = make_engine(content)
        s = eng.state
        scheduler = ConditionScheduler()

        s.corrected_clerk = True

        result = scheduler.evaluate_all(s)
        assert result is not None
        assert result.kind == LoseCondition.CORRECTED_CLERK


class TestEngineHandleInput:
    def test_no_crash_on_any_verb(self, content):
        """Engine must not raise on any verb+target combination."""
        eng = make_engine(content)
        test_inputs = [
            "go gate",
            "examine location",
            "examine passport",
            "read passport",
            "read drivers_license",
            "drop passport",
            "wait",
            "help",
            "status",
            "talk to nobody",
            "use the air",
            "take the ceiling",
            "frobnicate everything",
            "asdfghjkl",
            "",
            "   ",
        ]
        for inp in test_inputs:
            try:
                result = eng.handle_input(inp)
                assert isinstance(result, str)
            except Exception as e:
                pytest.fail(f"Input '{inp}' raised {type(e).__name__}: {e}")

    def test_engine_start_returns_string(self, content):
        eng = make_engine(content)
        result = eng.start()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_engine_shows_status_line(self, content):
        eng = make_engine(content)
        result = eng.start()
        assert "Loop" in result
        assert "Morale" in result

    def test_conversation_opens_and_closes(self, content):
        eng = make_engine(content)
        s = eng.state
        s.current_location_id = "waiting_room"

        eng.handle_input("talk to the veteran")
        assert s.current_conversation is not None
        assert s.current_conversation.is_active

        eng.handle_input("leave")
        assert s.current_conversation is None

    def test_conversation_uses_fallback_in_phase_3(self, content):
        eng = make_engine(content)
        s = eng.state
        s.current_location_id = "waiting_room"

        eng.handle_input("talk to the veteran")
        response = eng.handle_input("what do you know about workarounds")
        assert "You want my advice?" in response  # E-7 fallback line

    def test_npc_trust_survives_3_loops(self, content):
        eng = make_engine(content)
        s = eng.state
        s.npcs["e7"].relationship.trust = 3

        # Three resets
        for _ in range(3):
            from deers.clock import OFFICE_CLOSE_MINS
            s.clock.current_minutes = OFFICE_CLOSE_MINS - 1
            s.clock.advance(2)
            eng.state.trigger_reset()

        assert eng.state.npcs["e7"].relationship.trust == 3

    def test_impossible_combination_detection(self, content):
        eng = make_engine(content)
        s = eng.state
        s.deers.fields["dod_id"].is_corrupted = True
        s.deers.fields["clearance_level"].is_corrupted = True
        assert s.deers.has_impossible_combination()


class TestPhase8Mechanics:
    """End-to-end tests for Phase 8 mechanics."""

    def test_standard_win_via_submit(self, content):
        """Player can win by submitting documents that fix all blocking fields."""
        eng = make_engine(content)
        s = eng.state

        # Clear all corruption, set only last_name (ON_SITE, fixed by passport)
        for f in s.deers.fields.values():
            f.is_corrupted = False
        s.deers.fields["last_name"].is_corrupted = True
        s.current_location_id = "queue_window"
        s.queue_position = 0

        # Submit cleans last_name using passport
        result = eng.handle_input("submit documents")
        assert not s.deers.fields["last_name"].is_corrupted
        # CAC should be issued (TerminalCondition fires)
        assert "VICTORY" in result or "CAC" in result

    def test_workaround_win_via_payphone(self, content):
        """Player can win by using payphone with WORKAROUND_KNOWN."""
        eng = make_engine(content)
        s = eng.state
        s.permanent_knowledge.add("WORKAROUND_KNOWN")
        s.current_location_id = "waiting_room"

        result = eng.handle_input("use payphone")
        assert s.workaround_called
        assert "VICTORY" in result

    def test_workaround_win_without_knowledge_fails(self, content):
        """Payphone without WORKAROUND_KNOWN does NOT trigger win."""
        eng = make_engine(content)
        s = eng.state
        s.current_location_id = "waiting_room"
        assert "WORKAROUND_KNOWN" not in s.permanent_knowledge

        result = eng.handle_input("use payphone")
        assert not s.workaround_called
        assert "VICTORY" not in result

    def test_transcendence_win_full_path(self, content):
        """All three transcendence steps present → TRANSCENDENCE_UNLOCKED → win."""
        eng = make_engine(content)
        s = eng.state
        scheduler = ConditionScheduler(content)

        s.permanent_knowledge.add("IMPOSSIBLE_SEEN")
        s.permanent_knowledge.add("TRANSCENDENCE_STEP_1")
        s.permanent_knowledge.add("TRANSCENDENCE_STEP_2")
        s.permanent_knowledge.add("TRANSCENDENCE_UNLOCKED")

        result = scheduler.evaluate_all(s)
        assert result is not None
        assert result.kind == WinCondition.TRANSCENDENCE

    def test_transcendence_step2_awarded_on_fix(self, content):
        """Fixing a DEERS field via SUBMIT awards TRANSCENDENCE_STEP_2."""
        eng = make_engine(content)
        s = eng.state
        s.current_location_id = "queue_window"
        s.queue_position = 0
        for f in s.deers.fields.values():
            f.is_corrupted = False
        s.deers.fields["last_name"].is_corrupted = True

        eng.handle_input("submit documents")
        assert "TRANSCENDENCE_STEP_2" in s.permanent_knowledge

    def test_transcendence_unlocked_when_all_steps_present(self, content):
        """SUBMIT that fixes a field when IMPOSSIBLE_SEEN + STEP_1 present → TRANSCENDENCE_UNLOCKED."""
        eng = make_engine(content)
        s = eng.state
        s.permanent_knowledge.add("IMPOSSIBLE_SEEN")
        s.permanent_knowledge.add("TRANSCENDENCE_STEP_1")
        s.current_location_id = "queue_window"
        s.queue_position = 0
        for f in s.deers.fields.values():
            f.is_corrupted = False
        s.deers.fields["last_name"].is_corrupted = True

        eng.handle_input("submit documents")
        assert "TRANSCENDENCE_UNLOCKED" in s.permanent_knowledge

    def test_examine_deers_command(self, content):
        """EXAMINE DEERS shows record status."""
        eng = make_engine(content)
        result = eng.handle_input("examine deers")
        assert "DEERS" in result

    def test_endings_loaded_from_toml(self, content):
        """ConditionScheduler with content loads ending text from endings.toml."""
        from deers.conditions import ConditionScheduler as CS
        scheduler = CS(content)
        s = GameState.new_game("Test", content)
        s.current_location_id = "queue_window"
        s.queue_position = 0
        for f in s.deers.fields.values():
            f.is_corrupted = False

        result = scheduler.evaluate_all(s)
        assert result is not None
        # The TOML text has "CAC" in it
        assert "CAC" in result.message

    def test_submit_in_engine_full_flow(self, content):
        """Engine processes SUBMIT verb end-to-end without crashing."""
        eng = make_engine(content)
        s = eng.state
        s.current_location_id = "queue_window"
        s.queue_position = 0
        result = eng.handle_input("submit")
        assert isinstance(result, str)
        assert len(result) > 0


class TestPhase9Polish:
    """Tests for Phase 9: cold-start, voice, status display polish."""

    def test_cold_start_shows_intro(self, content):
        """Fresh game (loop 1) shows opening monologue in start()."""
        eng = make_engine(content)
        assert eng.state.loop_number == 1
        result = eng.start()
        assert "Monday" in result
        assert "CAC" in result
        assert "Friday" in result

    def test_cold_start_includes_orientation(self, content):
        """Cold start includes command orientation hints."""
        eng = make_engine(content)
        result = eng.start()
        assert "HELP" in result
        assert "EXAMINE DEERS" in result

    def test_no_intro_after_loop_reset(self, content):
        """After loop reset (loop >= 2), start() does not show the intro."""
        from deers.clock import OFFICE_CLOSE_MINS
        eng = make_engine(content)
        s = eng.state
        s.clock.current_minutes = OFFICE_CLOSE_MINS - 29
        eng.handle_input("wait")
        assert s.loop_number == 2
        result = eng.start()
        # Intro text starts with "Monday. 0845."
        assert "0845" not in result

    def test_status_shows_next_when_queue_zero(self, content):
        """STATUS and status line show 'NEXT' when queue_position is 0."""
        eng = make_engine(content)
        s = eng.state
        s.queue_position = 0
        status = eng.handle_input("status")
        assert "NEXT" in status

    def test_status_line_shows_next_when_queue_zero(self, content):
        """The inline status line also shows NEXT for queue=0."""
        eng = make_engine(content)
        s = eng.state
        s.queue_position = 0
        result = eng.start()
        assert "NEXT" in result

    def test_status_shows_blocking_corruptions(self, content):
        """STATUS highlights blocking DEERS corruptions separately."""
        eng = make_engine(content)
        s = eng.state
        for f in s.deers.fields.values():
            f.is_corrupted = False
        s.deers.fields["last_name"].is_corrupted = True
        status = eng.handle_input("status")
        assert "Blocking" in status or "blocking" in status.lower()

    def test_failure_messages_in_voice(self, content):
        """ResolutionFailure messages do not use casual contractions."""
        eng = make_engine(content)
        # These should all fail with in-voice messages
        fail_inputs = [
            "go narnia",
            "examine dragon",
            "take moon",
            "read newspaper",
            "drop invisible_thing",
        ]
        for inp in fail_inputs:
            result = eng.handle_input(inp)
            # Should not contain casual "There's" — use "There is" instead
            assert "There's" not in result, (
                f"Input '{inp}' produced casual contraction: {result!r}"
            )

    def test_unknown_verb_message_in_voice(self, content):
        """Unknown verbs (converted to EXAMINE by keyword parser) produce in-voice messages."""
        eng = make_engine(content)
        result = eng.handle_input("frobnicate everything")
        # Keyword parser maps unknown verbs to EXAMINE; should not use casual "doesn't"
        assert "doesn't" not in result
        assert len(result) > 0

    def test_is_game_over_false_at_start(self, content):
        """engine.is_game_over is False before any terminal condition fires."""
        eng = make_engine(content)
        assert not eng.is_game_over

    def test_is_game_over_true_after_win(self, content):
        """engine.is_game_over is True after a win condition fires."""
        eng = make_engine(content)
        s = eng.state
        s.current_location_id = "queue_window"
        s.queue_position = 0
        for f in s.deers.fields.values():
            f.is_corrupted = False
        eng.handle_input("wait")  # triggers evaluate_all post-action → standard win
        assert eng.is_game_over

    def test_is_game_over_true_after_lose(self, content):
        """engine.is_game_over is True after a lose condition fires."""
        eng = make_engine(content)
        s = eng.state
        s.morale.apply_delta(-1000)
        eng.handle_input("wait")
        assert eng.is_game_over

    def test_readme_exists(self):
        """README.md exists at project root."""
        from pathlib import Path
        readme = Path(__file__).parent.parent / "README.md"
        assert readme.exists(), "README.md not found at project root"
        text = readme.read_text()
        assert "CAC" in text
        assert "DEERS" in text
        assert len(text) > 500  # not empty
