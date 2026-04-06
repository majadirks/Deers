"""GameEngine: top-level orchestrator for game input/output."""

from __future__ import annotations

from deers.actions import ActionResolver, ResolutionFailure
from deers.clock import day_name
from deers.conditions import ConditionScheduler
from deers.models import ParsedAction, TerminalCondition
from deers.persistence import save_game
from deers.state import GameState


class GameEngine:
    """
    Orchestrates the game loop. Claude components (parser, narrator, dialogue)
    are None until Phase 5-7. All Claude calls have authored fallbacks.
    """

    def __init__(self, player_name: str, api_key: str | None = None):
        self.state = GameState.new_game(player_name)
        self.resolver = ActionResolver()
        self.scheduler = ConditionScheduler()
        self.api_key = api_key

        # Claude components — wired in Phase 5-7
        self.parser = None
        self.narrator = None
        self.dialogue = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self) -> str:
        """Return the opening description."""
        return self._status_line() + "\n\n" + self._describe_current_location()

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
        save_game(self.state)
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

    def _handle_terminal(self, condition: TerminalCondition) -> str:
        return condition.message

    # ------------------------------------------------------------------
    # Internal: dialogue (Phase 3 stub — replaced by DialogueEngine in Phase 7)
    # ------------------------------------------------------------------

    def _handle_dialogue(self, raw: str) -> str:
        """
        Phase 3 stub: simple keyword dialogue without Claude.
        Returns NPC fallback line for most input; closes on leave/bye.
        """
        if self.dialogue:
            return self.dialogue.respond(raw, self.state)

        conv = self.state.current_conversation
        if conv is None:
            return ""

        npc = self.state.npcs.get(conv.npc_id)
        close_words = {"leave", "bye", "goodbye", "exit", "walk away", "enough", "later"}

        if any(word in raw.lower() for word in close_words):
            effects = conv.close()
            if npc and effects["trust_delta"]:
                npc.relationship.trust = max(
                    0, npc.relationship.trust + effects["trust_delta"]
                )
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

        # Record turns
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
    # Internal: parsing (Phase 3 keyword parser — replaced by Claude in Phase 5)
    # ------------------------------------------------------------------

    def _parse(self, raw: str) -> ParsedAction:
        if self.parser:
            return self.parser.parse(raw, self.state)
        return self._simple_parse(raw)

    def _simple_parse(self, raw: str) -> ParsedAction:
        """Keyword parser. Replaced by Claude InputParser in Phase 5."""
        tokens = raw.strip().split()
        if not tokens:
            return ParsedAction(verb="EXAMINE", target="location")
        verb = tokens[0].upper()
        target = " ".join(tokens[1:]).lower() if len(tokens) > 1 else ""
        return ParsedAction(verb=verb, target=target)

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
        return (
            f"[Loop {s.loop_number} | "
            f"{day_name(s.loop_number)} {s.clock.time_display()} | "
            f"Morale: {s.morale.bar()} {s.morale.percentage()}% | "
            f"Queue: {s.queue_position if s.queue_position is not None else '—'}]"
        )
