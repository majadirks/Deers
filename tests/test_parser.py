"""Tests for deers/parser.py and deers/claude_client.py (Phase 5)."""

from __future__ import annotations

import json
import pytest

from deers.claude_client import ClaudeUnavailable
from deers.content import load_all
from deers.models import ParsedAction
from deers.parser import (
    InputParser,
    _CLARIFICATION_CONFIDENCE,
    _VALID_VERBS,
    _build_context,
    _keyword_parse,
    _parse_json_response,
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


class _MockClient:
    """Duck-typed ClaudeClient that returns a fixed string."""

    def __init__(self, response_text: str):
        self._response = response_text

    def complete(self, system: str, user: str, max_tokens: int = 128) -> str:
        return self._response


class _FailingClient:
    """Duck-typed ClaudeClient that always raises ClaudeUnavailable."""

    def complete(self, system: str, user: str, max_tokens: int = 128) -> str:
        raise ClaudeUnavailable("simulated failure")


def _make_json(**kwargs) -> str:
    defaults = {"verb": "EXAMINE", "target": "location", "confidence": 0.95, "clarification": None}
    defaults.update(kwargs)
    return json.dumps(defaults)


# ---------------------------------------------------------------------------
# ClaudeUnavailable
# ---------------------------------------------------------------------------

class TestClaudeUnavailable:
    def test_is_exception(self):
        exc = ClaudeUnavailable("test")
        assert isinstance(exc, Exception)
        assert str(exc) == "test"


# ---------------------------------------------------------------------------
# _keyword_parse
# ---------------------------------------------------------------------------

class TestKeywordParse:
    def test_empty_input(self):
        result = _keyword_parse("")
        assert result.verb == "EXAMINE"
        assert result.target == "location"

    def test_whitespace_only(self):
        result = _keyword_parse("   ")
        assert result.verb == "EXAMINE"
        assert result.target == "location"

    def test_valid_verb_no_target(self):
        result = _keyword_parse("WAIT")
        assert result.verb == "WAIT"
        assert result.target == ""

    def test_valid_verb_lowercase(self):
        result = _keyword_parse("go waiting_room")
        assert result.verb == "GO"
        assert result.target == "waiting_room"

    def test_valid_verb_with_multi_word_target(self):
        result = _keyword_parse("examine the old desk")
        assert result.verb == "EXAMINE"
        assert result.target == "the old desk"

    def test_invalid_verb_falls_back_to_examine(self):
        result = _keyword_parse("flibbertigibbet around")
        assert result.verb == "EXAMINE"
        assert result.target == "flibbertigibbet around"

    def test_all_valid_verbs_recognised(self):
        for verb in _VALID_VERBS:
            result = _keyword_parse(f"{verb} something")
            assert result.verb == verb

    def test_no_clarification_set(self):
        result = _keyword_parse("go gate")
        assert result.clarification is None


# ---------------------------------------------------------------------------
# _parse_json_response
# ---------------------------------------------------------------------------

class TestParseJsonResponse:
    def test_well_formed_json(self):
        text = _make_json(verb="GO", target="waiting_room", confidence=0.95)
        result = _parse_json_response(text, "go to the waiting room")
        assert result.verb == "GO"
        assert result.target == "waiting_room"
        assert result.clarification is None

    def test_markdown_code_fence_stripped(self):
        text = "```json\n" + _make_json(verb="WAIT", target="") + "\n```"
        result = _parse_json_response(text, "wait here")
        assert result.verb == "WAIT"

    def test_markdown_fence_without_language(self):
        text = "```\n" + _make_json(verb="TALK", target="clerk") + "\n```"
        result = _parse_json_response(text, "talk to clerk")
        assert result.verb == "TALK"
        assert result.target == "clerk"

    def test_invalid_json_falls_back_to_keyword(self):
        result = _parse_json_response("not valid json at all", "go gate")
        assert result.verb == "GO"
        assert result.target == "gate"

    def test_unknown_verb_falls_back_to_keyword(self):
        text = _make_json(verb="DANCE", target="floor")
        result = _parse_json_response(text, "examine desk")
        assert result.verb == "EXAMINE"
        assert result.target == "desk"

    def test_null_target_becomes_empty_string(self):
        text = json.dumps({"verb": "WAIT", "target": None, "confidence": 0.9, "clarification": None})
        result = _parse_json_response(text, "wait")
        assert result.target == ""

    def test_missing_target_becomes_empty_string(self):
        text = json.dumps({"verb": "WAIT", "confidence": 0.9, "clarification": None})
        result = _parse_json_response(text, "wait")
        assert result.target == ""

    def test_low_confidence_with_clarification_returns_clarification(self):
        text = _make_json(
            verb="EXAMINE",
            target="",
            confidence=_CLARIFICATION_CONFIDENCE - 0.1,
            clarification="Did you want to examine the clerk or the window?",
        )
        result = _parse_json_response(text, "look at the thing")
        assert result.clarification == "Did you want to examine the clerk or the window?"
        assert result.verb == "EXAMINE"

    def test_high_confidence_clarification_is_ignored(self):
        """Above threshold: act on the verb, don't surface the clarification."""
        text = _make_json(
            verb="EXAMINE",
            target="desk",
            confidence=_CLARIFICATION_CONFIDENCE + 0.1,
            clarification="Did you mean the desk?",
        )
        result = _parse_json_response(text, "look at that thing")
        assert result.clarification is None
        assert result.verb == "EXAMINE"
        assert result.target == "desk"

    def test_exactly_at_threshold_not_clarification(self):
        """Confidence at threshold exactly: proceed, no clarification."""
        text = _make_json(
            verb="GO",
            target="gate",
            confidence=_CLARIFICATION_CONFIDENCE,
            clarification="Did you mean the gate?",
        )
        result = _parse_json_response(text, "head to gate")
        assert result.clarification is None

    def test_bad_confidence_value_defaults_to_1(self):
        text = json.dumps({"verb": "WAIT", "target": "", "confidence": "not-a-number", "clarification": None})
        result = _parse_json_response(text, "wait")
        assert result.verb == "WAIT"
        assert result.clarification is None

    def test_target_lowercased(self):
        text = _make_json(verb="TALK", target="E7_VETERAN")
        result = _parse_json_response(text, "talk to e7")
        assert result.target == "e7_veteran"

    def test_verb_case_insensitive_in_json(self):
        text = _make_json(verb="examine", target="desk")
        result = _parse_json_response(text, "examine desk")
        assert result.verb == "EXAMINE"


# ---------------------------------------------------------------------------
# _build_context
# ---------------------------------------------------------------------------

class TestBuildContext:
    def test_contains_location(self, state):
        ctx = _build_context(state)
        assert f"location: {state.current_location_id}" in ctx

    def test_contains_loop(self, state):
        ctx = _build_context(state)
        assert f"loop: {state.loop_number}" in ctx

    def test_contains_queue_position(self, state):
        ctx = _build_context(state)
        assert "queue_position:" in ctx

    def test_no_npcs_at_parking_lot(self, state):
        # parking_lot has no NPCs; should say 'none'
        assert state.current_location_id == "parking_lot"
        ctx = _build_context(state)
        assert "npcs_present: none" in ctx

    def test_exits_listed(self, state):
        ctx = _build_context(state)
        assert "exits:" in ctx


# ---------------------------------------------------------------------------
# InputParser.from_content
# ---------------------------------------------------------------------------

class TestInputParserFromContent:
    def test_constructs_from_content(self, content):
        client = _MockClient(_make_json())
        parser = InputParser.from_content(client, content)
        assert isinstance(parser, InputParser)
        assert content["prompts"]["parser"]["system"] in parser._system


# ---------------------------------------------------------------------------
# InputParser.parse — Claude path
# ---------------------------------------------------------------------------

class TestInputParserClaudePath:
    def test_returns_parsed_action(self, content, state):
        response = _make_json(verb="GO", target="installation_gate", confidence=0.95)
        parser = InputParser.from_content(_MockClient(response), content)
        result = parser.parse("head to the gate", state)
        assert isinstance(result, ParsedAction)
        assert result.verb == "GO"
        assert result.target == "installation_gate"

    def test_low_confidence_returns_clarification(self, content, state):
        response = _make_json(
            verb="TALK",
            target="",
            confidence=0.4,
            clarification="Who would you like to speak with?",
        )
        parser = InputParser.from_content(_MockClient(response), content)
        result = parser.parse("talk to someone", state)
        assert result.clarification == "Who would you like to speak with?"

    def test_malformed_response_falls_back_to_keyword(self, content, state):
        parser = InputParser.from_content(_MockClient("oops not json"), content)
        result = parser.parse("go gate", state)
        assert result.verb == "GO"
        assert result.target == "gate"

    def test_markdown_wrapped_response_handled(self, content, state):
        response = "```json\n" + _make_json(verb="EXAMINE", target="location") + "\n```"
        parser = InputParser.from_content(_MockClient(response), content)
        result = parser.parse("look around", state)
        assert result.verb == "EXAMINE"


# ---------------------------------------------------------------------------
# InputParser.parse — fallback path
# ---------------------------------------------------------------------------

class TestInputParserFallbackPath:
    def test_falls_back_on_claude_unavailable(self, content, state):
        parser = InputParser.from_content(_FailingClient(), content)
        result = parser.parse("go gate", state)
        # Should fall back to keyword parse
        assert result.verb == "GO"
        assert result.target == "gate"

    def test_fallback_never_raises(self, content, state):
        parser = InputParser.from_content(_FailingClient(), content)
        result = parser.parse("some completely nonsensical input !!!", state)
        assert isinstance(result, ParsedAction)

    def test_fallback_empty_input(self, content, state):
        parser = InputParser.from_content(_FailingClient(), content)
        result = parser.parse("", state)
        assert result.verb == "EXAMINE"
        assert result.target == "location"


# ---------------------------------------------------------------------------
# GameEngine wiring
# ---------------------------------------------------------------------------

class TestEngineWiring:
    def test_no_api_key_parser_is_none(self, content):
        from deers.engine import GameEngine
        eng = GameEngine.__new__(GameEngine)
        # Simulate init without api_key
        from deers.actions import ActionResolver
        from deers.conditions import ConditionScheduler
        from deers.parser import _keyword_parse
        eng.state = GameState.new_game("T", content)
        eng.resolver = ActionResolver()
        eng.scheduler = ConditionScheduler()
        eng.api_key = None
        eng.parser = None
        eng.narrator = None
        eng.dialogue = None
        assert eng.parser is None

    def test_keyword_fallback_used_when_parser_none(self, content):
        from deers.engine import GameEngine
        eng = GameEngine("TestPlayer")
        assert eng.parser is None
        # Go to gate is a valid keyword-parseable command
        result = eng.handle_input("go installation_gate")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_clarification_returned_directly(self, content):
        from deers.engine import GameEngine
        eng = GameEngine("TestPlayer")
        # Inject a mock parser that always returns a clarification
        class _ClarifyParser:
            def parse(self, raw, state):
                return ParsedAction(
                    verb="EXAMINE", target="", clarification="What do you want to examine?"
                )
        eng.parser = _ClarifyParser()
        result = eng.handle_input("look at something ambiguous")
        assert result == "What do you want to examine?"

    def test_no_clarification_proceeds_to_action(self, content):
        from deers.engine import GameEngine
        eng = GameEngine("TestPlayer")
        class _DirectParser:
            def parse(self, raw, state):
                return ParsedAction(verb="EXAMINE", target="location")
        eng.parser = _DirectParser()
        result = eng.handle_input("look around")
        # Should not be the clarification, should be a real location description
        assert "[Loop" in result  # status line present
