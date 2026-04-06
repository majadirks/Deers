"""DialogueEngine: trust-gated, topic-aware NPC conversations via Claude.

Flow per player turn:
  1. Check for close intent (keyword) → commit effects, end conversation.
  2. Detect topic via Claude topic_parser (fast, 64-token call).
  3. Generate in-character NPC response via Claude chat() with full history.
  4. Accrue morale/knowledge side effects for the detected topic.
  5. On conversation close (explicit or exhausted): award trust, commit all
     accumulated effects to permanent game state.

Fallbacks on ClaudeUnavailable:
  - Topic detection → "freeform" (no topic-specific effects accrued).
  - Response generation → npc.card.fallback_line.
  All fallbacks are silent; the conversation continues on the next turn.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from jinja2 import Template

from deers.claude_client import ClaudeClient, ClaudeUnavailable

if TYPE_CHECKING:
    from deers.npcs import ConversationBuffer, NPC
    from deers.state import GameState

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CLOSE_WORDS: frozenset[str] = frozenset(
    {"leave", "bye", "goodbye", "exit", "walk away", "enough", "later", "done"}
)

# Minimum confidence from topic_parser to treat a match as real.
_TOPIC_CONFIDENCE: float = 0.6

# NPC response token budget: ~80 words cap per narrator spec; 150 is safe.
_RESPONSE_MAX_TOKENS: int = 150
# Topic detection is a lightweight classification; 64 tokens is plenty.
_TOPIC_MAX_TOKENS: int = 64

# Minimum turns exchanged in a conversation to award a trust increment.
_MIN_TURNS_FOR_TRUST: int = 2

# ---------------------------------------------------------------------------
# Knowledge unlock tables (game logic — not in TOML)
# ---------------------------------------------------------------------------

# Keys unlocked when (npc_id, topic) is first discussed.
_TOPIC_KNOWLEDGE: dict[tuple[str, str], list[str]] = {
    ("e7", "workaround"): ["WORKAROUND_KNOWN"],
    ("e7", "base_library_location"): ["LIBRARY_LOCATION_KNOWN"],
    ("contractor", "base_library_location"): ["LIBRARY_LOCATION_KNOWN"],
    ("e7", "supervisor_name"): ["SUPERVISOR_NAME_KNOWN"],
}

# Keys unlocked when npc trust first reaches or exceeds the given threshold.
_TRUST_KNOWLEDGE: dict[str, list[tuple[int, str]]] = {
    "e7": [(1, "CLERK_NAME_KNOWN")],
    "clerk": [(2, "TRANSCENDENCE_STEP_1")],
}

# Human-readable trust labels for the dialogue system prompt.
_TRUST_LABELS: dict[int, str] = {
    0: "Stranger",
    1: "Recognized",
    2: "Familiar",
    3: "Trusted",
    4: "Confiding",
}


# ---------------------------------------------------------------------------
# DialogueEngine
# ---------------------------------------------------------------------------

class DialogueEngine:
    """
    Manages one conversational turn: detect topic, generate response, accrue
    side effects, close conversation when appropriate.
    """

    def __init__(
        self,
        client: ClaudeClient,
        dialogue_template_str: str,
        topic_parser_system: str,
    ) -> None:
        self._client = client
        self._template = Template(dialogue_template_str)
        self._topic_system = topic_parser_system

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def respond(self, raw: str, state: "GameState") -> str:
        """
        Process one player turn inside an active conversation.
        Returns the formatted NPC line (or close message).
        Does NOT append status line / location — the engine does that.
        """
        conv = state.current_conversation
        if conv is None or not conv.is_active:
            return ""

        npc = state.npcs.get(conv.npc_id)
        if npc is None:
            return ""

        # ---- close intent ----
        if _is_close_intent(raw):
            return self._do_close(npc, state, conv)

        # ---- topic detection ----
        topic = self._detect_topic(raw, npc)

        # ---- response generation ----
        system = self._render_system(npc, state)
        messages = conv.to_messages() + [{"role": "user", "content": raw}]
        npc_text = self._generate_response(system, messages, fallback=npc.card.fallback_line)

        # ---- record turn ----
        conv.add_player(raw)
        conv.add_npc(npc_text)

        # ---- side effects ----
        self._accrue_turn_effects(topic, npc, state, conv)
        if topic != "freeform":
            npc.relationship.record_topic(topic)

        # ---- exhaustion check ----
        if conv.is_exhausted():
            return self._do_exhausted(npc, state, conv, npc_text)

        return f'{npc.display_name(state)}: "{npc_text}"'

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_content(cls, client: ClaudeClient, content: dict) -> "DialogueEngine":
        dialogue_template = content["prompts"]["dialogue"]["system_template"]
        topic_parser_system = content["prompts"]["dialogue_topic_parser"]["system"]
        return cls(client, dialogue_template, topic_parser_system)

    # ------------------------------------------------------------------
    # Close paths
    # ------------------------------------------------------------------

    def _do_close(
        self,
        npc: "NPC",
        state: "GameState",
        conv: "ConversationBuffer",
    ) -> str:
        _maybe_award_trust(conv, npc)
        effects = conv.close()
        self._commit_effects(effects, npc, state)
        state.current_conversation = None
        return "You step away from the conversation."

    def _do_exhausted(
        self,
        npc: "NPC",
        state: "GameState",
        conv: "ConversationBuffer",
        last_npc_text: str,
    ) -> str:
        _maybe_award_trust(conv, npc)
        effects = conv.close()
        self._commit_effects(effects, npc, state)
        state.current_conversation = None
        return (
            f'{npc.display_name(state)}: "{last_npc_text}"\n\n'
            "The conversation has reached its natural end."
        )

    # ------------------------------------------------------------------
    # Topic detection
    # ------------------------------------------------------------------

    def _detect_topic(self, raw: str, npc: "NPC") -> str:
        available = npc.available_topics()
        if not available:
            return "freeform"
        try:
            return self._call_topic_parser(raw, available)
        except ClaudeUnavailable:
            return "freeform"

    def _call_topic_parser(self, raw: str, topics: list[str]) -> str:
        topic_list = "\n".join(f"- {t}" for t in topics)
        user_msg = f"PLAYER INPUT: {raw}\n\nAVAILABLE TOPICS:\n{topic_list}"
        text = self._client.complete(
            self._topic_system, user_msg, max_tokens=_TOPIC_MAX_TOKENS
        )
        return _parse_topic_response(text)

    # ------------------------------------------------------------------
    # Response generation
    # ------------------------------------------------------------------

    def _generate_response(
        self, system: str, messages: list[dict], fallback: str
    ) -> str:
        try:
            return self._client.chat(system, messages, max_tokens=_RESPONSE_MAX_TOKENS)
        except ClaudeUnavailable:
            return fallback

    def _render_system(self, npc: "NPC", state: "GameState") -> str:
        """Render the Jinja2 dialogue system prompt for this NPC + state."""
        available = npc.available_topics()
        content_lines = []
        for t in available:
            desc = npc.card.knowledge_map.get(t, "")
            threshold = npc.card.trust_thresholds.get(t, 0)
            content_lines.append(f"  [{t} | trust >= {threshold}] {desc}")
        unlockable = (
            "\n".join(content_lines)
            if content_lines
            else "  (no specific information to reveal at current trust level)"
        )

        return self._template.render(
            npc_name=npc.display_name(state),
            archetype=npc.card.archetype.value,
            voice_description=npc.card.voice_description,
            trust_level=npc.relationship.trust,
            trust_label=_TRUST_LABELS.get(min(npc.relationship.trust, 4), "Confiding"),
            loop_number=state.loop_number,
            morale_bracket=state.morale.bracket(),
            time_of_day=state.clock.time_display(),
            location_name=state.current_location().name,
            unlockable_content=unlockable,
        )

    # ------------------------------------------------------------------
    # Effects
    # ------------------------------------------------------------------

    def _accrue_turn_effects(
        self,
        topic: str,
        npc: "NPC",
        state: "GameState",
        conv: "ConversationBuffer",
    ) -> None:
        """Accrue morale and knowledge effects for the current turn's topic."""
        if topic == "freeform":
            return

        morale_delta = npc.card.morale_deltas.get(topic, 0)

        # Only unlock keys not already known (permanent or pending)
        knowledge_keys = [
            k
            for k in _TOPIC_KNOWLEDGE.get((npc.npc_id, topic), [])
            if k not in state.permanent_knowledge
            and k not in conv.pending_knowledge
        ]

        if morale_delta or knowledge_keys:
            conv.accrue_effects(
                morale_delta=morale_delta,
                knowledge=knowledge_keys if knowledge_keys else None,
            )

    def _commit_effects(
        self, effects: dict, npc: "NPC", state: "GameState"
    ) -> None:
        """Apply accumulated ConversationBuffer effects to permanent game state."""
        # Trust (capped 0–4)
        delta = effects.get("trust_delta", 0)
        if delta:
            npc.relationship.trust = max(0, min(4, npc.relationship.trust + delta))

        # Morale
        state.morale.apply_delta(effects.get("morale_delta", 0))

        # Knowledge
        for key in effects.get("knowledge_gained", []):
            state.permanent_knowledge.add(key)
            if key not in npc.relationship.knowledge_revealed:
                npc.relationship.knowledge_revealed.append(key)

        # Trust-milestone unlocks (checked after trust is updated)
        self._check_trust_unlocks(npc, state)

    def _check_trust_unlocks(self, npc: "NPC", state: "GameState") -> None:
        """Grant permanent knowledge keys when trust milestones are reached."""
        for min_trust, key in _TRUST_KNOWLEDGE.get(npc.npc_id, []):
            if npc.relationship.trust >= min_trust:
                state.permanent_knowledge.add(key)


# ---------------------------------------------------------------------------
# Module-level helpers (exposed for testing)
# ---------------------------------------------------------------------------

def _is_close_intent(raw: str) -> bool:
    """True if the player's input signals they want to end the conversation."""
    lowered = raw.lower().strip()
    return any(word in lowered for word in _CLOSE_WORDS)


def _parse_topic_response(text: str) -> str:
    """
    Parse the JSON response from the topic_parser Claude call.
    Returns the topic string, or "freeform" on any parse failure or low confidence.
    """
    cleaned = re.sub(r"```(?:json)?|```", "", text).strip()
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return "freeform"

    topic = str(data.get("topic") or "freeform").strip()
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    if confidence < _TOPIC_CONFIDENCE:
        return "freeform"
    return topic if topic else "freeform"


def _maybe_award_trust(conv: "ConversationBuffer", npc: "NPC") -> None:
    """Award +1 trust if the conversation was substantive and trust < 4."""
    if conv.turns_taken >= _MIN_TURNS_FOR_TRUST and npc.relationship.trust < 4:
        conv.accrue_effects(trust_delta=1)
