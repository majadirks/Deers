"""Location, Feature, Exit, and Condition models.

Exit conditions are wired here as code — this is the intentional coupling point
between content and logic. Every exit condition is documented with a comment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from deers.content import load_all

if TYPE_CHECKING:
    from deers.state import GameState


@dataclass
class Feature:
    id: str
    name: str
    examine_text: str
    interactions: dict[str, str]    # verb -> event_type to emit
    conditions: dict[str, "Condition"] = field(default_factory=dict)


@dataclass
class Condition:
    description: str
    failure_message: str
    check: Callable[["GameState"], bool]


@dataclass
class Exit:
    destination_id: str
    description: str
    conditions: list[Condition] = field(default_factory=list)

    def is_available(self, state: "GameState") -> bool:
        return all(c.check(state) for c in self.conditions)

    def first_failure(self, state: "GameState") -> Condition | None:
        for c in self.conditions:
            if not c.check(state):
                return c
        return None


@dataclass
class Location:
    id: str
    name: str
    static_description: str
    static_facts: dict
    base_time_cost_minutes: int
    features: list[Feature] = field(default_factory=list)
    exits: list[Exit] = field(default_factory=list)

    def feature(self, feature_id: str) -> Feature | None:
        return next((f for f in self.features if f.id == feature_id), None)

    def present_npcs(self, state: "GameState") -> list:
        """Return NPCs present at this location given current state."""
        return [
            npc for npc in state.npcs.values()
            if npc.is_present_at(self.id, state)
        ]

    def available_exits(self, state: "GameState") -> list[Exit]:
        return [e for e in self.exits if e.is_available(state)]


def _build_features_from_content(loc_spec: dict) -> list[Feature]:
    """Build Feature objects from a location spec dict."""
    features = []
    for fspec in loc_spec.get("features", []):
        features.append(Feature(
            id=fspec["id"],
            name=fspec["name"],
            examine_text=fspec["examine_text"],
            interactions=fspec.get("interactions", {}),
        ))
    return features


def build_locations(content: dict | None = None) -> dict[str, Location]:
    """
    Build all Location objects from content, wiring exits and conditions as code.
    Returns a dict keyed by location id.
    """
    if content is None:
        content = load_all()

    loc_specs = {spec["id"]: spec for spec in content["locations"]["location"]}

    locs: dict[str, Location] = {}
    for spec in content["locations"]["location"]:
        locs[spec["id"]] = Location(
            id=spec["id"],
            name=spec["name"],
            static_description=spec["static_description"],
            static_facts=spec.get("static_facts", {}),
            base_time_cost_minutes=spec["base_time_cost_minutes"],
            features=_build_features_from_content(spec),
            exits=[],  # wired below
        )

    # -------------------------------------------------------------------------
    # EXIT WIRING
    # All exits and their conditions are defined here, not in TOML.
    # Conditions are lambdas over GameState; they cannot be serialized.
    # -------------------------------------------------------------------------

    # parking_lot -> installation_gate
    # Condition: always available (you can always try to enter)
    locs["parking_lot"].exits.append(Exit(
        destination_id="installation_gate",
        description="Walk toward the installation gate.",
        conditions=[],
    ))

    # installation_gate -> waiting_room
    # Condition: player must have at least one document (appointment email or ID)
    # AND the office must not be closed for the day
    locs["installation_gate"].exits.append(Exit(
        destination_id="waiting_room",
        description="Pass through the gate to the DEERS office waiting room.",
        conditions=[
            Condition(
                description="Have at least one document to present",
                failure_message=(
                    "The MP at the gate asks for your documentation. "
                    "You do not have any documentation. The MP's expression does not change. "
                    "You are not waved through."
                ),
                check=lambda state: len(state.inventory.documents) > 0,
            ),
            Condition(
                description="Office must be open",
                failure_message=(
                    "The DEERS office is closed. The gate is still open, "
                    "but there is nothing inside for you. "
                    "The MP suggests you return during office hours: 0900 to 1600."
                ),
                check=lambda state: not state.clock.is_closed(),
            ),
        ],
    ))

    # installation_gate -> parking_lot (always — you can always leave)
    locs["installation_gate"].exits.append(Exit(
        destination_id="parking_lot",
        description="Return to the parking lot.",
        conditions=[],
    ))

    # waiting_room -> queue_window
    # Condition: player has taken a number AND their number is being called
    # (simplified: queue_position is 0 or they are next)
    locs["waiting_room"].exits.append(Exit(
        destination_id="queue_window",
        description="Approach the processing window when your number is called.",
        conditions=[
            Condition(
                description="Must have a queue number",
                failure_message=(
                    "You approach the window. The clerk looks up. "
                    "\"Do you have a number?\" You do not have a number. "
                    "The clerk returns to their screen."
                ),
                check=lambda state: state.queue_position is not None,
            ),
            Condition(
                description="Office must not be at lunch",
                failure_message=(
                    "The window has a hand-lettered sign: LUNCH 1130-1230. "
                    "It is lunch. The clerk is not present. "
                    "The sign does not offer further guidance."
                ),
                check=lambda state: not state.clock.is_lunch(),
            ),
            Condition(
                description="Office must be open",
                failure_message=(
                    "The processing window is closed. A sign says: "
                    "OFFICE HOURS 0900-1600 MON-FRI. It is neither of those things."
                ),
                check=lambda state: state.clock.is_office_open(),
            ),
        ],
    ))

    # waiting_room -> vending_alcove (always available)
    locs["waiting_room"].exits.append(Exit(
        destination_id="vending_alcove",
        description="Step into the vending alcove.",
        conditions=[],
    ))

    # waiting_room -> installation_gate (leave the building)
    locs["waiting_room"].exits.append(Exit(
        destination_id="installation_gate",
        description="Leave the building toward the gate.",
        conditions=[],
    ))

    # waiting_room -> supervisors_door
    # Condition: player must know the supervisor's name (permanent_knowledge)
    locs["waiting_room"].exits.append(Exit(
        destination_id="supervisors_door",
        description="Go to the supervisor's office.",
        conditions=[
            Condition(
                description="Must know where the supervisor's office is",
                failure_message=(
                    "You're not sure where the supervisor's office is. "
                    "There are no signs. You stand in the waiting room."
                ),
                check=lambda state: "SUPERVISOR_NAME_KNOWN" in state.permanent_knowledge,
            ),
        ],
    ))

    # queue_window -> waiting_room (step back from the window)
    locs["queue_window"].exits.append(Exit(
        destination_id="waiting_room",
        description="Step back to the waiting area.",
        conditions=[],
    ))

    # vending_alcove -> waiting_room (always)
    locs["vending_alcove"].exits.append(Exit(
        destination_id="waiting_room",
        description="Return to the waiting room.",
        conditions=[],
    ))

    # vending_alcove -> base_library
    # Condition: player must know the library's location (permanent_knowledge)
    locs["vending_alcove"].exits.append(Exit(
        destination_id="base_library",
        description="Head to the base library.",
        conditions=[
            Condition(
                description="Must know where the base library is",
                failure_message=(
                    "You know there's a library somewhere on base. "
                    "You do not know where. Wandering the installation "
                    "without a CAC is not advisable."
                ),
                check=lambda state: "LIBRARY_LOCATION_KNOWN" in state.permanent_knowledge,
            ),
        ],
    ))

    # base_library -> waiting_room (walk back)
    locs["base_library"].exits.append(Exit(
        destination_id="waiting_room",
        description="Walk back to the DEERS office.",
        conditions=[],
    ))

    # supervisors_door -> waiting_room
    locs["supervisors_door"].exits.append(Exit(
        destination_id="waiting_room",
        description="Return to the waiting room.",
        conditions=[],
    ))

    return locs
