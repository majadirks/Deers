"""Tests for GameState."""

import pytest
from deers.content import load_all
from deers.models import DocumentType
from deers.state import GameState


@pytest.fixture
def content():
    return load_all()


@pytest.fixture
def state(content):
    return GameState.new_game("TestPlayer", content)


class TestGameStateInit:
    def test_starts_at_loop_1(self, state):
        assert state.loop_number == 1

    def test_starts_at_parking_lot(self, state):
        assert state.current_location_id == "parking_lot"

    def test_starting_inventory_has_3_docs(self, state):
        assert len(state.inventory.documents) == 3

    def test_starting_inventory_has_appointment_email(self, state):
        assert state.inventory.has(DocumentType.APPOINTMENT_EMAIL)

    def test_starting_inventory_has_passport(self, state):
        assert state.inventory.has(DocumentType.PASSPORT)

    def test_starting_passport_is_valid(self, state):
        assert state.inventory.has_valid(DocumentType.PASSPORT)

    def test_starting_drivers_license_is_invalid(self, state):
        # Starts laminated — blocking flaw
        assert state.inventory.has(DocumentType.DRIVERS_LICENSE)
        assert not state.inventory.has_valid(DocumentType.DRIVERS_LICENSE)

    def test_deers_has_corruptions(self, state):
        assert len(state.deers.corrupted_fields()) >= 1

    def test_loop_1_deers_has_3_corruptions(self, state):
        assert len(state.deers.corrupted_fields()) >= 3

    def test_all_7_locations_present(self, state):
        assert len(state.locations) == 7

    def test_all_5_npcs_present(self, state):
        assert len(state.npcs) == 5

    def test_queue_position_starts_none(self, state):
        assert state.queue_position is None


class TestTriggerReset:
    def test_increments_loop_number(self, state):
        state.trigger_reset()
        assert state.loop_number == 2

    def test_resets_to_parking_lot(self, state):
        state.current_location_id = "waiting_room"
        state.trigger_reset()
        assert state.current_location_id == "parking_lot"

    def test_resets_clock(self, state):
        state.clock.advance(300)
        state.trigger_reset()
        from deers.clock import OFFICE_OPEN_MINS
        assert state.clock.current_minutes == OFFICE_OPEN_MINS

    def test_resets_morale(self, state):
        state.morale.apply_delta(-50)
        state.trigger_reset()
        assert state.morale.percentage() == 100

    def test_resets_queue_position(self, state):
        state.queue_position = 5
        state.trigger_reset()
        assert state.queue_position is None

    def test_generates_new_deers_record(self, state):
        old_corruptions = {f.name for f in state.deers.corrupted_fields()}
        # Loop 2 with no knowledge may produce same or different corruptions
        # At minimum it should generate a valid record
        state.trigger_reset()
        assert len(state.deers.corrupted_fields()) >= 1

    def test_permanent_knowledge_survives(self, state):
        state.permanent_knowledge.add("WORKAROUND_KNOWN")
        state.trigger_reset()
        assert "WORKAROUND_KNOWN" in state.permanent_knowledge

    def test_permanent_npc_trust_survives(self, state):
        state.npcs["e7"].relationship.trust = 3
        state.trigger_reset()
        assert state.npcs["e7"].relationship.trust == 3

    def test_non_permanent_npc_trust_resets(self, state):
        state.npcs["clerk"].relationship.trust = 2
        state.trigger_reset()
        assert state.npcs["clerk"].relationship.trust == 0

    def test_rebuilds_inventory(self, state):
        # Drop everything, reset, should have fresh inventory
        state.inventory.documents.clear()
        state.trigger_reset()
        assert len(state.inventory.documents) == 3

    def test_resets_lose_flags(self, state):
        state.tailgating_detected = True
        state.corrected_clerk = True
        state.trigger_reset()
        assert not state.tailgating_detected
        assert not state.corrected_clerk


class TestSerializationRoundTrip:
    def test_round_trip_preserves_player_name(self, state, content):
        d = state.to_dict()
        s2 = GameState.from_dict(d, content)
        assert s2.player_name == "TestPlayer"

    def test_round_trip_preserves_loop_number(self, state, content):
        state.trigger_reset()  # loop 2
        d = state.to_dict()
        s2 = GameState.from_dict(d, content)
        assert s2.loop_number == 2

    def test_round_trip_preserves_permanent_knowledge(self, state, content):
        state.permanent_knowledge.add("WORKAROUND_KNOWN")
        state.permanent_knowledge.add("LIBRARY_LOCATION_KNOWN")
        d = state.to_dict()
        s2 = GameState.from_dict(d, content)
        assert "WORKAROUND_KNOWN" in s2.permanent_knowledge
        assert "LIBRARY_LOCATION_KNOWN" in s2.permanent_knowledge

    def test_round_trip_preserves_e7_trust(self, state, content):
        state.npcs["e7"].relationship.trust = 4
        d = state.to_dict()
        s2 = GameState.from_dict(d, content)
        assert s2.npcs["e7"].relationship.trust == 4

    def test_round_trip_starts_at_parking_lot(self, state, content):
        state.current_location_id = "waiting_room"
        d = state.to_dict()
        s2 = GameState.from_dict(d, content)
        assert s2.current_location_id == "parking_lot"

    def test_save_version_is_v1(self, state):
        assert state.to_dict()["save_version"] == "v1"

    def test_round_trip_has_correct_locations(self, state, content):
        d = state.to_dict()
        s2 = GameState.from_dict(d, content)
        assert len(s2.locations) == 7


class TestShouldLoop:
    def test_false_at_start(self, state):
        assert not state.should_loop()

    def test_true_when_office_closed(self, state):
        from deers.clock import OFFICE_CLOSE_MINS
        state.clock.current_minutes = OFFICE_CLOSE_MINS
        assert state.should_loop()
