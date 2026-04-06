"""Tests for deers/narrator.py (Phase 6)."""

from __future__ import annotations

import pytest

from deers.claude_client import DummyClaudeClient
from deers.content import load_all
from deers.narrator import (
    NarratorEngine,
    _fallback_description,
    _format_facts,
    build_location_user_message,
    cache_key,
)
from deers.state import GameState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def content():
    return load_all()


@pytest.fixture
def state(content):
    return GameState.new_game("TestPlayer", content)


GENERATED = "You are standing in a parking lot that smells of institutional ambition."


# ---------------------------------------------------------------------------
# cache_key
# ---------------------------------------------------------------------------

class TestCacheKey:
    def test_format(self, state):
        key = cache_key(state)
        parts = key.split(":")
        assert len(parts) == 4

    def test_location_in_key(self, state):
        key = cache_key(state)
        assert key.startswith(state.current_location_id + ":")

    def test_loop_in_key(self, state):
        key = cache_key(state)
        assert f":{state.loop_number}:" in key

    def test_morale_bracket_in_key(self, state):
        key = cache_key(state)
        assert state.morale.bracket() in key

    def test_time_bracket_in_key(self, state):
        key = cache_key(state)
        assert state.clock.time_bracket() in key

    def test_different_morale_different_key(self, state, content):
        state_b = GameState.new_game("B", content)
        state_b.morale.apply_delta(-80)  # drive to critical
        assert cache_key(state) != cache_key(state_b)

    def test_different_location_different_key(self, state, content):
        state_b = GameState.new_game("B", content)
        state_b.current_location_id = "waiting_room"
        assert cache_key(state) != cache_key(state_b)

    def test_different_loop_different_key(self, state, content):
        state_b = GameState.new_game("B", content)
        state_b.loop_number = 3
        assert cache_key(state) != cache_key(state_b)


# ---------------------------------------------------------------------------
# _format_facts
# ---------------------------------------------------------------------------

class TestFormatFacts:
    def test_string_value(self):
        lines = _format_facts({"tone": "exhausted"})
        assert "tone: exhausted" in lines

    def test_bool_true(self):
        lines = _format_facts({"inside": True})
        assert "inside: yes" in lines

    def test_bool_false(self):
        lines = _format_facts({"inside": False})
        assert "inside: no" in lines

    def test_list_value(self):
        lines = _format_facts({"visible_features": ["chairs", "clock"]})
        assert "visible_features: chairs, clock" in lines

    def test_empty_facts(self):
        assert _format_facts({}) == []


# ---------------------------------------------------------------------------
# build_location_user_message
# ---------------------------------------------------------------------------

class TestBuildLocationUserMessage:
    def test_contains_location_name(self, state):
        msg = build_location_user_message(state)
        loc = state.current_location()
        assert loc.name in msg

    def test_contains_base_description(self, state):
        msg = build_location_user_message(state)
        assert state.current_location().static_description in msg

    def test_contains_loop(self, state):
        msg = build_location_user_message(state)
        assert f"LOOP: {state.loop_number}" in msg

    def test_contains_morale(self, state):
        msg = build_location_user_message(state)
        assert state.morale.bracket() in msg

    def test_contains_time(self, state):
        msg = build_location_user_message(state)
        assert state.clock.time_display() in msg

    def test_contains_no_npcs_label_when_empty(self, state):
        # parking_lot has no NPCs
        msg = build_location_user_message(state)
        assert "NPCS_PRESENT: none" in msg

    def test_writing_instruction_present(self, state):
        msg = build_location_user_message(state)
        assert "second person" in msg.lower() or "Second person" in msg


# ---------------------------------------------------------------------------
# _fallback_description
# ---------------------------------------------------------------------------

class TestFallbackDescription:
    def test_contains_static_description(self, state):
        desc = _fallback_description(state)
        assert state.current_location().static_description in desc

    def test_no_exits_listed(self, state):
        desc = _fallback_description(state)
        # Fallback must not list exits — player uses STATUS
        assert "Exits:" not in desc

    def test_lists_npcs_when_present(self, state, content):
        # Move to waiting_room where e7 might be present
        state2 = GameState.new_game("P", content)
        state2.current_location_id = "waiting_room"
        desc = _fallback_description(state2)
        # Just check it doesn't crash and returns a string
        assert isinstance(desc, str)
        assert len(desc) > 0


# ---------------------------------------------------------------------------
# NarratorEngine.from_content
# ---------------------------------------------------------------------------

class TestNarratorEngineFromContent:
    def test_constructs(self, content):
        engine = NarratorEngine.from_content(DummyClaudeClient(), content)
        assert isinstance(engine, NarratorEngine)

    def test_system_prompt_loaded(self, content):
        engine = NarratorEngine.from_content(DummyClaudeClient(), content)
        assert content["prompts"]["narrator"]["system"] in engine._system

    def test_empty_cache_by_default(self, content):
        engine = NarratorEngine.from_content(DummyClaudeClient(), content)
        assert engine.cache == {}

    def test_supplied_cache_used(self, content):
        pre = {"parking_lot:1:high:morning": "Cached desc."}
        engine = NarratorEngine.from_content(DummyClaudeClient(), content, cache=pre)
        assert len(engine.cache) == 1


# ---------------------------------------------------------------------------
# NarratorEngine.describe_location — cache behaviour
# ---------------------------------------------------------------------------

class TestDescribeLocationCache:
    def test_cache_hit_returns_stored_value(self, state, content):
        client = DummyClaudeClient()
        engine = NarratorEngine.from_content(client, content)
        key = cache_key(state)
        engine.cache[key] = "Pre-cached description."
        result = engine.describe_location(state)
        assert result == "Pre-cached description."
        assert client.complete_calls == []  # Claude was NOT called

    def test_cache_miss_calls_claude(self, state, content):
        client = DummyClaudeClient()
        engine = NarratorEngine.from_content(client, content)
        engine.describe_location(state)
        assert len(client.complete_calls) == 1

    def test_result_stored_in_cache(self, state, content):
        client = DummyClaudeClient(complete_response=GENERATED)
        engine = NarratorEngine.from_content(client, content)
        engine.describe_location(state)
        key = cache_key(state)
        assert engine.cache[key] == GENERATED

    def test_second_call_uses_cache(self, state, content):
        client = DummyClaudeClient()
        engine = NarratorEngine.from_content(client, content)
        engine.describe_location(state)
        engine.describe_location(state)
        assert len(client.complete_calls) == 1  # only one real API call

    def test_different_location_separate_cache_entries(self, state, content):
        client = DummyClaudeClient()
        engine = NarratorEngine.from_content(client, content)
        engine.describe_location(state)
        state.current_location_id = "installation_gate"
        engine.describe_location(state)
        assert len(client.complete_calls) == 2


# ---------------------------------------------------------------------------
# NarratorEngine.describe_location — Claude path
# ---------------------------------------------------------------------------

class TestDescribeLocationClaudePath:
    def test_returns_claude_text(self, state, content):
        engine = NarratorEngine.from_content(DummyClaudeClient(complete_response=GENERATED), content)
        result = engine.describe_location(state)
        assert result == GENERATED

    def test_user_message_sent_to_claude(self, state, content):
        client = DummyClaudeClient()
        engine = NarratorEngine.from_content(client, content)
        engine.describe_location(state)
        _, user_msg = client.complete_calls[0]
        assert state.current_location().name in user_msg


# ---------------------------------------------------------------------------
# NarratorEngine.describe_location — fallback path
# ---------------------------------------------------------------------------

class TestDescribeLocationFallback:
    def test_falls_back_on_claude_unavailable(self, state, content):
        engine = NarratorEngine.from_content(DummyClaudeClient(raises=True), content)
        result = engine.describe_location(state)
        # Should return static description, not raise
        assert state.current_location().static_description in result

    def test_fallback_does_not_cache(self, state, content):
        """Failed calls must not be cached — next time should retry Claude."""
        engine = NarratorEngine.from_content(DummyClaudeClient(raises=True), content)
        engine.describe_location(state)
        assert cache_key(state) not in engine.cache

    def test_fallback_never_raises(self, state, content):
        engine = NarratorEngine.from_content(DummyClaudeClient(raises=True), content)
        result = engine.describe_location(state)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Engine wiring
# ---------------------------------------------------------------------------

class TestEngineWiring:
    def test_no_api_key_narrator_is_none(self):
        from deers.engine import GameEngine
        eng = GameEngine("TestPlayer")
        assert eng.narrator is None

    def test_no_api_key_describe_location_uses_engine_fallback(self):
        from deers.engine import GameEngine
        eng = GameEngine("TestPlayer")
        result = eng._describe_current_location()
        assert isinstance(result, str)
        assert len(result) > 0
        # Engine fallback lists exits for devmode usability
        assert "Exits:" in result or "installation_gate" in result

    def test_narrator_describe_location_used_when_set(self, content):
        from deers.engine import GameEngine
        eng = GameEngine("TestPlayer")
        # Inject narrator with a fixed response
        engine_narrator = NarratorEngine.from_content(
            DummyClaudeClient(complete_response="Narrator was here."), content
        )
        eng.narrator = engine_narrator
        result = eng._describe_current_location()
        assert result == "Narrator was here."

    def test_save_calls_save_narrator_cache(self, content, tmp_path, monkeypatch):
        from deers.engine import GameEngine
        import deers.persistence as pers
        monkeypatch.setattr(pers, "SAVE_DIR", tmp_path)

        eng = GameEngine("TestPlayer")
        engine_narrator = NarratorEngine.from_content(
            DummyClaudeClient(), content, cache={"k": "v"}
        )
        eng.narrator = engine_narrator
        eng.save()

        cache_file = tmp_path / "narrator_cache.json"
        assert cache_file.exists()
        import json
        saved = json.loads(cache_file.read_text())
        assert saved == {"k": "v"}

    def test_save_without_narrator_does_not_crash(self, tmp_path, monkeypatch):
        from deers.engine import GameEngine
        import deers.persistence as pers
        monkeypatch.setattr(pers, "SAVE_DIR", tmp_path)

        eng = GameEngine("TestPlayer")
        assert eng.narrator is None
        eng.save()  # must not raise
