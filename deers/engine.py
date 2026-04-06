"""GameEngine: top-level orchestrator for game input/output."""

from __future__ import annotations

from deers.actions import ActionResolver, ResolutionFailure
from deers.clock import day_name
from deers.claude_client import ClaudeClient, ClaudeUnavailable
from deers.conditions import ConditionScheduler
from deers.dialogue import DialogueEngine
from deers.models import ParsedAction, TerminalCondition
from deers.narrator import NarratorEngine
from deers.parser import InputParser, _keyword_parse
from deers.persistence import load_narrator_cache, save_game, save_narrator_cache
from deers.state import GameState


# ---------------------------------------------------------------------------
# Cold-start intro (shown once, on the first loop of a new game)
# ---------------------------------------------------------------------------

_COLD_START_TEXT = """\
Monday. 0845. You have an appointment for CAC in-processing at 0900, Building 23.

The Common Access Card is required for network access, facility entry, and \
existence in any official capacity on this installation. You do not have one. \
Getting one is why you are here.

Your contracting officer has confirmed your start date is Friday. It is \
currently Monday. This should be enough time.

─────────────────────────────────────────────
Type HELP for available commands.
Type EXAMINE DEERS to see what the system has on file for you.
Type STATUS at any time to check your situation.
─────────────────────────────────────────────\
"""


class GameEngine:
    """
    Orchestrates the game loop. Claude components (parser, narrator, dialogue)
    are None until Phase 5-7. All Claude calls have authored fallbacks.
    """

    def __init__(self, player_name: str, api_key: str | None = None):
        self.state = GameState.new_game(player_name)
        self.resolver = ActionResolver()
        self.scheduler = ConditionScheduler(self.state.content)
        self.api_key = api_key
        self._game_over: bool = False

        # Phase 5-7: Claude components (None if no api_key or anthropic not installed)
        self.parser: InputParser | None = None
        self.narrator: NarratorEngine | None = None
        self.dialogue: DialogueEngine | None = None

        if api_key:
            try:
                client = ClaudeClient(api_key)
                self.parser = InputParser.from_content(client, self.state.content)
                narrator_cache = load_narrator_cache()
                self.narrator = NarratorEngine.from_content(client, self.state.content, narrator_cache)
                self.dialogue = DialogueEngine.from_content(client, self.state.content)
            except ClaudeUnavailable:
                pass  # anthropic package not installed; fallbacks will be used

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Persist game state and narrator cache (called on loop reset and quit)."""
        save_game(self.state)
        if self.narrator is not None:
            save_narrator_cache(self.narrator.cache)

    def start(self) -> str:
        """Return the opening description, with cold-start intro for fresh games."""
        parts = []
        if self.state.loop_number == 1:
            parts.append(_COLD_START_TEXT.format(name=self.state.player_name))
        parts.append(self._status_line())
        parts.append(self._describe_current_location())
        return "\n\n".join(parts)

    def handle_input(self, raw: str) -> str:
        """Process one line of player input and return the response."""
        raw = raw.strip()
        if not raw:
            return ""

        # Route to dialogue handler if in a conversation
        if (
            self.state.current_conversation is not None
            and self.state.current_conversation.is_active
        ):
            return self._handle_dialogue(raw)

        parsed = self._parse(raw)

        # If Claude is unsure, ask the player for clarification instead of
        # attempting to execute an ambiguous action.
        if parsed.clarification:
            return parsed.clarification

        return self._process_action(parsed)

    # ------------------------------------------------------------------
    # Internal: action processing
    # ------------------------------------------------------------------

    def _process_action(self, parsed: ParsedAction) -> str:
        # Check terminal conditions before action
        terminal = self.scheduler.evaluate_all(self.state)
        if terminal:
            return self._handle_terminal(terminal)

        result = self.resolver.resolve(parsed, self.state)
        if isinstance(result, ResolutionFailure):
            self.state.morale.apply("action_failed")
            return result.message

        execution = result.execute(self.state)
        for event in execution.events:
            self.state.apply_event(event)

        # Check terminal conditions after action
        terminal = self.scheduler.evaluate_all(self.state)
        if terminal:
            return self._handle_terminal(terminal)

        # Check for loop reset (office closed)
        if self.state.should_loop():
            return self._handle_loop_reset()

        # Build output
        parts: list[str] = []
        if execution.message:
            parts.append(execution.message)
        parts.append(self._status_line())
        parts.append(self._describe_current_location())
        return "\n\n".join(parts)

    def _handle_loop_reset(self) -> str:
        self.state.trigger_reset()
        self.save()
        tomorrow = day_name(self.state.loop_number)
        if self.state.loop_number > 4:
            day_line = f"You drive home. Tomorrow is {tomorrow}. Your start date is {tomorrow}."
        else:
            day_line = f"You drive home. Tomorrow is {tomorrow}."
        parts = [
            f"The office closes at 4:00 PM. The clerk does not say goodbye.\n{day_line}",
            self._status_line(),
            self._describe_current_location(),
        ]
        return "\n\n".join(parts)

    @property
    def is_game_over(self) -> bool:
        return self._game_over

    def _handle_terminal(self, condition: TerminalCondition) -> str:
        self._game_over = True
        return condition.message

    # ------------------------------------------------------------------
    # Internal: dialogue
    # ------------------------------------------------------------------

    def _handle_dialogue(self, raw: str) -> str:
        """Route to DialogueEngine when available; fall back to keyword stub."""
        if self.dialogue:
            npc_response = self.dialogue.respond(raw, self.state)
            # If the conversation just ended, append the updated world state.
            conv = self.state.current_conversation
            if conv is None or not conv.is_active:
                parts = [p for p in [npc_response, self._status_line(), self._describe_current_location()] if p]
                return "\n\n".join(parts)
            return npc_response

        # ---- Keyword stub (no Claude dialogue configured) ----
        conv = self.state.current_conversation
        if conv is None:
            return ""

        npc = self.state.npcs.get(conv.npc_id)
        close_words = {"leave", "bye", "goodbye", "exit", "walk away", "enough", "later"}

        if any(word in raw.lower() for word in close_words):
            effects = conv.close()
            if npc and effects["trust_delta"]:
                npc.relationship.trust = max(0, npc.relationship.trust + effects["trust_delta"])
            for key in effects.get("knowledge_gained", []):
                self.state.permanent_knowledge.add(key)
            self.state.morale.apply_delta(effects.get("morale_delta", 0))
            self.state.current_conversation = None
            parts = [
                "You step away from the conversation.",
                self._status_line(),
                self._describe_current_location(),
            ]
            return "\n\n".join(parts)

        conv.add_player(raw)
        response = npc.card.fallback_line if npc else "..."
        conv.add_npc(response)

        if conv.is_exhausted():
            conv.close()
            self.state.current_conversation = None
            return (
                f'{npc.display_name(self.state) if npc else "They"}: "{response}"\n\n'
                "The conversation has reached its natural end."
            )

        return f'{npc.display_name(self.state) if npc else "They"}: "{response}"'

    # ------------------------------------------------------------------
    # Internal: parsing
    # ------------------------------------------------------------------

    def _parse(self, raw: str) -> ParsedAction:
        """Claude parser when available; keyword fallback otherwise."""
        if self.parser:
            return self.parser.parse(raw, self.state)
        return _keyword_parse(raw)

    # ------------------------------------------------------------------
    # Internal: description (Phase 3 static text — replaced by NarratorEngine in Phase 6)
    # ------------------------------------------------------------------

    def _describe_current_location(self) -> str:
        if self.narrator:
            return self.narrator.describe_location(self.state)
        loc = self.state.current_location()
        npcs_here = [
            npc.display_name(self.state)
            for npc in loc.present_npcs(self.state)
        ]
        desc = loc.static_description
        if npcs_here:
            desc += f"\n\nPresent: {', '.join(npcs_here)}."
        exits = [e.destination_id for e in loc.available_exits(self.state)]
        if exits:
            desc += f"\nExits: {', '.join(exits)}."
        return desc

    def _status_line(self) -> str:
        s = self.state
        if s.queue_position is None:
            queue_str = "—"
        elif s.queue_position == 0:
            queue_str = "NEXT"
        else:
            queue_str = str(s.queue_position)
        return (
            f"[Loop {s.loop_number} | "
            f"{day_name(s.loop_number)} {s.clock.time_display()} | "
            f"Morale: {s.morale.bar()} {s.morale.percentage()}% | "
            f"Queue: {queue_str}]"
        )
