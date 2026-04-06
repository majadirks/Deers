"""InputParser: parse raw player text into ParsedAction using Claude with keyword fallback."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from deers.claude_client import ClaudeClient, ClaudeUnavailable
from deers.models import ParsedAction

if TYPE_CHECKING:
    from deers.state import GameState

_VALID_VERBS = frozenset(
    {
        "GO", "TALK", "EXAMINE", "TAKE", "USE", "WAIT", "DROP", "READ",
        "HELP", "STATUS", "QUIT", "SUBMIT", "GIVE", "HAND",
    }
)

# Threshold below which we emit the clarification as a hint message
_CLARIFICATION_CONFIDENCE = 0.7


class InputParser:
    """
    Wraps Claude to parse natural language into ParsedAction.
    Falls back to keyword parsing on any API failure.
    """

    def __init__(self, client: ClaudeClient, system_prompt: str):
        self._client = client
        self._system = system_prompt

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def parse(self, raw: str, state: "GameState") -> ParsedAction:
        """Parse raw input. Returns ParsedAction; never raises."""
        try:
            return self._claude_parse(raw, state)
        except ClaudeUnavailable:
            return _keyword_parse(raw)

    # ------------------------------------------------------------------
    # Claude path
    # ------------------------------------------------------------------

    def _claude_parse(self, raw: str, state: "GameState") -> ParsedAction:
        context = _build_context(state)
        user_msg = f"CONTEXT:\n{context}\n\nPLAYER INPUT: {raw}"
        text = self._client.complete(self._system, user_msg, max_tokens=128)
        return _parse_json_response(text, raw)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_content(cls, client: ClaudeClient, content: dict) -> "InputParser":
        system_prompt = content["prompts"]["parser"]["system"]
        return cls(client, system_prompt)


# ---------------------------------------------------------------------------
# JSON response parsing
# ---------------------------------------------------------------------------

def _parse_json_response(text: str, raw: str) -> ParsedAction:
    """Extract JSON from Claude response; fall back to keyword parse on failure."""
    # Strip markdown code fences if present
    cleaned = re.sub(r"```(?:json)?|```", "", text).strip()
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return _keyword_parse(raw)

    verb = str(data.get("verb") or "").upper()
    if verb not in _VALID_VERBS:
        return _keyword_parse(raw)

    # target may be null/None from Claude — normalise to empty string
    target = str(data.get("target") or "").lower().strip()

    try:
        confidence = float(data.get("confidence", 1.0))
    except (TypeError, ValueError):
        confidence = 1.0

    clarification = data.get("clarification") or None

    if clarification and confidence < _CLARIFICATION_CONFIDENCE:
        return ParsedAction(verb=verb, target=target, clarification=clarification)

    return ParsedAction(verb=verb, target=target)


# ---------------------------------------------------------------------------
# Keyword fallback (same logic as engine._simple_parse)
# ---------------------------------------------------------------------------

def _keyword_parse(raw: str) -> ParsedAction:
    tokens = raw.strip().split()
    if not tokens:
        return ParsedAction(verb="EXAMINE", target="location")
    verb = tokens[0].upper()
    if verb not in _VALID_VERBS:
        verb = "EXAMINE"
        target = raw.lower().strip()
    else:
        target = " ".join(tokens[1:]).lower() if len(tokens) > 1 else ""
    return ParsedAction(verb=verb, target=target)


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------

def _build_context(state: "GameState") -> str:
    loc = state.current_location()
    npc_ids = [
        npc_id
        for npc_id, npc in state.npcs.items()
        if npc.is_present_at(state.current_location_id, state)
    ]
    exits = [e.destination_id for e in loc.available_exits(state)]
    return (
        f"location: {state.current_location_id}\n"
        f"npcs_present: {', '.join(npc_ids) or 'none'}\n"
        f"exits: {', '.join(exits) or 'none'}\n"
        f"loop: {state.loop_number}\n"
        f"queue_position: {state.queue_position}"
    )
