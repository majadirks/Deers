"""Core enums, value types, and lightweight dataclasses used across all modules."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class FixMethod(Enum):
    ON_SITE = "ON_SITE"
    HR = "HR"
    FSO = "FSO"
    CONGRESSIONAL = "CONGRESSIONAL"
    IMPOSSIBLE = "IMPOSSIBLE"


class NPCArchetype(Enum):
    CLERK = "clerk"
    VETERAN = "veteran"
    CONTRACTOR = "contractor"
    QUEUE_CUTTER = "queue_cutter"
    SUPERVISOR = "supervisor"


class DocumentType(Enum):
    PASSPORT = "passport"
    DRIVERS_LICENSE = "drivers_license"
    BIRTH_CERTIFICATE = "birth_certificate"
    SF86_EXTRACT = "sf86_extract"
    APPOINTMENT_EMAIL = "appointment_email"
    SECURITY_OFFICER_LETTER = "security_officer_letter"
    VEHICLE_PASS_REQUEST = "vehicle_pass_request"
    CONTRACTOR_LETTER = "contractor_letter"
    TWO_FORMS_ID_COMBO = "two_forms_id_combo"
    PREVIOUS_CAC = "previous_cac"


class DocumentFlaw(Enum):
    LAMINATED = "laminated"
    EXPIRED = "expired"
    MAIDEN_NAME = "maiden_name"
    WRONG_ADDRESS = "wrong_address"
    ILLEGIBLE_NOTARY = "illegible_notary"
    MISSING_PAGE_2 = "missing_page_2"
    UNOFFICIAL_COPY = "unofficial_copy"


# Flaws that prevent a document from being used even if it technically fixes the field.
BLOCKING_FLAWS: frozenset[DocumentFlaw] = frozenset({
    DocumentFlaw.LAMINATED,
    DocumentFlaw.EXPIRED,
    DocumentFlaw.MISSING_PAGE_2,
    DocumentFlaw.ILLEGIBLE_NOTARY,
})


class WinCondition(Enum):
    STANDARD = "standard"
    WORKAROUND = "workaround"
    TRANSCENDENCE = "transcendence"


class LoseCondition(Enum):
    MORALE_COLLAPSE = "morale_collapse"
    START_DATE_MISSED = "start_date_missed"
    TAILGATING = "tailgating"
    CORRECTED_CLERK = "corrected_clerk"


@dataclass
class GameEvent:
    event_type: str
    actor: str = "player"
    payload: dict = field(default_factory=dict)
    loop_number: int = 0
    is_permanent: bool = False
    id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "timestamp": self.timestamp.isoformat(),
            "loop_number": self.loop_number,
            "event_type": self.event_type,
            "actor": self.actor,
            "payload": self.payload,
            "is_permanent": self.is_permanent,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GameEvent":
        return cls(
            id=UUID(d["id"]),
            timestamp=datetime.fromisoformat(d["timestamp"]),
            loop_number=d["loop_number"],
            event_type=d["event_type"],
            actor=d["actor"],
            payload=d["payload"],
            is_permanent=d["is_permanent"],
        )


@dataclass
class ParsedAction:
    verb: str
    target: str
    confidence: float = 1.0
    clarification: str | None = None


@dataclass
class DialogueResult:
    text: str
    trust_delta: int = 0
    knowledge_gained: list[str] = field(default_factory=list)
    morale_delta: int = 0


@dataclass
class FixResult:
    success: bool
    field_name: str
    message: str


@dataclass
class TerminalCondition:
    kind: WinCondition | LoseCondition
    message: str
