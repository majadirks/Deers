"""Tests for deers/dialogue.py and ClaudeClient.chat() (Phase 7)."""

from __future__ import annotations

import json
import pytest

from deers.claude_client import DummyClaudeClient
from deers.content import load_all
from deers.dialogue import (
    DialogueEngine,
    _TOPIC_CONFIDENCE,
    _MIN_TURNS_FOR_TRUST,
    _is_close_intent,
    _maybe_award_trust,
    _parse_topic_response,
)
from deers.npcs import ConversationBuffer
from deers.state import GameState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def content():
    return load_all()


@pytest.fixture
def state(content):
    s = GameState.new_game("TestPlayer", content)
    s.current_location_id = "waiting_room"
    return s


def _make_engine(content, topic_resp=None, chat_resp="Noted."):
    """Build a DialogueEngine backed by a DummyClaudeClient."""
    client = DummyClaudeClient(
        complete_response=topic_resp or _freeform_json(),
        chat_response=chat_resp,
    )
    return DialogueEngine.from_content(client, content), client


def _make_conv(npc_id="e7", turns=0):
    conv = ConversationBuffer(npc_id=npc_id)
    # Simulate prior turns by stuffing messages directly
    for i in range(turns):
        conv.add_player(f"player turn {i}")
        conv.add_npc(f"npc turn {i}")
    return conv


def _activate(state, npc_id="e7", turns=0):
    """Attach a fresh ConversationBuffer to state and return it."""
    conv = _make_conv(npc_id=npc_id, turns=turns)
    state.current_conversation = conv
    return conv


def _freeform_json():
    return json.dumps({"topic": "freeform", "confidence": 1.0})


def _topic_json(topic, confidence=0.9):
    return json.dumps({"topic": topic, "confidence": confidence})


# ---------------------------------------------------------------------------
# _is_close_intent
# ---------------------------------------------------------------------------

class TestIsCloseIntent:
    def test_bye(self):
        assert _is_close_intent("bye")

    def test_leave(self):
        assert _is_close_intent("I need to leave")

    def test_goodbye_mixed_case(self):
        assert _is_close_intent("Goodbye")

    def test_enough(self):
        assert _is_close_intent("that's enough for now")

    def test_done(self):
        assert _is_close_intent("done")

    def test_normal_input_false(self):
        assert not _is_close_intent("what is wrong with my record")

    def test_empty_false(self):
        assert not _is_close_intent("")

    def test_later(self):
        assert _is_close_intent("talk to you later")


# ---------------------------------------------------------------------------
# _parse_topic_response
# ---------------------------------------------------------------------------

class TestParseTopicResponse:
    def test_valid_high_confidence(self):
        text = _topic_json("deers_fix", 0.85)
        assert _parse_topic_response(text) == "deers_fix"

    def test_exactly_at_threshold(self):
        text = _topic_json("workaround", _TOPIC_CONFIDENCE)
        assert _parse_topic_response(text) == "workaround"

    def test_below_threshold_returns_freeform(self):
        text = _topic_json("deers_fix", _TOPIC_CONFIDENCE - 0.01)
        assert _parse_topic_response(text) == "freeform"

    def test_explicit_freeform(self):
        text = _freeform_json()
        assert _parse_topic_response(text) == "freeform"

    def test_invalid_json_returns_freeform(self):
        assert _parse_topic_response("not json") == "freeform"

    def test_missing_topic_returns_freeform(self):
        text = json.dumps({"confidence": 0.9})
        assert _parse_topic_response(text) == "freeform"

    def test_bad_confidence_returns_freeform(self):
        text = json.dumps({"topic": "deers_fix", "confidence": "not-a-number"})
        assert _parse_topic_response(text) == "freeform"

    def test_markdown_wrapped_json(self):
        text = "```json\n" + _topic_json("appointment_system", 0.8) + "\n```"
        assert _parse_topic_response(text) == "appointment_system"

    def test_null_topic_returns_freeform(self):
        text = json.dumps({"topic": None, "confidence": 0.95})
        assert _parse_topic_response(text) == "freeform"


# ---------------------------------------------------------------------------
# _maybe_award_trust
# ---------------------------------------------------------------------------

class TestMaybeAwardTrust:
    def test_awards_trust_after_min_turns(self, state):
        conv = _make_conv(turns=_MIN_TURNS_FOR_TRUST)
        npc = state.npcs["e7"]
        npc.relationship.trust = 0
        _maybe_award_trust(conv, npc)
        assert conv.pending_trust_delta == 1

    def test_no_trust_below_min_turns(self, state):
        conv = _make_conv(turns=_MIN_TURNS_FOR_TRUST - 1)
        npc = state.npcs["e7"]
        npc.relationship.trust = 0
        _maybe_award_trust(conv, npc)
        assert conv.pending_trust_delta == 0

    def test_no_trust_at_cap(self, state):
        conv = _make_conv(turns=_MIN_TURNS_FOR_TRUST)
        npc = state.npcs["e7"]
        npc.relationship.trust = 4  # already maxed
        _maybe_award_trust(conv, npc)
        assert conv.pending_trust_delta == 0


# ---------------------------------------------------------------------------
# DialogueEngine.from_content
# ---------------------------------------------------------------------------

class TestDialogueEngineFromContent:
    def test_constructs(self, content):
        engine, _ = _make_engine(content)
        assert isinstance(engine, DialogueEngine)

    def test_template_loaded(self, content):
        engine, _ = _make_engine(content)
        # Template should exist and be renderable
        assert engine._template is not None

    def test_topic_system_loaded(self, content):
        engine, _ = _make_engine(content)
        assert "topic" in engine._topic_system.lower()


# ---------------------------------------------------------------------------
# DialogueEngine.respond — basic flow
# ---------------------------------------------------------------------------

class TestDialogueEngineRespondBasic:
    def test_returns_npc_line(self, state, content):
        engine, _ = _make_engine(content, chat_resp="I'll need your case number.")
        _activate(state, npc_id="e7")
        result = engine.respond("tell me about DEERS", state)
        assert "I'll need your case number." in result

    def test_no_active_conv_returns_empty(self, state, content):
        engine, _ = _make_engine(content)
        state.current_conversation = None
        assert engine.respond("hello", state) == ""

    def test_npc_name_in_response(self, state, content):
        engine, _ = _make_engine(content, chat_resp="Test response.")
        _activate(state, npc_id="e7")
        result = engine.respond("hello", state)
        npc = state.npcs["e7"]
        assert npc.display_name(state) in result

    def test_records_player_turn(self, state, content):
        engine, _ = _make_engine(content)
        conv = _activate(state, npc_id="e7")
        engine.respond("hello", state)
        player_msgs = [m for m in conv.messages if m["role"] == "user"]
        assert any("hello" in m["content"] for m in player_msgs)

    def test_records_npc_turn(self, state, content):
        engine, _ = _make_engine(content, chat_resp="My response.")
        conv = _activate(state, npc_id="e7")
        engine.respond("hello", state)
        npc_msgs = [m for m in conv.messages if m["role"] == "assistant"]
        assert any("My response." in m["content"] for m in npc_msgs)

    def test_calls_topic_parser(self, state, content):
        engine, client = _make_engine(content)
        _activate(state, npc_id="e7")
        engine.respond("what about my record", state)
        assert len(client.complete_calls) == 1

    def test_calls_chat_for_response(self, state, content):
        engine, client = _make_engine(content)
        _activate(state, npc_id="e7")
        engine.respond("hello", state)
        assert len(client.chat_calls) == 1

    def test_history_passed_to_chat(self, state, content):
        engine, client = _make_engine(content)
        conv = _activate(state, npc_id="e7", turns=1)
        engine.respond("new input", state)
        _, messages = client.chat_calls[0]
        # Should include prior turns plus new player input
        assert len(messages) >= 3  # 2 prior + 1 new


# ---------------------------------------------------------------------------
# DialogueEngine.respond — close intent
# ---------------------------------------------------------------------------

class TestDialogueEngineClose:
    def test_close_returns_step_away(self, state, content):
        engine, _ = _make_engine(content)
        _activate(state, npc_id="e7")
        result = engine.respond("bye", state)
        assert "step away" in result.lower()

    def test_close_clears_conversation(self, state, content):
        engine, _ = _make_engine(content)
        _activate(state, npc_id="e7")
        engine.respond("leave", state)
        assert state.current_conversation is None

    def test_close_commits_morale(self, state, content):
        engine, _ = _make_engine(content)
        conv = _activate(state, npc_id="e7")
        conv.accrue_effects(morale_delta=-5)
        before = state.morale.current
        engine.respond("bye", state)
        assert state.morale.current == before - 5

    def test_close_commits_knowledge(self, state, content):
        engine, _ = _make_engine(content)
        conv = _activate(state, npc_id="e7")
        conv.accrue_effects(knowledge=["TEST_KEY"])
        engine.respond("bye", state)
        assert "TEST_KEY" in state.permanent_knowledge

    def test_close_awards_trust_after_min_turns(self, state, content):
        engine, _ = _make_engine(content)
        e7 = state.npcs["e7"]
        e7.relationship.trust = 0
        _activate(state, npc_id="e7", turns=_MIN_TURNS_FOR_TRUST)
        engine.respond("bye", state)
        assert e7.relationship.trust == 1

    def test_close_no_trust_below_min_turns(self, state, content):
        engine, _ = _make_engine(content)
        e7 = state.npcs["e7"]
        e7.relationship.trust = 0
        _activate(state, npc_id="e7", turns=0)
        engine.respond("bye", state)
        assert e7.relationship.trust == 0


# ---------------------------------------------------------------------------
# DialogueEngine.respond — fallback on ClaudeUnavailable
# ---------------------------------------------------------------------------

class TestDialogueEngineFallback:
    def test_uses_fallback_line_when_chat_fails(self, state, content):
        client = DummyClaudeClient(raises=True)
        engine = DialogueEngine.from_content(client, content)
        _activate(state, npc_id="e7")
        result = engine.respond("hello", state)
        npc = state.npcs["e7"]
        assert npc.card.fallback_line in result

    def test_topic_freeform_when_parser_fails(self, state, content):
        # Topic parse failure → freeform → no topic effects accrued
        client = DummyClaudeClient(raises=True)
        engine = DialogueEngine.from_content(client, content)
        conv = _activate(state, npc_id="e7")
        before_morale = state.morale.current
        engine.respond("hello", state)
        # No topic-specific morale should have accrued
        assert conv.pending_morale_delta == 0

    def test_respond_never_raises(self, state, content):
        client = DummyClaudeClient(raises=True)
        engine = DialogueEngine.from_content(client, content)
        _activate(state, npc_id="e7")
        result = engine.respond("any input", state)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Topic-based knowledge accrual
# ---------------------------------------------------------------------------

class TestTopicKnowledgeAccrual:
    def test_e7_workaround_grants_key(self, state, content):
        engine, _ = _make_engine(
            content,
            topic_resp=_topic_json("workaround", 0.9),
        )
        # e7 needs trust >= 3 to discuss workaround
        state.npcs["e7"].relationship.trust = 3
        conv = _activate(state, npc_id="e7")
        engine.respond("how do I bypass this", state)
        assert "WORKAROUND_KNOWN" in conv.pending_knowledge

    def test_e7_library_grants_key(self, state, content):
        engine, _ = _make_engine(
            content,
            topic_resp=_topic_json("base_library_location", 0.85),
        )
        state.npcs["e7"].relationship.trust = 1
        conv = _activate(state, npc_id="e7")
        engine.respond("where can I copy documents", state)
        assert "LIBRARY_LOCATION_KNOWN" in conv.pending_knowledge

    def test_contractor_library_grants_key(self, state, content):
        engine, _ = _make_engine(
            content,
            topic_resp=_topic_json("base_library_location", 0.85),
        )
        state.current_location_id = "vending_alcove"
        conv = _activate(state, npc_id="contractor")
        engine.respond("where is the library", state)
        assert "LIBRARY_LOCATION_KNOWN" in conv.pending_knowledge

    def test_known_key_not_re_accrued(self, state, content):
        state.permanent_knowledge.add("WORKAROUND_KNOWN")
        engine, _ = _make_engine(
            content,
            topic_resp=_topic_json("workaround", 0.9),
        )
        state.npcs["e7"].relationship.trust = 3
        conv = _activate(state, npc_id="e7")
        engine.respond("tell me the number again", state)
        assert "WORKAROUND_KNOWN" not in conv.pending_knowledge

    def test_same_key_not_accrued_twice_in_one_conv(self, state, content):
        state.permanent_knowledge.discard("WORKAROUND_KNOWN")
        engine, _ = _make_engine(
            content,
            topic_resp=_topic_json("workaround", 0.9),
        )
        state.npcs["e7"].relationship.trust = 3
        conv = _activate(state, npc_id="e7")
        engine.respond("tell me the workaround", state)
        engine.respond("tell me the workaround again", state)
        count = conv.pending_knowledge.count("WORKAROUND_KNOWN")
        assert count == 1


# ---------------------------------------------------------------------------
# Trust-milestone knowledge unlocks
# ---------------------------------------------------------------------------

class TestTrustKnowledgeUnlocks:
    def test_e7_trust_1_grants_clerk_name(self, state, content):
        engine, _ = _make_engine(content)
        e7 = state.npcs["e7"]
        e7.relationship.trust = 0
        conv = _activate(state, npc_id="e7", turns=_MIN_TURNS_FOR_TRUST)
        engine.respond("bye", state)
        # trust should now be 1 → CLERK_NAME_KNOWN granted
        assert "CLERK_NAME_KNOWN" in state.permanent_knowledge

    def test_clerk_trust_2_grants_transcendence_step1(self, state, content):
        engine, _ = _make_engine(content)
        clerk = state.npcs["clerk"]
        clerk.relationship.trust = 1  # start at 1
        # Move to queue_window where clerk is present
        state.current_location_id = "queue_window"
        conv = _activate(state, npc_id="clerk", turns=_MIN_TURNS_FOR_TRUST)
        engine.respond("bye", state)
        # trust 1 → 2 → TRANSCENDENCE_STEP_1
        assert "TRANSCENDENCE_STEP_1" in state.permanent_knowledge

    def test_trust_not_granted_when_trust_stays_0(self, state, content):
        state.permanent_knowledge.discard("CLERK_NAME_KNOWN")
        engine, _ = _make_engine(content)
        e7 = state.npcs["e7"]
        e7.relationship.trust = 0
        # Only 1 turn — below min, no trust awarded
        _activate(state, npc_id="e7", turns=0)
        engine.respond("bye", state)
        assert "CLERK_NAME_KNOWN" not in state.permanent_knowledge


# ---------------------------------------------------------------------------
# Topic effects: morale
# ---------------------------------------------------------------------------

class TestMoraleAccrual:
    def test_topic_morale_delta_accrued(self, state, content):
        # e7's deers_fix topic has morale_delta=1
        engine, _ = _make_engine(
            content,
            topic_resp=_topic_json("deers_fix", 0.9),
        )
        conv = _activate(state, npc_id="e7")
        engine.respond("what is wrong with my record", state)
        assert conv.pending_morale_delta == 1

    def test_freeform_no_morale_delta(self, state, content):
        engine, _ = _make_engine(content, topic_resp=_freeform_json())
        conv = _activate(state, npc_id="e7")
        engine.respond("nice weather", state)
        assert conv.pending_morale_delta == 0


# ---------------------------------------------------------------------------
# Exhaustion
# ---------------------------------------------------------------------------

class TestExhaustion:
    def test_exhausted_conv_closes(self, state, content):
        engine, _ = _make_engine(content)
        # Set up conv with max_turns - 1 turns already taken (one more will exhaust)
        from deers.npcs import MAX_CONVERSATION_TURNS
        conv = _activate(state, npc_id="e7", turns=MAX_CONVERSATION_TURNS - 1)
        result = engine.respond("one more thing", state)
        assert "natural end" in result
        assert state.current_conversation is None

    def test_exhausted_includes_last_npc_line(self, state, content):
        from deers.npcs import MAX_CONVERSATION_TURNS
        engine, _ = _make_engine(content, chat_resp="Final words.")
        _activate(state, npc_id="e7", turns=MAX_CONVERSATION_TURNS - 1)
        result = engine.respond("last question", state)
        assert "Final words." in result


# ---------------------------------------------------------------------------
# Engine wiring
# ---------------------------------------------------------------------------

class TestEngineDialogueWiring:
    def test_no_api_key_dialogue_is_none(self):
        from deers.engine import GameEngine
        eng = GameEngine("TestPlayer")
        assert eng.dialogue is None

    def test_stub_handles_close_without_dialogue(self):
        from deers.engine import GameEngine
        eng = GameEngine("TestPlayer")
        assert eng.dialogue is None
        eng.state.current_location_id = "waiting_room"
        # Start a conversation manually
        conv = ConversationBuffer(npc_id="e7")
        eng.state.current_conversation = conv
        result = eng._handle_dialogue("bye")
        assert eng.state.current_conversation is None
        assert isinstance(result, str)

    def test_handle_dialogue_appends_world_state_after_close(self, content):
        from deers.engine import GameEngine
        eng = GameEngine("TestPlayer")
        eng.state.current_location_id = "waiting_room"
        # Inject a mock dialogue engine that returns close
        class _MockDialogue:
            def respond(self, raw, state):
                state.current_conversation = None
                return "You step away from the conversation."
        eng.dialogue = _MockDialogue()
        conv = ConversationBuffer(npc_id="e7")
        eng.state.current_conversation = conv
        result = eng._handle_dialogue("bye")
        # Should contain both the close message and the status line
        assert "You step away" in result
        assert "[Loop" in result

    def test_handle_dialogue_no_world_state_mid_conversation(self, content):
        from deers.engine import GameEngine
        eng = GameEngine("TestPlayer")
        eng.state.current_location_id = "waiting_room"
        conv = ConversationBuffer(npc_id="e7")
        eng.state.current_conversation = conv

        class _MockDialogue:
            def respond(self, raw, state):
                # Conversation stays open
                return 'The E-7: "Noted."'
        eng.dialogue = _MockDialogue()
        result = eng._handle_dialogue("tell me more")
        # Only the NPC line — no status line appended
        assert result == 'The E-7: "Noted."'
        assert "[Loop" not in result
