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
