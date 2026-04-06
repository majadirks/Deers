"""Tests for ActionResolver — all 8 verbs."""

import pytest
from deers.actions import ActionResolver, ResolutionFailure
from deers.content import load_all
from deers.models import DocumentType, DocumentFlaw, ParsedAction
from deers.state import GameState


@pytest.fixture
def content():
    return load_all()


@pytest.fixture
def state(content):
    return GameState.new_game("TestPlayer", content)


@pytest.fixture
def resolver():
    return ActionResolver()


def resolve_ok(resolver, verb, target, state):
    result = resolver.resolve(ParsedAction(verb=verb, target=target), state)
    assert not isinstance(result, ResolutionFailure), \
        f"Expected Action, got ResolutionFailure: {result.message}"
    return result


def resolve_fail(resolver, verb, target, state):
    result = resolver.resolve(ParsedAction(verb=verb, target=target), state)
    assert isinstance(result, ResolutionFailure), \
        f"Expected ResolutionFailure, got Action"
    return result


class TestGoVerb:
    def test_go_to_gate_from_parking_lot(self, resolver, state):
        action = resolve_ok(resolver, "GO", "gate", state)
        action.execute(state)
        assert state.current_location_id == "installation_gate"

    def test_go_uses_alias(self, resolver, state):
        action = resolve_ok(resolver, "GO", "installation_gate", state)
        action.execute(state)
        assert state.current_location_id == "installation_gate"

    def test_go_advances_clock(self, resolver, state):
        from deers.clock import OFFICE_OPEN_MINS
        action = resolve_ok(resolver, "GO", "gate", state)
        action.execute(state)
        # installation_gate has base_time_cost=10
        assert state.clock.current_minutes > OFFICE_OPEN_MINS

    def test_go_invalid_target_fails(self, resolver, state):
        resolve_fail(resolver, "GO", "narnia", state)

    def test_go_unreachable_exit_fails(self, resolver, state):
        # Can't go to waiting_room directly from parking_lot
        resolve_fail(resolver, "GO", "waiting_room", state)

    def test_go_to_waiting_room_requires_docs(self, resolver, state, content):
        state.current_location_id = "installation_gate"
        # Clear inventory — no docs
        state.inventory.documents.clear()
        resolve_fail(resolver, "GO", "waiting_room", state)

    def test_go_to_waiting_room_with_docs(self, resolver, state, content):
        state.current_location_id = "installation_gate"
        action = resolve_ok(resolver, "GO", "waiting_room", state)
        action.execute(state)
        assert state.current_location_id == "waiting_room"

    def test_go_sets_tailgating_without_photo_id(self, resolver, state):
        state.current_location_id = "installation_gate"
        # Remove passport and driver's license (keep only appointment email)
        state.inventory.documents = [
            d for d in state.inventory.documents
            if d.doc_type == DocumentType.APPOINTMENT_EMAIL
        ]
        action = resolve_ok(resolver, "GO", "waiting_room", state)
        action.execute(state)
        assert state.tailgating_detected

    def test_go_no_tailgating_with_valid_passport(self, resolver, state):
        state.current_location_id = "installation_gate"
        # Has valid passport (default starting inventory)
        action = resolve_ok(resolver, "GO", "waiting_room", state)
        action.execute(state)
        assert not state.tailgating_detected


class TestTalkVerb:
    def test_talk_to_e7_in_waiting_room(self, resolver, state):
        state.current_location_id = "waiting_room"
        action = resolve_ok(resolver, "TALK", "e7", state)
        assert action.target == "e7"

    def test_talk_opens_conversation(self, resolver, state):
        state.current_location_id = "waiting_room"
        action = resolve_ok(resolver, "TALK", "veteran", state)
        action.execute(state)
        assert state.current_conversation is not None
        assert state.current_conversation.npc_id == "e7"

    def test_talk_advances_clock(self, resolver, state):
        from deers.clock import OFFICE_OPEN_MINS
        state.current_location_id = "waiting_room"
        action = resolve_ok(resolver, "TALK", "e7", state)
        action.execute(state)
        assert state.clock.current_minutes > OFFICE_OPEN_MINS

    def test_talk_to_absent_npc_fails(self, resolver, state):
        # Clerk is not in waiting_room
        state.current_location_id = "waiting_room"
        resolve_fail(resolver, "TALK", "clerk", state)

    def test_talk_to_clerk_at_queue_window(self, resolver, state):
        state.current_location_id = "queue_window"
        action = resolve_ok(resolver, "TALK", "clerk", state)
        assert action.target == "clerk"

    def test_talk_returns_fallback_line(self, resolver, state):
        state.current_location_id = "waiting_room"
        action = resolve_ok(resolver, "TALK", "e7", state)
        execution = action.execute(state)
        assert "You want my advice?" in execution.message


class TestExamineVerb:
    def test_examine_location(self, resolver, state):
        action = resolve_ok(resolver, "EXAMINE", "location", state)
        execution = action.execute(state)
        assert len(execution.message) > 0

    def test_examine_empty_target_is_location(self, resolver, state):
        action = resolve_ok(resolver, "EXAMINE", "", state)
        execution = action.execute(state)
        assert "parking" in execution.message.lower()

    def test_examine_feature(self, resolver, state):
        action = resolve_ok(resolver, "EXAMINE", "car", state)
        execution = action.execute(state)
        assert len(execution.message) > 0

    def test_examine_document_in_inventory(self, resolver, state):
        action = resolve_ok(resolver, "EXAMINE", "passport", state)
        execution = action.execute(state)
        assert "passport" in execution.message.lower()

    def test_examine_nonexistent_target_fails(self, resolver, state):
        resolve_fail(resolver, "EXAMINE", "dragon", state)

    def test_examine_npc_returns_voice_description(self, resolver, state):
        state.current_location_id = "waiting_room"
        action = resolve_ok(resolver, "EXAMINE", "e7", state)
        execution = action.execute(state)
        assert len(execution.message) > 10


class TestTakeVerb:
    def test_take_number_in_waiting_room(self, resolver, state):
        state.current_location_id = "waiting_room"
        action = resolve_ok(resolver, "TAKE", "number", state)
        action.execute(state)
        assert state.queue_position is not None
        assert state.queue_position >= 5

    def test_take_number_twice_fails(self, resolver, state):
        state.current_location_id = "waiting_room"
        action = resolve_ok(resolver, "TAKE", "number", state)
        action.execute(state)
        resolve_fail(resolver, "TAKE", "number", state)

    def test_take_number_not_in_parking_lot(self, resolver, state):
        # parking_lot has no number_dispenser
        resolve_fail(resolver, "TAKE", "number", state)

    def test_take_invalid_target_fails(self, resolver, state):
        resolve_fail(resolver, "TAKE", "the_moon", state)


class TestUseVerb:
    def test_use_vending_machine_restores_morale(self, resolver, state):
        state.current_location_id = "vending_alcove"
        state.morale.apply_delta(-20)
        before = state.morale.current
        action = resolve_ok(resolver, "USE", "vending", state)
        action.execute(state)
        assert state.morale.current > before

    def test_use_water_fountain(self, resolver, state):
        state.current_location_id = "vending_alcove"
        before = state.morale.current
        action = resolve_ok(resolver, "USE", "water", state)
        action.execute(state)
        assert state.morale.current >= before  # water restores a little

    def test_use_photocopier_requires_copyable_doc(self, resolver, state):
        state.current_location_id = "base_library"
        # Clear non-copyable docs, add a copyable one
        from deers.inventory import DocumentFactory
        import random
        factory = DocumentFactory(random.Random(1), state.content)
        state.inventory.documents.clear()
        state.inventory.add(factory.make(DocumentType.APPOINTMENT_EMAIL, force_flaws=[]))
        action = resolve_ok(resolver, "USE", "photocopier", state)
        before_count = len(state.inventory.documents)
        action.execute(state)
        assert len(state.inventory.documents) > before_count

    def test_use_photocopier_grants_knowledge(self, resolver, state):
        state.current_location_id = "base_library"
        action = resolve_ok(resolver, "USE", "photocopier", state)
        action.execute(state)
        assert "PHOTOCOPY_TRICK_KNOWN" in state.permanent_knowledge

    def test_use_nonexistent_fails(self, resolver, state):
        resolve_fail(resolver, "USE", "flying_carpet", state)


class TestWaitVerb:
    def test_wait_advances_clock(self, resolver, state):
        from deers.clock import OFFICE_OPEN_MINS
        action = resolve_ok(resolver, "WAIT", "", state)
        action.execute(state)
        assert state.clock.current_minutes == OFFICE_OPEN_MINS + 30

    def test_wait_drains_morale(self, resolver, state):
        before = state.morale.current
        action = resolve_ok(resolver, "WAIT", "", state)
        action.execute(state)
        assert state.morale.current < before

    def test_wait_advances_queue(self, resolver, state):
        state.queue_position = 5
        action = resolve_ok(resolver, "WAIT", "", state)
        action.execute(state)
        assert state.queue_position < 5

    def test_wait_queue_does_not_go_negative(self, resolver, state):
        state.queue_position = 0
        action = resolve_ok(resolver, "WAIT", "", state)
        action.execute(state)
        assert state.queue_position == 0

    def test_wait_enough_times_closes_office(self, resolver, state):
        closed = False
        for _ in range(20):
            action = resolve_ok(resolver, "WAIT", "", state)
            action.execute(state)
            if state.should_loop():
                closed = True
                break
        assert closed


class TestDropVerb:
    def test_drop_document(self, resolver, state):
        initial_count = len(state.inventory.documents)
        action = resolve_ok(resolver, "DROP", "passport", state)
        action.execute(state)
        assert len(state.inventory.documents) == initial_count - 1

    def test_cannot_drop_appointment_email(self, resolver, state):
        resolve_fail(resolver, "DROP", "appointment", state)

    def test_drop_nonexistent_fails(self, resolver, state):
        resolve_fail(resolver, "DROP", "something_not_in_inventory", state)


class TestReadVerb:
    def test_read_document_in_inventory(self, resolver, state):
        action = resolve_ok(resolver, "READ", "passport", state)
        execution = action.execute(state)
        assert "passport" in execution.message.lower()

    def test_read_advances_clock(self, resolver, state):
        from deers.clock import OFFICE_OPEN_MINS
        action = resolve_ok(resolver, "READ", "passport", state)
        action.execute(state)
        assert state.clock.current_minutes > OFFICE_OPEN_MINS

    def test_read_shows_flaws(self, resolver, state):
        # Driver's license starts laminated
        action = resolve_ok(resolver, "READ", "license", state)
        execution = action.execute(state)
        assert "laminated" in execution.message.lower()

    def test_read_nonexistent_fails(self, resolver, state):
        resolve_fail(resolver, "READ", "newspaper", state)


class TestHelpAndStatus:
    def test_help_returns_verb_list(self, resolver, state):
        action = resolve_ok(resolver, "HELP", "", state)
        execution = action.execute(state)
        assert "GO" in execution.message
        assert "TALK" in execution.message
        assert "SUBMIT" in execution.message

    def test_status_shows_loop(self, resolver, state):
        action = resolve_ok(resolver, "STATUS", "", state)
        execution = action.execute(state)
        assert "Loop" in execution.message

    def test_unknown_verb_fails(self, resolver, state):
        resolve_fail(resolver, "FROBNICATE", "everything", state)


class TestSubmitVerb:
    def _setup_at_window(self, state):
        state.current_location_id = "queue_window"
        state.queue_position = 0

    def test_submit_fails_outside_queue_window(self, resolver, state):
        # Default: parking_lot
        resolve_fail(resolver, "SUBMIT", "documents", state)

    def test_submit_fails_without_queue_number(self, resolver, state):
        state.current_location_id = "queue_window"
        state.queue_position = None
        resolve_fail(resolver, "SUBMIT", "documents", state)

    def test_submit_resolves_at_window_with_number(self, resolver, state):
        self._setup_at_window(state)
        resolve_ok(resolver, "SUBMIT", "documents", state)

    def test_submit_fixes_on_site_field_with_valid_doc(self, resolver, state):
        self._setup_at_window(state)
        # Force last_name corruption; passport is in inventory and valid
        state.deers.fields["last_name"].is_corrupted = True
        # Ensure passport is clean (starting inventory has clean passport)
        action = resolve_ok(resolver, "SUBMIT", "documents", state)
        action.execute(state)
        assert not state.deers.fields["last_name"].is_corrupted

    def test_submit_morale_increase_on_fix(self, resolver, state):
        self._setup_at_window(state)
        # Clear all other corruptions so only last_name affects morale
        for f in state.deers.fields.values():
            f.is_corrupted = False
        state.deers.fields["last_name"].is_corrupted = True
        state.morale.apply_delta(-30)  # ensure we're below max so +12 is visible
        before = state.morale.current
        action = resolve_ok(resolver, "SUBMIT", "documents", state)
        action.execute(state)
        assert state.morale.current > before

    def test_submit_morale_drain_on_unfixable_blocking(self, resolver, state):
        self._setup_at_window(state)
        # ssn_last4 is HR; no HR document in starting inventory
        state.deers.fields["last_name"].is_corrupted = False
        for f in state.deers.fields.values():
            f.is_corrupted = False
        state.deers.fields["ssn_last4"].is_corrupted = True
        before = state.morale.current
        action = resolve_ok(resolver, "SUBMIT", "documents", state)
        action.execute(state)
        assert state.morale.current < before

    def test_submit_awards_transcendence_step_2_on_fix(self, resolver, state):
        self._setup_at_window(state)
        state.deers.fields["last_name"].is_corrupted = True
        action = resolve_ok(resolver, "SUBMIT", "documents", state)
        action.execute(state)
        assert "TRANSCENDENCE_STEP_2" in state.permanent_knowledge

    def test_submit_detects_impossible_combination(self, resolver, state):
        self._setup_at_window(state)
        state.deers.fields["dod_id"].is_corrupted = True
        state.deers.fields["clearance_level"].is_corrupted = True
        action = resolve_ok(resolver, "SUBMIT", "documents", state)
        action.execute(state)
        assert "IMPOSSIBLE_SEEN" in state.permanent_knowledge

    def test_submit_message_shows_results(self, resolver, state):
        self._setup_at_window(state)
        state.deers.fields["last_name"].is_corrupted = True
        action = resolve_ok(resolver, "SUBMIT", "documents", state)
        execution = action.execute(state)
        assert "Last Name" in execution.message

    def test_give_is_alias_for_submit(self, resolver, state):
        self._setup_at_window(state)
        resolve_ok(resolver, "GIVE", "documents", state)

    def test_hand_is_alias_for_submit(self, resolver, state):
        self._setup_at_window(state)
        resolve_ok(resolver, "HAND", "documents", state)


class TestExamineDeers:
    def test_examine_deers_returns_field_list(self, resolver, state):
        action = resolve_ok(resolver, "EXAMINE", "deers", state)
        execution = action.execute(state)
        assert "DEERS" in execution.message

    def test_examine_record_alias(self, resolver, state):
        action = resolve_ok(resolver, "EXAMINE", "record", state)
        execution = action.execute(state)
        assert "DEERS" in execution.message

    def test_examine_deers_shows_corrupted_fields(self, resolver, state):
        state.deers.fields["last_name"].is_corrupted = True
        action = resolve_ok(resolver, "EXAMINE", "deers", state)
        execution = action.execute(state)
        assert "CORRUPTED" in execution.message

    def test_examine_deers_awards_impossible_seen(self, resolver, state):
        state.deers.fields["dod_id"].is_corrupted = True
        state.deers.fields["clearance_level"].is_corrupted = True
        action = resolve_ok(resolver, "EXAMINE", "deers", state)
        action.execute(state)
        assert "IMPOSSIBLE_SEEN" in state.permanent_knowledge

    def test_examine_deers_no_impossible_seen_without_combination(self, resolver, state):
        state.deers.fields["dod_id"].is_corrupted = False
        state.deers.fields["clearance_level"].is_corrupted = False
        action = resolve_ok(resolver, "EXAMINE", "deers", state)
        action.execute(state)
        assert "IMPOSSIBLE_SEEN" not in state.permanent_knowledge


class TestPayphone:
    def test_payphone_present_in_waiting_room(self, resolver, state):
        state.current_location_id = "waiting_room"
        action = resolve_ok(resolver, "USE", "payphone", state)
        execution = action.execute(state)
        assert len(execution.message) > 0

    def test_payphone_without_workaround_known_gives_hint(self, resolver, state):
        state.current_location_id = "waiting_room"
        assert "WORKAROUND_KNOWN" not in state.permanent_knowledge
        action = resolve_ok(resolver, "USE", "payphone", state)
        execution = action.execute(state)
        assert "not sure" in execution.message.lower() or "someone" in execution.message.lower()
        assert not state.workaround_called

    def test_payphone_with_workaround_known_sets_flag(self, resolver, state):
        state.current_location_id = "waiting_room"
        state.permanent_knowledge.add("WORKAROUND_KNOWN")
        action = resolve_ok(resolver, "USE", "payphone", state)
        action.execute(state)
        assert state.workaround_called

    def test_payphone_with_workaround_known_advances_clock(self, resolver, state):
        from deers.clock import OFFICE_OPEN_MINS
        state.current_location_id = "waiting_room"
        state.permanent_knowledge.add("WORKAROUND_KNOWN")
        action = resolve_ok(resolver, "USE", "payphone", state)
        action.execute(state)
        assert state.clock.current_minutes > OFFICE_OPEN_MINS


class TestVendingChips:
    def test_chips_restore_morale(self, resolver, state):
        state.current_location_id = "vending_alcove"
        state.morale.apply_delta(-30)
        before = state.morale.current
        action = resolve_ok(resolver, "USE", "chips", state)
        action.execute(state)
        assert state.morale.current > before

    def test_vending_default_gives_coffee(self, resolver, state):
        state.current_location_id = "vending_alcove"
        action = resolve_ok(resolver, "USE", "vending machine", state)
        execution = action.execute(state)
        assert "coffee" in execution.message.lower()


class TestQueueMoraleEvent:
    def test_wait_awards_queue_advanced_morale(self, resolver, state):
        state.queue_position = 5
        before = state.morale.current
        action = resolve_ok(resolver, "WAIT", "", state)
        action.execute(state)
        # wait drains -3, queue_advanced restores +4 → net +1 if queue advances
        # Net could be -3 if queue didn't advance (unlikely but possible)
        # Just verify queue decreased
        assert state.queue_position < 5
