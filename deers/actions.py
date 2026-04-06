"""Action, ResolutionFailure, ExecutionResult, and ActionResolver.

Each verb handler builds an Action with:
  - conditions: checked at resolve time; first failure → ResolutionFailure
  - effects: Callable[[GameState], GameEvent | None]; mutate state and return events
  - message: str or Callable[[GameState], str]; displayed after execution
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from deers.inventory import DocumentFactory, DocumentType
from deers.locations import Condition
from deers.models import DocumentFlaw, GameEvent, ParsedAction
from deers.npcs import ConversationBuffer

if TYPE_CHECKING:
    from deers.state import GameState


# ---------------------------------------------------------------------------
# Core types
# ---------------------------------------------------------------------------

@dataclass
class ResolutionFailure:
    message: str


@dataclass
class ExecutionResult:
    events: list[GameEvent]
    message: str = ""


@dataclass
class Action:
    verb: str
    target: str
    conditions: list[Condition]
    effects: list[Callable[["GameState"], GameEvent | None]]
    message: str | Callable[["GameState"], str] = ""

    def execute(self, state: "GameState") -> ExecutionResult:
        events: list[GameEvent] = []
        for effect in self.effects:
            event = effect(state)
            if event is not None:
                events.append(event)
        msg = self.message(state) if callable(self.message) else self.message
        return ExecutionResult(events=events, message=msg)


# ---------------------------------------------------------------------------
# Target-resolution helpers
# ---------------------------------------------------------------------------

# Maps informal target strings to location ids.
_EXIT_ALIASES: dict[str, str] = {
    "gate": "installation_gate",
    "north": "installation_gate",
    "inside": "waiting_room",
    "deers": "waiting_room",
    "office": "waiting_room",
    "window": "queue_window",
    "counter": "queue_window",
    "vending": "vending_alcove",
    "alcove": "vending_alcove",
    "snack": "vending_alcove",
    "library": "base_library",
    "building_47": "base_library",
    "supervisor": "supervisors_door",
    "boss": "supervisors_door",
    "parking": "parking_lot",
    "lot": "parking_lot",
    "outside": "parking_lot",
    "waiting_room": "waiting_room",
    "queue_window": "queue_window",
    "installation_gate": "installation_gate",
    "vending_alcove": "vending_alcove",
    "base_library": "base_library",
    "supervisors_door": "supervisors_door",
    "parking_lot": "parking_lot",
}

# Maps informal target strings to NPC ids.
_NPC_ALIASES: dict[str, list[str]] = {
    "clerk": ["clerk", "window", "worker", "person"],
    "e7": ["e7", "veteran", "soldier", "sergeant", "old", "uniform", "nco", "staff", "guy", "man"],
    "contractor": ["contractor", "other_contractor", "civilian", "nervous"],
    "queue_cutter": ["cutter", "queue_cutter", "rude", "pushy"],
    "supervisor": ["supervisor", "boss", "manager"],
}

# Maps informal target strings to DocumentType.
_DOC_ALIASES: dict[str, DocumentType] = {
    "passport": DocumentType.PASSPORT,
    "drivers_license": DocumentType.DRIVERS_LICENSE,
    "license": DocumentType.DRIVERS_LICENSE,
    "dl": DocumentType.DRIVERS_LICENSE,
    "id": DocumentType.DRIVERS_LICENSE,
    "birth_certificate": DocumentType.BIRTH_CERTIFICATE,
    "birth": DocumentType.BIRTH_CERTIFICATE,
    "certificate": DocumentType.BIRTH_CERTIFICATE,
    "sf86": DocumentType.SF86_EXTRACT,
    "sf-86": DocumentType.SF86_EXTRACT,
    "extract": DocumentType.SF86_EXTRACT,
    "appointment": DocumentType.APPOINTMENT_EMAIL,
    "email": DocumentType.APPOINTMENT_EMAIL,
    "confirmation": DocumentType.APPOINTMENT_EMAIL,
    "fso_letter": DocumentType.SECURITY_OFFICER_LETTER,
    "security_officer_letter": DocumentType.SECURITY_OFFICER_LETTER,
    "fso": DocumentType.SECURITY_OFFICER_LETTER,
    "letter": DocumentType.SECURITY_OFFICER_LETTER,
    "vehicle": DocumentType.VEHICLE_PASS_REQUEST,
    "vehicle_pass": DocumentType.VEHICLE_PASS_REQUEST,
    "form": DocumentType.VEHICLE_PASS_REQUEST,
    "contractor_letter": DocumentType.CONTRACTOR_LETTER,
    "two_forms": DocumentType.TWO_FORMS_ID_COMBO,
    "combo": DocumentType.TWO_FORMS_ID_COMBO,
    "previous_cac": DocumentType.PREVIOUS_CAC,
    "old_cac": DocumentType.PREVIOUS_CAC,
    "cac": DocumentType.PREVIOUS_CAC,
}

# Documents that cannot be dropped.
_UNDROPABLE = frozenset({
    DocumentType.APPOINTMENT_EMAIL,
})


# ---------------------------------------------------------------------------
# ActionResolver
# ---------------------------------------------------------------------------

class ActionResolver:

    def resolve(
        self, parsed: ParsedAction, state: "GameState"
    ) -> Action | ResolutionFailure:
        """
        Build and validate an Action for the given parsed input.
        Returns ResolutionFailure if the verb is unknown, the target can't be
        found, or any condition fails.
        """
        verb = parsed.verb.upper()
        handlers = {
            "GO": self._handle_go,
            "TALK": self._handle_talk,
            "EXAMINE": self._handle_examine,
            "TAKE": self._handle_take,
            "USE": self._handle_use,
            "WAIT": self._handle_wait,
            "DROP": self._handle_drop,
            "READ": self._handle_read,
            "HELP": self._handle_help,
            "STATUS": self._handle_status,
        }
        handler = handlers.get(verb)
        if handler is None:
            return ResolutionFailure(
                f"The word '{parsed.verb}' doesn't mean anything here. "
                "Try: GO, TALK, EXAMINE, TAKE, USE, WAIT, DROP, READ, HELP, STATUS."
            )

        action = handler(parsed, state)
        if isinstance(action, ResolutionFailure):
            return action

        # Check all conditions at resolve time
        for cond in action.conditions:
            if not cond.check(state):
                return ResolutionFailure(cond.failure_message)

        return action

    # ------------------------------------------------------------------
    # Verb handlers
    # ------------------------------------------------------------------

    def _handle_go(
        self, parsed: ParsedAction, state: "GameState"
    ) -> Action | ResolutionFailure:
        loc = state.current_location()
        target = parsed.target.lower().strip()

        # Resolve target to a destination id
        dest_id = _EXIT_ALIASES.get(target)
        if dest_id is None:
            # Try partial match on destination id
            for exit_obj in loc.exits:
                if target in exit_obj.destination_id:
                    dest_id = exit_obj.destination_id
                    break

        if dest_id is None:
            available = [e.destination_id for e in loc.exits]
            return ResolutionFailure(
                f"You can't go to '{parsed.target}' from here. "
                f"You could go to: {', '.join(available)}."
                if available else
                "There's nowhere to go from here."
            )

        exit_obj = next(
            (e for e in loc.exits if e.destination_id == dest_id), None
        )
        if exit_obj is None:
            return ResolutionFailure(
                f"There's no way to reach {dest_id} from here."
            )

        dest_loc = state.locations.get(dest_id)
        time_cost = dest_loc.base_time_cost_minutes if dest_loc else 5
        dest_name = dest_loc.name if dest_loc else dest_id

        def move(s: "GameState") -> GameEvent:
            s.clock.advance(time_cost)
            # Tailgating check: entering installation without valid photo ID
            if dest_id == "waiting_room" and s.current_location_id == "installation_gate":
                has_photo_id = (
                    s.inventory.has_valid(DocumentType.PASSPORT)
                    or s.inventory.has_valid(DocumentType.DRIVERS_LICENSE)
                )
                if not has_photo_id:
                    s.tailgating_detected = True
            s.current_location_id = dest_id
            return GameEvent(
                event_type="player_moved",
                payload={"from": loc.id, "to": dest_id},
            )

        return Action(
            verb="GO",
            target=dest_id,
            conditions=exit_obj.conditions,
            effects=[move],
            message=f"You head to {dest_name}.",
        )

    def _handle_talk(
        self, parsed: ParsedAction, state: "GameState"
    ) -> Action | ResolutionFailure:
        npc = self._find_npc(parsed.target, state, present_only=True)
        if npc is None:
            # Check if they exist but aren't here
            npc_anywhere = self._find_npc(parsed.target, state, present_only=False)
            if npc_anywhere:
                return ResolutionFailure(
                    f"{npc_anywhere.display_name(state)} isn't here right now."
                )
            return ResolutionFailure(
                "There's no one by that description here."
            )

        npc_id = npc.npc_id

        def open_conversation(s: "GameState") -> GameEvent:
            s.clock.advance(10)
            s.current_conversation = ConversationBuffer(npc_id=npc_id)
            return GameEvent(
                event_type="conversation_opened",
                payload={"npc_id": npc_id},
            )

        return Action(
            verb="TALK",
            target=npc_id,
            conditions=[],
            effects=[open_conversation],
            message=lambda s: (
                f'{s.npcs[npc_id].display_name(s)}: '
                f'"{s.npcs[npc_id].card.fallback_line}"'
            ),
        )

    def _handle_examine(
        self, parsed: ParsedAction, state: "GameState"
    ) -> Action | ResolutionFailure:
        target = parsed.target.lower().strip()
        loc = state.current_location()

        # Examine current location
        if not target or target in ("location", "room", "area", "around", "here", "everything"):
            return Action(
                verb="EXAMINE",
                target="location",
                conditions=[],
                effects=[
                    lambda s: GameEvent(event_type="examine_location")
                ],
                message=lambda s: s.current_location().static_description,
            )

        # Try NPC present at this location
        npc = self._find_npc(target, state, present_only=True)
        if npc:
            return Action(
                verb="EXAMINE",
                target=npc.npc_id,
                conditions=[],
                effects=[],
                message=f"{npc.display_name(state)}: {npc.card.voice_description}",
            )

        # Try feature at current location
        feature = next(
            (
                f for f in loc.features
                if target in f.id.lower() or target in f.name.lower()
            ),
            None,
        )
        if feature:
            return Action(
                verb="EXAMINE",
                target=feature.id,
                conditions=[],
                effects=[],
                message=feature.examine_text,
            )

        # Try document in inventory
        doc = self._find_document(target, state)
        if doc:
            flaw_text = doc.describe_flaws()
            msg = f"{doc.display_name}: {doc.fallback_examine_text}"
            if flaw_text != "No apparent issues.":
                msg += f"\n{flaw_text}"
            return Action(
                verb="EXAMINE",
                target=doc.doc_type.value,
                conditions=[],
                effects=[],
                message=msg,
            )

        return ResolutionFailure(
            f"You don't see anything called '{parsed.target}' to examine."
        )

    def _handle_take(
        self, parsed: ParsedAction, state: "GameState"
    ) -> Action | ResolutionFailure:
        target = parsed.target.lower().strip()
        loc = state.current_location()

        # Number dispenser
        if any(kw in target for kw in ("number", "dispenser", "ticket", "slip")):
            has_dispenser = any(f.id == "number_dispenser" for f in loc.features)
            if not has_dispenser:
                return ResolutionFailure("There's no number dispenser here.")
            if state.queue_position is not None:
                return ResolutionFailure(
                    f"You already have a number. There are {state.queue_position} people ahead."
                )

            def take_number(s: "GameState") -> GameEvent:
                position = random.randint(5, 12)
                s.queue_position = position
                return GameEvent(
                    event_type="queue_number_taken",
                    payload={"position": position},
                )

            return Action(
                verb="TAKE",
                target="number_dispenser",
                conditions=[],
                effects=[take_number],
                message=lambda s: (
                    f"You take a number. The slip reads {s.queue_position}. "
                    f"There are {s.queue_position} people ahead of you."
                ),
            )

        return ResolutionFailure(
            f"There's nothing here called '{parsed.target}' to take."
        )

    def _handle_use(
        self, parsed: ParsedAction, state: "GameState"
    ) -> Action | ResolutionFailure:
        target = parsed.target.lower().strip()
        loc = state.current_location()

        # Number dispenser — USE acts like TAKE
        if any(kw in target for kw in ("number", "dispenser", "ticket")):
            return self._handle_take(
                ParsedAction(verb="TAKE", target=target), state
            )

        # Find a feature with USE interaction
        feature = next(
            (
                f for f in loc.features
                if target in f.id.lower() or target in f.name.lower()
            ),
            None,
        )
        if feature is None:
            return ResolutionFailure(
                f"There's nothing here called '{parsed.target}' to use."
            )

        event_type = feature.interactions.get("USE")
        if event_type is None:
            return ResolutionFailure(
                f"You can't use the {feature.name} that way."
            )

        return self._dispatch_feature_use(feature, event_type, state)

    def _dispatch_feature_use(
        self, feature, event_type: str, state: "GameState"
    ) -> Action | ResolutionFailure:
        """Dispatch a USE interaction to its specific logic."""

        if event_type == "player_uses_vending":
            def buy_coffee(s: "GameState") -> GameEvent:
                s.morale.apply("coffee_consumed")
                return GameEvent(event_type="coffee_consumed", payload={"item": "coffee"})

            return Action(
                verb="USE",
                target=feature.id,
                conditions=[],
                effects=[buy_coffee],
                message=(
                    "You feed $1.75 into the machine. A paper cup descends. "
                    "The coffee is approximately the temperature of a decision you "
                    "cannot take back. You drink it standing up."
                ),
            )

        if event_type == "player_drinks_water":
            def drink_water(s: "GameState") -> GameEvent:
                s.morale.apply("water_consumed")
                return GameEvent(event_type="water_consumed", payload={"item": "water"})

            return Action(
                verb="USE",
                target=feature.id,
                conditions=[],
                effects=[drink_water],
                message="You drink from the fountain. The water is cold. This helps, slightly.",
            )

        if event_type == "player_uses_photocopier":
            copyable = [d for d in state.inventory.documents if d.can_be_photocopied]
            if not copyable:
                return ResolutionFailure(
                    "You don't have any documents that can be photocopied."
                )
            # Copy the first copyable document (Phase 7 makes this interactive)
            doc_to_copy = copyable[0]

            def make_copy(s: "GameState") -> GameEvent:
                factory = DocumentFactory(random.Random(), s.content)
                copy = factory.make(doc_to_copy.doc_type, force_flaws=[])
                s.inventory.add(copy)
                s.permanent_knowledge.add("PHOTOCOPY_TRICK_KNOWN")
                s.clock.advance(5)
                return GameEvent(
                    event_type="document_photocopied",
                    payload={"doc": doc_to_copy.doc_type.value},
                    is_permanent=True,
                )

            return Action(
                verb="USE",
                target=feature.id,
                conditions=[],
                effects=[make_copy],
                message=(
                    f"You photocopy your {doc_to_copy.display_name}. "
                    "The machine works. Ten cents. The copy is clean."
                ),
            )

        # Generic feature interaction
        def generic_use(s: "GameState") -> GameEvent:
            return GameEvent(event_type=event_type)

        return Action(
            verb="USE",
            target=feature.id,
            conditions=[],
            effects=[generic_use],
            message=f"You interact with the {feature.name}.",
        )

    def _handle_wait(
        self, parsed: ParsedAction, state: "GameState"
    ) -> Action | ResolutionFailure:
        def do_wait(s: "GameState") -> GameEvent:
            s.clock.advance(30)
            s.morale.apply("wait")
            if s.queue_position is not None and s.queue_position > 0:
                s.queue_position = max(0, s.queue_position - random.randint(1, 2))
            return GameEvent(event_type="wait", payload={"minutes": 30})

        return Action(
            verb="WAIT",
            target="",
            conditions=[],
            effects=[do_wait],
            message=lambda s: (
                "Time passes."
                + (
                    f" Queue position: {s.queue_position} ahead of you."
                    if s.queue_position and s.queue_position > 0
                    else " You should be called soon."
                    if s.queue_position == 0
                    else ""
                )
            ),
        )

    def _handle_drop(
        self, parsed: ParsedAction, state: "GameState"
    ) -> Action | ResolutionFailure:
        target = parsed.target.lower().strip()
        doc = self._find_document(target, state)
        if doc is None:
            return ResolutionFailure(
                f"You're not carrying anything called '{parsed.target}'."
            )
        if doc.doc_type in _UNDROPABLE:
            return ResolutionFailure(
                f"You should keep your {doc.display_name}."
            )

        def drop_doc(s: "GameState") -> GameEvent:
            s.inventory.remove(doc)
            return GameEvent(
                event_type="document_dropped",
                payload={"doc": doc.doc_type.value},
            )

        return Action(
            verb="DROP",
            target=doc.doc_type.value,
            conditions=[],
            effects=[drop_doc],
            message=f"You leave the {doc.display_name} behind.",
        )

    def _handle_read(
        self, parsed: ParsedAction, state: "GameState"
    ) -> Action | ResolutionFailure:
        target = parsed.target.lower().strip()
        doc = self._find_document(target, state)
        if doc is None:
            return ResolutionFailure(
                f"You're not carrying anything to read called '{parsed.target}'."
            )

        def read_doc(s: "GameState") -> GameEvent:
            s.clock.advance(8)
            return GameEvent(
                event_type="document_read",
                payload={"doc": doc.doc_type.value},
            )

        flaw_section = doc.describe_flaws()
        msg = f"{doc.display_name}\n{doc.description}"
        if flaw_section != "No apparent issues.":
            msg += f"\n\nNote: {flaw_section}"

        return Action(
            verb="READ",
            target=doc.doc_type.value,
            conditions=[],
            effects=[read_doc],
            message=msg,
        )

    def _handle_help(
        self, parsed: ParsedAction, state: "GameState"
    ) -> Action | ResolutionFailure:
        help_text = (
            "DEERS IN THE HEADLIGHTS — Available Commands\n"
            "─────────────────────────────────────────────\n"
            "  GO [place]      Move to a location\n"
            "  TALK [person]   Start a conversation\n"
            "  EXAMINE [thing] Look at something closely\n"
            "  TAKE [thing]    Pick something up\n"
            "  USE [thing]     Interact with something\n"
            "  WAIT            Pass 30 minutes (advances queue)\n"
            "  DROP [item]     Put something down\n"
            "  READ [doc]      Read a document in detail\n"
            "  STATUS          Check your current status\n"
            "  HELP            Show this message\n"
            "\n"
            "You can type naturally — 'go to the waiting room', 'talk to the old guy'.\n"
            "The system will do its best.\n"
            "\n"
            "Objective: get your Common Access Card issued before Monday."
        )
        return Action(
            verb="HELP",
            target="",
            conditions=[],
            effects=[],
            message=help_text,
        )

    def _handle_status(
        self, parsed: ParsedAction, state: "GameState"
    ) -> Action | ResolutionFailure:
        def build_status(s: "GameState") -> str:
            loc = s.current_location()
            day = s.clock.day_display()
            time = s.clock.time_display()
            morale_bar = s.morale.bar()
            morale_pct = s.morale.percentage()
            queue_str = str(s.queue_position) if s.queue_position is not None else "—"
            corruptions = [f.display_name for f in s.deers.corrupted_fields()]
            docs = [d.display_name for d in s.inventory.documents]

            lines = [
                f"[Loop {s.loop_number} | {day} {time} | Morale: {morale_bar} {morale_pct}% | Queue: {queue_str}]",
                f"Location: {loc.name}",
                f"DEERS issues: {', '.join(corruptions) if corruptions else 'None detected'}",
                f"Documents: {', '.join(docs) if docs else 'None'}",
            ]
            return "\n".join(lines)

        return Action(
            verb="STATUS",
            target="",
            conditions=[],
            effects=[],
            message=lambda s: build_status(s),
        )

    # ------------------------------------------------------------------
    # Target-resolution helpers
    # ------------------------------------------------------------------

    def _find_exit_dest(self, target: str, state: "GameState") -> str | None:
        """Resolve a target string to a destination location id."""
        dest = _EXIT_ALIASES.get(target)
        if dest:
            return dest
        # Partial match on destination id
        for exit_obj in state.current_location().exits:
            if target in exit_obj.destination_id:
                return exit_obj.destination_id
        return None

    def _find_npc(
        self, target: str, state: "GameState", present_only: bool = True
    ):
        """Return the NPC matching target, optionally restricted to present NPCs."""
        target = target.lower()
        for npc_id, keywords in _NPC_ALIASES.items():
            if any(kw in target for kw in keywords):
                npc = state.npcs.get(npc_id)
                if npc is None:
                    continue
                if present_only and not npc.is_present_at(state.current_location_id, state):
                    continue
                return npc
        # Direct id match
        npc = state.npcs.get(target)
        if npc:
            if present_only and not npc.is_present_at(state.current_location_id, state):
                return None
            return npc
        return None

    def _find_document(self, target: str, state: "GameState"):
        """Return the first matching document in the player's inventory."""
        target = target.lower()
        # Exact alias match
        doc_type = _DOC_ALIASES.get(target)
        if doc_type:
            return state.inventory.get(doc_type)
        # Partial match against display names and type ids
        for doc in state.inventory.documents:
            if (
                target in doc.doc_type.value.lower()
                or target in doc.display_name.lower()
            ):
                return doc
        return None
