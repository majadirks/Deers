"""Tests for ConditionScheduler — all win/lose conditions."""

import pytest
from deers.conditions import ConditionScheduler
from deers.content import load_all
from deers.models import LoseCondition, WinCondition
from deers.state import GameState


@pytest.fixture
def content():
    return load_all()


@pytest.fixture
def state(content):
    return GameState.new_game("TestPlayer", content)


@pytest.fixture
def scheduler():
    return ConditionScheduler()


class TestMoraleCollapse:
    def test_no_terminal_at_full_morale(self, scheduler, state):
        assert scheduler.evaluate_all(state) is None

    def test_fires_at_zero_morale(self, scheduler, state):
        state.morale.apply_delta(-1000)
        result = scheduler.evaluate_all(state)
        assert result is not None
        assert result.kind == LoseCondition.MORALE_COLLAPSE

    def test_coffee_reprieve_at_zero(self, scheduler, state):
        from deers.models import GameEvent
        state.morale.apply_delta(-1000)
        # Simulate having consumed coffee this loop
        e = GameEvent(event_type="coffee_consumed", loop_number=state.loop_number)
        state.event_log.append(e)
        result = scheduler.evaluate_all(state)
        assert result is None
        assert state.morale.current > 0  # Restored slightly


class TestStartDateMissed:
    def test_no_terminal_when_days_remain(self, scheduler, state):
        assert state.clock.days_until_monday > 0
        # Run only start_date check
        result = scheduler._check_start_date_missed(state)
        assert result is None

    def test_fires_on_monday(self, scheduler, state):
        state.clock.days_until_monday = 0
        result = scheduler._check_start_date_missed(state)
        assert result is not None
        assert result.kind == LoseCondition.START_DATE_MISSED


class TestTailgating:
    def test_no_terminal_normally(self, scheduler, state):
        result = scheduler._check_tailgating(state)
        assert result is None

    def test_fires_when_flag_set(self, scheduler, state):
        state.tailgating_detected = True
        result = scheduler._check_tailgating(state)
        assert result is not None
        assert result.kind == LoseCondition.TAILGATING

    def test_resets_flag_after_firing(self, scheduler, state):
        state.tailgating_detected = True
        scheduler._check_tailgating(state)
        assert not state.tailgating_detected


class TestCorrectedClerk:
    def test_no_terminal_normally(self, scheduler, state):
        result = scheduler._check_corrected_clerk(state)
        assert result is None

    def test_fires_when_flag_set(self, scheduler, state):
        state.corrected_clerk = True
        result = scheduler._check_corrected_clerk(state)
        assert result is not None
        assert result.kind == LoseCondition.CORRECTED_CLERK


class TestCACIssued:
    def test_no_win_at_parking_lot(self, scheduler, state):
        result = scheduler._check_cac_issued(state)
        assert result is None

    def test_no_win_at_window_without_queue_number(self, scheduler, state):
        state.current_location_id = "queue_window"
        state.queue_position = None
        # Clear all DEERS corruptions
        for f in state.deers.fields.values():
            f.is_corrupted = False
        result = scheduler._check_cac_issued(state)
        assert result is None

    def test_no_win_at_window_with_corruptions(self, scheduler, state):
        state.current_location_id = "queue_window"
        state.queue_position = 0
        # Ensure at least one blocking corruption
        state.deers.fields["last_name"].is_corrupted = True
        result = scheduler._check_cac_issued(state)
        assert result is None

    def test_wins_at_window_with_clean_deers(self, scheduler, state):
        state.current_location_id = "queue_window"
        state.queue_position = 0
        for f in state.deers.fields.values():
            f.is_corrupted = False
        result = scheduler._check_cac_issued(state)
        assert result is not None
        assert result.kind == WinCondition.STANDARD

    def test_wins_with_only_nonblocking_corruptions(self, scheduler, state):
        state.current_location_id = "queue_window"
        state.queue_position = 0
        for f in state.deers.fields.values():
            f.is_corrupted = False
        # Non-blocking corruptions should not block issuance
        state.deers.fields["component"].is_corrupted = True
        assert state.deers.is_issuable()
        result = scheduler._check_cac_issued(state)
        assert result is not None
        assert result.kind == WinCondition.STANDARD


class TestWorkaroundComplete:
    def test_no_win_without_knowledge(self, scheduler, state):
        state.workaround_called = True
        result = scheduler._check_workaround_complete(state)
        assert result is None

    def test_no_win_without_called_flag(self, scheduler, state):
        state.permanent_knowledge.add("WORKAROUND_KNOWN")
        result = scheduler._check_workaround_complete(state)
        assert result is None

    def test_wins_with_knowledge_and_flag(self, scheduler, state):
        state.permanent_knowledge.add("WORKAROUND_KNOWN")
        state.workaround_called = True
        result = scheduler._check_workaround_complete(state)
        assert result is not None
        assert result.kind == WinCondition.WORKAROUND


class TestTranscendence:
    def test_no_win_without_key(self, scheduler, state):
        result = scheduler._check_transcendence(state)
        assert result is None

    def test_wins_with_key(self, scheduler, state):
        state.permanent_knowledge.add("TRANSCENDENCE_UNLOCKED")
        result = scheduler._check_transcendence(state)
        assert result is not None
        assert result.kind == WinCondition.TRANSCENDENCE


class TestPriorityOrder:
    def test_lose_takes_priority_over_win(self, scheduler, state):
        """If both a lose and win condition are met simultaneously, lose wins."""
        # Set up win condition
        state.current_location_id = "queue_window"
        state.queue_position = 0
        for f in state.deers.fields.values():
            f.is_corrupted = False
        # Also set morale to zero (lose condition)
        state.morale.apply_delta(-1000)
        result = scheduler.evaluate_all(state)
        assert result is not None
        assert result.kind == LoseCondition.MORALE_COLLAPSE
