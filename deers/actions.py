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

from deers.clock import day_name
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
            "SUBMIT": self._handle_submit,
            "GIVE": self._handle_submit,    # alias
            "HAND": self._handle_submit,    # alias
        }
        handler = handlers.get(verb)
        if handler is None:
            return ResolutionFailure(
                f"'{parsed.verb}' is not a recognized action. "
                "Try: GO, TALK, EXAMINE, TAKE, USE, SUBMIT, WAIT, DROP, READ, HELP, STATUS."
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
                f"There is no route to '{parsed.target}' from here. "
                f"Possible destinations: {', '.join(available)}."
                if available else
                "There is nowhere to go from here."
            )

        exit_obj = next(
            (e for e in loc.exits if e.destination_id == dest_id), None
        )
        if exit_obj is None:
            return ResolutionFailure(
                f"There is no exit to {dest_id} from here."
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
                    f"{npc_anywhere.display_name(state)} is not here."
                )
            return ResolutionFailure(
                "There is no one here matching that description."
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

        # Examine DEERS record
        if target in ("deers", "record", "my record", "my deers", "deers record", "deers_record"):
            return self._handle_examine_deers(state)

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
            f"There is nothing here called '{parsed.target}'."
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
                return ResolutionFailure(
                    "There is no number dispenser here. "
                    "Numbers are issued in the waiting room."
                )
            if state.queue_position is not None:
                ahead = state.queue_position
                if ahead == 0:
                    return ResolutionFailure("You already have a number. You are next.")
                return ResolutionFailure(
                    f"You already have a number. There are {ahead} people ahead of you."
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
            f"There is nothing here called '{parsed.target}' to take."
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

        # Vending machine aliases: chips, snacks, coffee → working_vending_machine
        if any(kw in target for kw in ("chip", "snack", "crisp", "coffee")):
            vending = next(
                (f for f in loc.features if f.id == "working_vending_machine"), None
            )
            if vending:
                event_type = vending.interactions.get("USE")
                if event_type:
                    return self._dispatch_feature_use(vending, event_type, state, target)

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
                f"There is nothing here called '{parsed.target}' to use."
            )

        event_type = feature.interactions.get("USE")
        if event_type is None:
            return ResolutionFailure(
                f"The {feature.name} does not respond to that."
            )

        return self._dispatch_feature_use(feature, event_type, state, target)

    def _dispatch_feature_use(
        self, feature, event_type: str, state: "GameState", raw_target: str = ""
    ) -> Action | ResolutionFailure:
        """Dispatch a USE interaction to its specific logic."""

        if event_type == "player_uses_vending":
            # Chips if player asked for chips/snacks; otherwise coffee.
            if any(kw in raw_target for kw in ("chip", "snack", "crisp")):
                def buy_chips(s: "GameState") -> GameEvent:
                    s.morale.apply("chips_consumed")
                    return GameEvent(event_type="chips_consumed", payload={"item": "chips"})

                return Action(
                    verb="USE",
                    target=feature.id,
                    conditions=[],
                    effects=[buy_chips],
                    message=(
                        "You buy a bag of chips. The machine dispenses them with the "
                        "reluctant energy of something that has done this ten thousand times. "
                        "They are salt-and-vinegar. You eat them over the trash can."
                    ),
                )

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

        if event_type == "player_uses_payphone":
            if "WORKAROUND_KNOWN" not in state.permanent_knowledge:
                return Action(
                    verb="USE",
                    target=feature.id,
                    conditions=[],
                    effects=[],
                    message=(
                        "You pick up the receiver. There is a dial tone. "
                        "You're not sure what number to call. "
                        "Someone in this building probably knows."
                    ),
                )

            def call_deers_helpdesk(s: "GameState") -> GameEvent:
                s.workaround_called = True
                s.clock.advance(15)
                return GameEvent(event_type="workaround_called", is_permanent=True)

            return Action(
                verb="USE",
                target=feature.id,
                conditions=[],
                effects=[call_deers_helpdesk],
                message=(
                    "You dial the number the E-7 gave you. The hold music is a MIDI "
                    "rendition of something that was once a song. After eleven minutes, "
                    "someone answers."
                ),
            )

        if event_type == "player_submits_via_tray":
            # Document tray at queue_window — delegate to submit logic
            return self._handle_submit(
                type("ParsedAction", (), {"verb": "SUBMIT", "target": "documents"})(),
                state,
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
                    "You have nothing that can be photocopied. "
                    "The machine waits with mechanical patience."
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
                old_pos = s.queue_position
                s.queue_position = max(0, s.queue_position - random.randint(1, 2))
                if s.queue_position < old_pos:
                    s.morale.apply("queue_advanced")
            return GameEvent(event_type="wait", payload={"minutes": 30})

        def wait_message(s: "GameState") -> str:
            base = "Time passes."
            if s.queue_position is None:
                return base
            if s.queue_position == 0:
                return base + " You should be called soon."
            return base + f" There are {s.queue_position} people ahead of you."

        return Action(
            verb="WAIT",
            target="",
            conditions=[],
            effects=[do_wait],
            message=wait_message,
        )

    def _handle_drop(
        self, parsed: ParsedAction, state: "GameState"
    ) -> Action | ResolutionFailure:
        target = parsed.target.lower().strip()
        doc = self._find_document(target, state)
        if doc is None:
            return ResolutionFailure(
                f"You are not carrying anything called '{parsed.target}'."
            )
        if doc.doc_type in _UNDROPABLE:
            return ResolutionFailure(
                f"You should hold onto your {doc.display_name}. "
                "It is why you are here."
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
                f"You are not carrying anything called '{parsed.target}' to read."
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
            "  GO [place]       Move to a location\n"
            "  TALK [person]    Start a conversation\n"
            "  EXAMINE [thing]  Look at something (try: EXAMINE DEERS)\n"
            "  TAKE [thing]     Pick something up\n"
            "  USE [thing]      Interact with something\n"
            "  SUBMIT           Submit documents to the clerk at the window\n"
            "  WAIT             Pass 30 minutes (advances queue)\n"
            "  DROP [item]      Put something down\n"
            "  READ [doc]       Read a document in detail\n"
            "  STATUS           Check your current status\n"
            "  HELP             Show this message\n"
            "\n"
            "You can type naturally — 'go to the waiting room', 'talk to the old guy'.\n"
            "The system will do its best.\n"
            "\n"
            "Objective: get your Common Access Card issued before Friday."
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
            day = day_name(s.loop_number)
            time = s.clock.time_display()
            morale_bar = s.morale.bar()
            morale_pct = s.morale.percentage()
            if s.queue_position is None:
                queue_str = "—"
            elif s.queue_position == 0:
                queue_str = "NEXT"
            else:
                queue_str = str(s.queue_position)
            corruptions = [f.display_name for f in s.deers.corrupted_fields()]
            blocking = [f.display_name for f in s.deers.blocking_corruptions()]
            docs = [d.display_name for d in s.inventory.documents]

            lines = [
                f"[Loop {s.loop_number} | {day} {time} | Morale: {morale_bar} {morale_pct}% | Queue: {queue_str}]",
                f"Location: {loc.name}",
                f"DEERS issues: {', '.join(corruptions) if corruptions else 'None detected'}",
            ]
            if blocking:
                lines.append(f"  Blocking issuance: {', '.join(blocking)}")
            lines.append(f"Documents: {', '.join(docs) if docs else 'None'}")
            return "\n".join(lines)

        return Action(
            verb="STATUS",
            target="",
            conditions=[],
            effects=[],
            message=lambda s: build_status(s),
        )

    def _handle_submit(
        self, parsed: ParsedAction, state: "GameState"
    ) -> Action | ResolutionFailure:
        """Submit documents to the clerk to fix ON_SITE DEERS fields."""
        if state.current_location_id != "queue_window":
            return ResolutionFailure(
                "You are not at the processing window. "
                "Document submission occurs at the processing window."
            )
        if state.queue_position is None:
            return ResolutionFailure(
                "You do not have a queue number. "
                "Take one from the dispenser in the waiting room."
            )

        # Use a closure list so effects can write and message can read.
        result_lines: list[str] = []

        def submit_documents(s: "GameState") -> GameEvent:
            any_fixed = False

            for f in list(s.deers.corrupted_fields()):
                matching = [
                    d for d in s.inventory.documents
                    if d.doc_type.value in f.fixing_documents
                ]
                if not matching:
                    if f.blocking:
                        result_lines.append(
                            f"{f.display_name}: No applicable document in your possession."
                        )
                        s.morale.apply("deers_field_rejected")
                    continue

                fix_result = f.attempt_fix(matching[0])
                result_lines.append(fix_result.message)
                if fix_result.success:
                    any_fixed = True
                    s.morale.apply("deers_field_fixed")
                    # Record field knowledge for corruption-probability mitigation
                    s.permanent_knowledge.add(f"DEERS_FIELD_{f.name}")
                    # TRANSCENDENCE_STEP_2: fixing any field "by accident"
                    s.permanent_knowledge.add("TRANSCENDENCE_STEP_2")
                else:
                    s.morale.apply("deers_field_rejected")

            # Discover IMPOSSIBLE combination if present
            if s.deers.has_impossible_combination():
                if "IMPOSSIBLE_SEEN" not in s.permanent_knowledge:
                    s.permanent_knowledge.add("IMPOSSIBLE_SEEN")
                    s.permanent_knowledge.add("DEERS_FIELD_dod_id")
                    s.permanent_knowledge.add("DEERS_FIELD_clearance_level")
                    result_lines.append(
                        "The terminal pauses. The clerk looks at the screen. "
                        "The clerk looks at you. They say: 'This shouldn't be possible.'"
                    )

            # Unlock transcendence when all steps are present
            if all(
                k in s.permanent_knowledge
                for k in ("IMPOSSIBLE_SEEN", "TRANSCENDENCE_STEP_1", "TRANSCENDENCE_STEP_2")
            ):
                s.permanent_knowledge.add("TRANSCENDENCE_UNLOCKED")

            return GameEvent(
                event_type="documents_submitted",
                payload={"any_fixed": any_fixed},
            )

        def build_message(s: "GameState") -> str:
            prefix = (
                "You slide your documents under the plexiglass. "
                "The clerk examines each one in silence."
            )
            if not result_lines:
                return prefix + "\n\nAll fields are in order."
            return prefix + "\n\n" + "\n".join(f"• {r}" for r in result_lines)

        return Action(
            verb="SUBMIT",
            target="documents",
            conditions=[],
            effects=[submit_documents],
            message=build_message,
        )

    def _handle_examine_deers(self, state: "GameState") -> Action:
        """Examine the player's DEERS record."""

        def discover_impossible(s: "GameState") -> GameEvent | None:
            if (
                s.deers.has_impossible_combination()
                and "IMPOSSIBLE_SEEN" not in s.permanent_knowledge
            ):
                s.permanent_knowledge.add("IMPOSSIBLE_SEEN")
                s.permanent_knowledge.add("DEERS_FIELD_dod_id")
                s.permanent_knowledge.add("DEERS_FIELD_clearance_level")
            return GameEvent(event_type="examine_deers")

        def build_deers_text(s: "GameState") -> str:
            lines = ["Your DEERS Record:"]
            lines.append("─" * 36)
            for f in s.deers.fields.values():
                if f.is_corrupted:
                    block = " [BLOCKING]" if f.blocking else ""
                    fix = f"  Fix: {f.fix_method.value}"
                    lines.append(f"  {f.display_name}: CORRUPTED ({f.current_value}){block}")
                    lines.append(fix)
                else:
                    lines.append(f"  {f.display_name}: OK")
            return "\n".join(lines)

        return Action(
            verb="EXAMINE",
            target="deers",
            conditions=[],
            effects=[discover_impossible],
            message=build_deers_text,
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
