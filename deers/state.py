"""GameState: central container for all mutable game state."""

from __future__ import annotations

import random

from deers.clock import GameClock
from deers.content import load_all
from deers.deers_record import DEERSGenerator, DEERSRecord
from deers.inventory import DocumentFactory, DocumentType, Inventory
from deers.locations import Location, build_locations
from deers.models import DocumentFlaw, GameEvent
from deers.morale import MoraleMeter
from deers.npcs import NPC, ConversationBuffer


class GameState:
    """
    Central game state. Permanent fields survive loop resets; ephemeral fields
    are rebuilt by trigger_reset(). Only permanent state is serialized.
    """

    def __init__(self, player_name: str, content: dict | None = None):
        self.player_name = player_name
        self.content: dict = content or load_all()

        # --- Permanent (survive loops and save/load) ---
        self.loop_number: int = 0
        self.event_log: list[GameEvent] = []
        self.permanent_knowledge: set[str] = set()

        # --- Ephemeral (rebuilt each loop) ---
        self.inventory: Inventory = Inventory()
        self.morale: MoraleMeter = MoraleMeter()
        self.deers: DEERSRecord = DEERSRecord()
        self.clock: GameClock = GameClock()
        self.npcs: dict[str, NPC] = {}
        self.locations: dict[str, Location] = {}
        self.current_location_id: str = "parking_lot"
        self.queue_position: int | None = None
        self.current_conversation: ConversationBuffer | None = None

        # --- Lose-condition flags (reset each loop) ---
        self.tailgating_detected: bool = False
        self.corrected_clerk: bool = False

        # --- Win-condition flags ---
        self.workaround_called: bool = False  # player called DEERS help desk

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def new_game(cls, player_name: str, content: dict | None = None) -> "GameState":
        content = content or load_all()
        state = cls(player_name, content)
        for spec in content["npcs"]["npc"]:
            state.npcs[spec["id"]] = NPC.from_content(spec)
        state.trigger_reset()
        return state

    # ------------------------------------------------------------------
    # Loop management
    # ------------------------------------------------------------------

    def trigger_reset(self) -> None:
        """Increment loop counter, preserve permanent NPC relationships, rebuild ephemeral state."""
        self.loop_number += 1

        # Save permanent NPC relationships before reset
        saved_rels = {
            npc_id: npc.relationship
            for npc_id, npc in self.npcs.items()
            if npc.card.is_permanent
        }

        self._rebuild_ephemeral()

        # Restore permanent NPC relationships
        for npc_id, rel in saved_rels.items():
            if npc_id in self.npcs:
                self.npcs[npc_id].relationship = rel

    def _rebuild_ephemeral(self) -> None:
        """Rebuild all loop-scoped state. Does NOT restore permanent NPC relationships."""
        pk = frozenset(self.permanent_knowledge)

        self.deers = DEERSGenerator(self.content).generate(self.loop_number, pk)
        self.clock = GameClock()
        self.morale = MoraleMeter()
        self.queue_position = None
        self.current_conversation = None
        self.current_location_id = "parking_lot"
        self.tailgating_detected = False
        self.corrected_clerk = False
        self.locations = build_locations(self.content)

        # Fresh NPCs (caller restores permanent relationships if needed)
        for spec in self.content["npcs"]["npc"]:
            self.npcs[spec["id"]] = NPC.from_content(spec)

        # Starting inventory: appointment email (clean), passport (clean),
        # driver's license (laminated — one blocking flaw)
        rng = random.Random(hash(f"inventory_{self.loop_number}"))
        factory = DocumentFactory(rng, self.content)
        self.inventory = Inventory()
        self.inventory.add(factory.make(DocumentType.APPOINTMENT_EMAIL, force_flaws=[]))
        self.inventory.add(factory.make(DocumentType.PASSPORT, force_flaws=[]))
        self.inventory.add(
            factory.make(DocumentType.DRIVERS_LICENSE, force_flaws=[DocumentFlaw.LAMINATED])
        )

    def should_loop(self) -> bool:
        return self.clock.is_closed()

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def current_location(self) -> Location:
        return self.locations[self.current_location_id]

    def npc_at_location(self, npc_id: str) -> NPC | None:
        npc = self.npcs.get(npc_id)
        if npc and npc.is_present_at(self.current_location_id, self):
            return npc
        return None

    # ------------------------------------------------------------------
    # Event log
    # ------------------------------------------------------------------

    def apply_event(self, event: GameEvent) -> None:
        """Record event. State mutations are performed directly by effect functions."""
        event.loop_number = self.loop_number
        self.event_log.append(event)

    # ------------------------------------------------------------------
    # Serialization (permanent state only)
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "save_version": "v1",
            "player_name": self.player_name,
            "loop_number": self.loop_number,
            "permanent_knowledge": sorted(self.permanent_knowledge),
            "npcs": {npc_id: npc.to_dict() for npc_id, npc in self.npcs.items()},
            "workaround_called": self.workaround_called,
        }

    @classmethod
    def from_dict(cls, d: dict, content: dict | None = None) -> "GameState":
        content = content or load_all()
        state = cls(d["player_name"], content)
        state.loop_number = d["loop_number"]
        state.permanent_knowledge = set(d.get("permanent_knowledge", []))
        state.workaround_called = d.get("workaround_called", False)

        # Restore NPCs from saved relationships
        npc_data = d.get("npcs", {})
        for spec in content["npcs"]["npc"]:
            npc_id = spec["id"]
            npc_dict = npc_data.get(npc_id, {"npc_id": npc_id, "skipped": True})
            state.npcs[npc_id] = NPC.from_dict(npc_dict, spec)

        # Rebuild ephemeral state WITHOUT resetting NPC relationships
        pk = frozenset(state.permanent_knowledge)
        state.deers = DEERSGenerator(content).generate(state.loop_number, pk)
        state.clock = GameClock()
        state.morale = MoraleMeter()
        state.queue_position = None
        state.current_conversation = None
        state.current_location_id = "parking_lot"
        state.locations = build_locations(content)

        rng = random.Random(hash(f"inventory_{state.loop_number}"))
        factory = DocumentFactory(rng, content)
        state.inventory = Inventory()
        state.inventory.add(factory.make(DocumentType.APPOINTMENT_EMAIL, force_flaws=[]))
        state.inventory.add(factory.make(DocumentType.PASSPORT, force_flaws=[]))
        state.inventory.add(
            factory.make(DocumentType.DRIVERS_LICENSE, force_flaws=[DocumentFlaw.LAMINATED])
        )

        return state
