"""NPC models: CharacterCard, NPCRelationship, ConversationBuffer, NPC."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from deers.models import NPCArchetype

if TYPE_CHECKING:
    pass  # GameState imported at runtime to avoid circular imports

MAX_CONVERSATION_TURNS = 8


@dataclass
class CharacterCard:
    """Static data from TOML — describes who an NPC is."""
    npc_id: str
    archetype: NPCArchetype
    voice_description: str
    fallback_line: str
    knowledge_map: dict[str, str]       # topic -> knowledge template
    trust_thresholds: dict[str, int]    # topic -> minimum trust to reveal
    morale_deltas: dict[str, int]       # topic -> player morale delta on discussion
    is_permanent: bool
    present_at_locations: list[str]
    present_hours: str                  # 'office_hours', 'always_during_office_hours', etc.

    @classmethod
    def from_content(cls, spec: dict) -> "CharacterCard":
        archetype_map = {
            "clerk": NPCArchetype.CLERK,
            "veteran": NPCArchetype.VETERAN,
            "contractor": NPCArchetype.CONTRACTOR,
            "queue_cutter": NPCArchetype.QUEUE_CUTTER,
            "supervisor": NPCArchetype.SUPERVISOR,
        }
        return cls(
            npc_id=spec["id"],
            archetype=archetype_map[spec["archetype"]],
            voice_description=spec["voice_description"],
            fallback_line=spec["fallback_line"],
            knowledge_map=spec.get("knowledge_map", {}),
            trust_thresholds=spec.get("trust_thresholds", {}),
            morale_deltas=spec.get("morale_deltas", {}),
            is_permanent=spec.get("is_permanent", False),
            present_at_locations=spec.get("is_present_at", {}).get("locations", []),
            present_hours=spec.get("is_present_at", {}).get("hours", "office_hours"),
        )


@dataclass
class NPCRelationship:
    """Mutable per-playthrough relationship state for one NPC."""
    npc_id: str
    trust: int = 0
    topics_discussed: list[str] = field(default_factory=list)
    knowledge_revealed: list[str] = field(default_factory=list)

    def can_discuss(self, topic: str, thresholds: dict[str, int]) -> bool:
        min_trust = thresholds.get(topic, 0)
        return self.trust >= min_trust

    def record_topic(self, topic: str) -> None:
        if topic not in self.topics_discussed:
            self.topics_discussed.append(topic)

    def to_dict(self) -> dict:
        return {
            "npc_id": self.npc_id,
            "trust": self.trust,
            "topics_discussed": self.topics_discussed,
            "knowledge_revealed": self.knowledge_revealed,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "NPCRelationship":
        return cls(
            npc_id=d["npc_id"],
            trust=d["trust"],
            topics_discussed=d.get("topics_discussed", []),
            knowledge_revealed=d.get("knowledge_revealed", []),
        )


@dataclass
class ConversationBuffer:
    """
    Holds the message history for one conversation with one NPC.
    Side effects (trust deltas, morale changes, knowledge gained) are accumulated
    and committed atomically when the conversation closes.
    """
    npc_id: str
    max_turns: int = MAX_CONVERSATION_TURNS
    messages: list[dict] = field(default_factory=list)  # Claude API format
    is_active: bool = True
    pending_trust_delta: int = 0
    pending_morale_delta: int = 0
    pending_knowledge: list[str] = field(default_factory=list)
    turns_taken: int = 0

    def add_player(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_npc(self, text: str) -> None:
        self.messages.append({"role": "assistant", "content": text})
        self.turns_taken += 1

    def to_messages(self) -> list[dict]:
        """Return messages in Claude API format."""
        return list(self.messages)

    def is_exhausted(self) -> bool:
        return self.turns_taken >= self.max_turns

    def accrue_effects(
        self,
        trust_delta: int = 0,
        morale_delta: int = 0,
        knowledge: list[str] | None = None,
    ) -> None:
        self.pending_trust_delta += trust_delta
        self.pending_morale_delta += morale_delta
        if knowledge:
            self.pending_knowledge.extend(knowledge)

    def close(self) -> dict:
        """
        Mark conversation inactive. Returns the accumulated side effects
        for the caller to commit to game state.
        """
        self.is_active = False
        return {
            "trust_delta": self.pending_trust_delta,
            "morale_delta": self.pending_morale_delta,
            "knowledge_gained": list(self.pending_knowledge),
        }


@dataclass
class NPC:
    """Combines static card data with mutable relationship state."""
    card: CharacterCard
    relationship: NPCRelationship

    @classmethod
    def from_content(cls, spec: dict) -> "NPC":
        card = CharacterCard.from_content(spec)
        rel = NPCRelationship(npc_id=spec["id"])
        return cls(card=card, relationship=rel)

    @property
    def npc_id(self) -> str:
        return self.card.npc_id

    @property
    def trust(self) -> int:
        return self.relationship.trust

    def display_name(self, state=None) -> str:
        """
        Returns '???' if trust is 0 and NPC is not permanent.
        Otherwise returns a readable name derived from archetype.
        """
        archetype_names = {
            NPCArchetype.CLERK: "The Clerk",
            NPCArchetype.VETERAN: "The E-7",
            NPCArchetype.CONTRACTOR: "The Contractor",
            NPCArchetype.QUEUE_CUTTER: "???",
            NPCArchetype.SUPERVISOR: "The Supervisor",
        }
        if not self.card.is_permanent and self.relationship.trust == 0:
            return "???"
        return archetype_names.get(self.card.archetype, self.card.npc_id)

    def available_topics(self, state=None) -> list[str]:
        """Topics this NPC can currently discuss (trust-gated)."""
        return [
            topic
            for topic in self.card.knowledge_map
            if self.relationship.can_discuss(topic, self.card.trust_thresholds)
        ]

    def is_present_at(self, location_id: str, state=None) -> bool:
        """True if this NPC is present at the given location."""
        if location_id not in self.card.present_at_locations:
            return False
        # supervisor is never present
        if self.card.archetype == NPCArchetype.SUPERVISOR:
            return False
        return True

    def to_dict(self) -> dict:
        """
        Permanent NPCs: serialize full relationship.
        Non-permanent: only serialize if trust > 0.
        """
        if not self.card.is_permanent and self.relationship.trust == 0:
            return {"npc_id": self.npc_id, "skipped": True}
        return {
            "npc_id": self.npc_id,
            "skipped": False,
            "relationship": self.relationship.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict, spec: dict) -> "NPC":
        card = CharacterCard.from_content(spec)
        if d.get("skipped", False):
            rel = NPCRelationship(npc_id=d["npc_id"])
        else:
            rel = NPCRelationship.from_dict(d["relationship"])
        return cls(card=card, relationship=rel)
