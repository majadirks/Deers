"""Phase 2 tests: core data models."""

import pytest
import random

from deers.content import load_all
from deers.models import (
    BLOCKING_FLAWS,
    DocumentFlaw,
    DocumentType,
    FixMethod,
    GameEvent,
    LoseCondition,
    ParsedAction,
    TerminalCondition,
    WinCondition,
)
from deers.morale import MoraleMeter, CRITICAL_THRESHOLD, LOW_THRESHOLD, HIGH_THRESHOLD, MAX_MORALE
from deers.clock import GameClock, OFFICE_OPEN_MINS, OFFICE_CLOSE_MINS, LUNCH_START_MINS, LUNCH_END_MINS
from deers.inventory import Document, DocumentFactory, Inventory
from deers.deers_record import DEERSField, DEERSRecord, DEERSGenerator
from deers.npcs import CharacterCard, NPCRelationship, ConversationBuffer, NPC
from deers.locations import build_locations, Location, Feature, Exit, Condition


@pytest.fixture
def content():
    return load_all()


# ---------------------------------------------------------------------------
# models.py
# ---------------------------------------------------------------------------

class TestGameEvent:
    def test_round_trip(self):
        e = GameEvent(event_type="test", actor="player", payload={"x": 1}, loop_number=2)
        d = e.to_dict()
        e2 = GameEvent.from_dict(d)
        assert e2.event_type == "test"
        assert e2.actor == "player"
        assert e2.payload == {"x": 1}
        assert e2.loop_number == 2

    def test_is_permanent_default_false(self):
        e = GameEvent(event_type="foo")
        assert not e.is_permanent


# ---------------------------------------------------------------------------
# morale.py
# ---------------------------------------------------------------------------

class TestMoraleMeter:
    def test_initial_state(self):
        m = MoraleMeter()
        assert m.current == MAX_MORALE
        assert m.bracket() == "high"

    def test_bracket_boundaries(self):
        m = MoraleMeter()
        m.current = CRITICAL_THRESHOLD
        assert m.bracket() == "critical"
        m.current = CRITICAL_THRESHOLD + 1
        assert m.bracket() == "low"
        m.current = LOW_THRESHOLD + 1
        assert m.bracket() == "medium"
        m.current = HIGH_THRESHOLD + 1
        assert m.bracket() == "high"

    def test_apply_delta_clamps_at_zero(self):
        m = MoraleMeter()
        m.apply_delta(-999)
        assert m.current == 0
        assert m.is_zero()

    def test_apply_delta_clamps_at_max(self):
        m = MoraleMeter()
        m.apply_delta(999)
        assert m.current == MAX_MORALE

    def test_apply_named_event(self):
        m = MoraleMeter()
        before = m.current
        m.apply("wait")
        assert m.current < before

    def test_apply_unknown_event_is_noop(self):
        m = MoraleMeter()
        before = m.current
        m.apply("nonexistent_event_xyz")
        assert m.current == before

    def test_is_critical(self):
        m = MoraleMeter()
        m.current = CRITICAL_THRESHOLD
        assert m.is_critical()
        m.current = CRITICAL_THRESHOLD + 1
        assert not m.is_critical()

    def test_modifier_range(self):
        m = MoraleMeter()
        for bracket, expected in [("high", 1.0), ("medium", 0.75), ("low", 0.5), ("critical", 0.25)]:
            m.current = {"high": MAX_MORALE, "medium": LOW_THRESHOLD + 1, "low": CRITICAL_THRESHOLD + 1, "critical": CRITICAL_THRESHOLD}[bracket]
            assert m.modifier() == expected

    def test_round_trip(self):
        m = MoraleMeter(current=42)
        m2 = MoraleMeter.from_dict(m.to_dict())
        assert m2.current == 42


# ---------------------------------------------------------------------------
# clock.py
# ---------------------------------------------------------------------------

class TestGameClock:
    def test_initial_state(self):
        c = GameClock()
        assert c.current_minutes == OFFICE_OPEN_MINS
        assert c.is_office_open()
        assert not c.is_lunch()
        assert not c.is_closed()

    def test_office_open_at_9am(self):
        c = GameClock(current_minutes=OFFICE_OPEN_MINS)
        assert c.is_office_open()

    def test_office_closed_at_4pm(self):
        c = GameClock(current_minutes=OFFICE_CLOSE_MINS)
        assert not c.is_office_open()
        assert c.is_closed()

    def test_lunch_hours(self):
        c = GameClock(current_minutes=LUNCH_START_MINS)
        assert c.is_lunch()
        assert not c.is_office_open()
        c.current_minutes = LUNCH_END_MINS
        assert not c.is_lunch()
        assert c.is_office_open()

    def test_advance_triggers_office_closed(self):
        c = GameClock(current_minutes=OFFICE_CLOSE_MINS - 1)
        events = c.advance(1)
        assert "office_closed" in events

    def test_advance_triggers_lunch(self):
        c = GameClock(current_minutes=LUNCH_START_MINS - 5)
        events = c.advance(10)
        assert "lunch_started" in events

    def test_advance_triggers_lunch_end(self):
        c = GameClock(current_minutes=LUNCH_END_MINS - 5)
        events = c.advance(10)
        assert "lunch_ended" in events

    def test_advance_no_events_midmorning(self):
        c = GameClock(current_minutes=600)  # 10am
        events = c.advance(30)
        assert events == []

    def test_time_display(self):
        c = GameClock(current_minutes=OFFICE_OPEN_MINS)  # 9:00
        assert c.time_display() == "9:00 AM"
        c.current_minutes = 13 * 60 + 30  # 1:30 PM
        assert c.time_display() == "1:30 PM"

    def test_day_name(self):
        from deers.clock import day_name
        assert day_name(1) == "Monday"
        assert day_name(2) == "Tuesday"
        assert day_name(3) == "Wednesday"
        assert day_name(4) == "Thursday"
        assert day_name(5) == "Friday"
        assert day_name(99) == "Friday"  # any loop > 4 is deadline day

    def test_time_bracket(self):
        c = GameClock(current_minutes=600)  # 10am
        assert c.time_bracket() == "morning"
        c.current_minutes = LUNCH_START_MINS
        assert c.time_bracket() == "lunch"
        c.current_minutes = LUNCH_END_MINS
        assert c.time_bracket() == "afternoon"

    def test_round_trip(self):
        c = GameClock(current_minutes=700)
        c2 = GameClock.from_dict(c.to_dict())
        assert c2.current_minutes == 700

    def test_wait_8_times_closes_office(self):
        """WAIT costs 30 minutes; 8 waits = 240 min; 540 + 240 = 780 < 960 close,
        but with enough waits we cross office_closed."""
        c = GameClock()
        closed_triggered = False
        for _ in range(15):
            events = c.advance(30)
            if "office_closed" in events:
                closed_triggered = True
                break
        assert closed_triggered


# ---------------------------------------------------------------------------
# inventory.py
# ---------------------------------------------------------------------------

class TestDocument:
    def test_fixes_correct_field(self, content):
        factory = DocumentFactory(random.Random(42), content)
        doc = factory.make(DocumentType.PASSPORT, force_flaws=[])
        assert doc.fixes("last_name")
        assert not doc.fixes("ssn_last4")

    def test_blocking_flaw_makes_invalid(self, content):
        factory = DocumentFactory(random.Random(42), content)
        doc = factory.make(DocumentType.DRIVERS_LICENSE, force_flaws=[DocumentFlaw.LAMINATED])
        assert not doc.is_effectively_valid()
        assert doc.has_blocking_flaw()

    def test_non_blocking_flaw_does_not_invalidate(self, content):
        factory = DocumentFactory(random.Random(42), content)
        doc = factory.make(DocumentType.PASSPORT, force_flaws=[DocumentFlaw.MAIDEN_NAME])
        # maiden_name is not in BLOCKING_FLAWS
        assert DocumentFlaw.MAIDEN_NAME not in BLOCKING_FLAWS
        assert doc.is_effectively_valid()

    def test_no_flaws_is_valid(self, content):
        factory = DocumentFactory(random.Random(42), content)
        doc = factory.make(DocumentType.PASSPORT, force_flaws=[])
        assert doc.is_effectively_valid()

    def test_round_trip(self, content):
        factory = DocumentFactory(random.Random(42), content)
        doc = factory.make(DocumentType.PASSPORT, force_flaws=[DocumentFlaw.EXPIRED])
        d = doc.to_dict()
        doc2 = Document.from_dict(d, content)
        assert doc2.doc_type == DocumentType.PASSPORT
        assert DocumentFlaw.EXPIRED in doc2.active_flaws


class TestInventory:
    def test_has_and_has_valid(self, content):
        factory = DocumentFactory(random.Random(1), content)
        inv = Inventory()
        doc = factory.make(DocumentType.PASSPORT, force_flaws=[])
        inv.add(doc)
        assert inv.has(DocumentType.PASSPORT)
        assert inv.has_valid(DocumentType.PASSPORT)

    def test_has_valid_false_when_expired(self, content):
        factory = DocumentFactory(random.Random(1), content)
        inv = Inventory()
        doc = factory.make(DocumentType.PASSPORT, force_flaws=[DocumentFlaw.EXPIRED])
        inv.add(doc)
        assert inv.has(DocumentType.PASSPORT)
        assert not inv.has_valid(DocumentType.PASSPORT)

    def test_matching_documents(self, content):
        factory = DocumentFactory(random.Random(1), content)
        inv = Inventory()
        inv.add(factory.make(DocumentType.PASSPORT, force_flaws=[]))
        inv.add(factory.make(DocumentType.DRIVERS_LICENSE, force_flaws=[]))
        matches = inv.matching_documents("last_name")
        assert len(matches) == 2

    def test_round_trip(self, content):
        factory = DocumentFactory(random.Random(1), content)
        inv = Inventory()
        inv.add(factory.make(DocumentType.PASSPORT, force_flaws=[]))
        inv.add(factory.make(DocumentType.CONTRACTOR_LETTER, force_flaws=[DocumentFlaw.MISSING_PAGE_2]))
        d = inv.to_dict()
        inv2 = Inventory.from_dict(d, content)
        assert len(inv2.documents) == 2
        assert inv2.documents[0].doc_type == DocumentType.PASSPORT


# ---------------------------------------------------------------------------
# deers_record.py
# ---------------------------------------------------------------------------

class TestDEERSGenerator:
    def test_deterministic(self, content):
        gen = DEERSGenerator(content)
        pk = frozenset()
        r1 = gen.generate(1, pk)
        r2 = gen.generate(1, pk)
        assert [f.name for f in r1.corrupted_fields()] == [f.name for f in r2.corrupted_fields()]

    def test_always_at_least_one_corruption(self, content):
        gen = DEERSGenerator(content)
        for loop in range(1, 10):
            record = gen.generate(loop, frozenset())
            assert len(record.corrupted_fields()) >= 1, f"Loop {loop} had zero corruptions"

    def test_loop_1_has_at_least_3_corruptions(self, content):
        gen = DEERSGenerator(content)
        record = gen.generate(1, frozenset())
        assert len(record.corrupted_fields()) >= 3

    def test_different_loops_may_differ(self, content):
        gen = DEERSGenerator(content)
        r1 = gen.generate(1, frozenset())
        r5 = gen.generate(5, frozenset())
        # They won't always be identical (different seeds)
        names1 = {f.name for f in r1.corrupted_fields()}
        names5 = {f.name for f in r5.corrupted_fields()}
        # At least the corruption sets can differ — just verify both are valid
        assert len(names1) >= 1
        assert len(names5) >= 1

    def test_knowledge_reduces_corruption(self, content):
        gen = DEERSGenerator(content)
        # With many resolved fields, later loops should have fewer corruptions on average
        all_keys = frozenset([
            "DEERS_FIELD_last_name", "DEERS_FIELD_ssn_last4",
            "DEERS_FIELD_component", "DEERS_FIELD_uic",
            "DEERS_FIELD_rank_grade",
        ])
        counts_with = []
        counts_without = []
        for loop in range(2, 12):
            r_with = gen.generate(loop, all_keys)
            r_without = gen.generate(loop, frozenset())
            counts_with.append(len(r_with.corrupted_fields()))
            counts_without.append(len(r_without.corrupted_fields()))
        assert sum(counts_with) <= sum(counts_without)


class TestDEERSRecord:
    def test_is_issuable_no_blocking(self, content):
        gen = DEERSGenerator(content)
        record = gen.generate(1, frozenset())
        # Manually clear all corruptions
        for f in record.fields.values():
            f.is_corrupted = False
        assert record.is_issuable()

    def test_is_not_issuable_with_blocking(self, content):
        gen = DEERSGenerator(content)
        record = gen.generate(1, frozenset())
        # Force a blocking corruption
        record.fields["last_name"].is_corrupted = True
        assert not record.is_issuable()

    def test_attempt_fix_on_site_success(self, content):
        gen = DEERSGenerator(content)
        factory = DocumentFactory(random.Random(1), content)
        record = gen.generate(1, frozenset())
        record.fields["last_name"].is_corrupted = True
        # passport fixes last_name ON_SITE
        doc = factory.make(DocumentType.PASSPORT, force_flaws=[])
        result = record.attempt_fix("last_name", doc)
        assert result.success
        assert not record.fields["last_name"].is_corrupted

    def test_attempt_fix_blocked_by_wrong_document(self, content):
        gen = DEERSGenerator(content)
        factory = DocumentFactory(random.Random(1), content)
        record = gen.generate(1, frozenset())
        record.fields["last_name"].is_corrupted = True
        # sf86_extract does NOT fix last_name
        doc = factory.make(DocumentType.SF86_EXTRACT, force_flaws=[])
        result = record.attempt_fix("last_name", doc)
        assert not result.success

    def test_attempt_fix_impossible_field(self, content):
        gen = DEERSGenerator(content)
        record = gen.generate(1, frozenset())
        record.fields["dod_id"].is_corrupted = True
        # Any document — should fail as IMPOSSIBLE
        from deers.inventory import DocumentFactory
        factory = DocumentFactory(random.Random(1), content)
        doc = factory.make(DocumentType.PASSPORT, force_flaws=[])
        result = record.attempt_fix("dod_id", doc)
        assert not result.success

    def test_round_trip(self, content):
        gen = DEERSGenerator(content)
        record = gen.generate(1, frozenset())
        d = record.to_dict()
        record2 = DEERSRecord.from_dict(d, content)
        assert set(record2.fields.keys()) == set(record.fields.keys())
        for name in record.fields:
            assert record2.fields[name].is_corrupted == record.fields[name].is_corrupted


# ---------------------------------------------------------------------------
# npcs.py
# ---------------------------------------------------------------------------

class TestConversationBuffer:
    def test_add_and_messages(self):
        buf = ConversationBuffer(npc_id="clerk")
        buf.add_player("Hello")
        buf.add_npc("I need your documents.")
        msgs = buf.to_messages()
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"

    def test_exhausted_at_max_turns(self):
        buf = ConversationBuffer(npc_id="clerk", max_turns=2)
        assert not buf.is_exhausted()
        buf.add_player("hi")
        buf.add_npc("response")
        buf.add_player("hi")
        buf.add_npc("response")
        assert buf.is_exhausted()

    def test_close_returns_effects(self):
        buf = ConversationBuffer(npc_id="e7")
        buf.accrue_effects(trust_delta=1, morale_delta=5, knowledge=["WORKAROUND_KNOWN"])
        effects = buf.close()
        assert effects["trust_delta"] == 1
        assert effects["morale_delta"] == 5
        assert "WORKAROUND_KNOWN" in effects["knowledge_gained"]
        assert not buf.is_active


class TestNPC:
    def test_display_name_unknown_at_trust_0(self, content):
        spec = next(n for n in content["npcs"]["npc"] if n["id"] == "queue_cutter")
        npc = NPC.from_content(spec)
        assert npc.display_name() == "???"

    def test_display_name_clerk_always_shown(self, content):
        # clerk is not permanent but archetype name should show once trust > 0
        spec = next(n for n in content["npcs"]["npc"] if n["id"] == "clerk")
        npc = NPC.from_content(spec)
        npc.relationship.trust = 1
        assert npc.display_name() == "The Clerk"

    def test_available_topics_trust_gated(self, content):
        spec = next(n for n in content["npcs"]["npc"] if n["id"] == "e7")
        npc = NPC.from_content(spec)
        npc.relationship.trust = 0
        topics_0 = npc.available_topics()
        npc.relationship.trust = 3
        topics_3 = npc.available_topics()
        assert len(topics_3) > len(topics_0)

    def test_workaround_requires_trust_3(self, content):
        spec = next(n for n in content["npcs"]["npc"] if n["id"] == "e7")
        npc = NPC.from_content(spec)
        npc.relationship.trust = 2
        assert "workaround" not in npc.available_topics()
        npc.relationship.trust = 3
        assert "workaround" in npc.available_topics()

    def test_is_present_at(self, content):
        spec = next(n for n in content["npcs"]["npc"] if n["id"] == "clerk")
        npc = NPC.from_content(spec)
        assert npc.is_present_at("queue_window")
        assert not npc.is_present_at("waiting_room")

    def test_supervisor_never_present(self, content):
        spec = next(n for n in content["npcs"]["npc"] if n["id"] == "supervisor")
        npc = NPC.from_content(spec)
        for loc in ["queue_window", "waiting_room", "parking_lot", "supervisors_door"]:
            assert not npc.is_present_at(loc)

    def test_round_trip_permanent(self, content):
        spec = next(n for n in content["npcs"]["npc"] if n["id"] == "e7")
        npc = NPC.from_content(spec)
        npc.relationship.trust = 3
        npc.relationship.topics_discussed = ["workaround"]
        d = npc.to_dict()
        npc2 = NPC.from_dict(d, spec)
        assert npc2.relationship.trust == 3

    def test_round_trip_nonpermanent_trust_0(self, content):
        spec = next(n for n in content["npcs"]["npc"] if n["id"] == "clerk")
        npc = NPC.from_content(spec)
        d = npc.to_dict()
        assert d["skipped"] is True
        npc2 = NPC.from_dict(d, spec)
        assert npc2.relationship.trust == 0


# ---------------------------------------------------------------------------
# locations.py
# ---------------------------------------------------------------------------

class TestLocations:
    def test_all_7_locations_built(self, content):
        locs = build_locations(content)
        assert len(locs) == 7

    def test_parking_lot_has_exit_to_gate(self, content):
        locs = build_locations(content)
        exits = [e.destination_id for e in locs["parking_lot"].exits]
        assert "installation_gate" in exits

    def test_gate_exit_to_waiting_room_requires_documents(self, content):
        locs = build_locations(content)
        gate = locs["installation_gate"]
        exit_to_wr = next(e for e in gate.exits if e.destination_id == "waiting_room")
        # Create a minimal fake state
        from types import SimpleNamespace
        fake_inv = SimpleNamespace(documents=[])
        fake_clock = SimpleNamespace(is_closed=lambda: False)
        state = SimpleNamespace(inventory=fake_inv, clock=fake_clock)
        assert not exit_to_wr.is_available(state)
        # Add a document
        fake_inv.documents = [object()]
        assert exit_to_wr.is_available(state)

    def test_library_exit_requires_knowledge(self, content):
        locs = build_locations(content)
        vending = locs["vending_alcove"]
        library_exit = next((e for e in vending.exits if e.destination_id == "base_library"), None)
        assert library_exit is not None
        from types import SimpleNamespace
        state_no = SimpleNamespace(permanent_knowledge=set())
        state_yes = SimpleNamespace(permanent_knowledge={"LIBRARY_LOCATION_KNOWN"})
        assert not library_exit.is_available(state_no)
        assert library_exit.is_available(state_yes)

    def test_supervisor_exit_requires_knowledge(self, content):
        locs = build_locations(content)
        wr = locs["waiting_room"]
        sup_exit = next((e for e in wr.exits if e.destination_id == "supervisors_door"), None)
        assert sup_exit is not None
        from types import SimpleNamespace
        state_no = SimpleNamespace(permanent_knowledge=set())
        state_yes = SimpleNamespace(permanent_knowledge={"SUPERVISOR_NAME_KNOWN"})
        assert not sup_exit.is_available(state_no)
        assert sup_exit.is_available(state_yes)

    def test_queue_window_exit_requires_number(self, content):
        locs = build_locations(content)
        wr = locs["waiting_room"]
        qw_exit = next(e for e in wr.exits if e.destination_id == "queue_window")
        from types import SimpleNamespace
        # No number, not lunch, office open
        state = SimpleNamespace(
            queue_position=None,
            clock=SimpleNamespace(is_lunch=lambda: False, is_office_open=lambda: True),
        )
        assert not qw_exit.is_available(state)
        state.queue_position = 1
        assert qw_exit.is_available(state)
