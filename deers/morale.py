"""MoraleMeter: tracks player morale as a resource."""

from dataclasses import dataclass


MAX_MORALE = 100
CRITICAL_THRESHOLD = 25
LOW_THRESHOLD = 50
HIGH_THRESHOLD = 75

# Drain / restore rates keyed on event_type strings.
EVENT_DELTAS: dict[str, int] = {
    # Drains
    "deers_field_rejected": -8,
    "document_rejected": -6,
    "queue_advanced_past": -10,   # someone cuts the queue
    "office_closed": -5,
    "wait": -3,
    "action_failed": -2,
    "wrong_location": -2,
    "npc_unhelpful": -4,
    "loop_reset": -5,
    # Restores
    "coffee_consumed": 15,
    "water_consumed": 5,
    "document_accepted": 8,
    "deers_field_fixed": 12,
    "knowledge_gained": 6,
    "npc_helpful": 5,
    "queue_advanced": 4,
    "chips_consumed": 8,
}


@dataclass
class MoraleMeter:
    current: int = MAX_MORALE
    maximum: int = MAX_MORALE

    # Per-event drain/restore rates (can be overridden for balance tuning)
    event_deltas: dict = None  # type: ignore

    def __post_init__(self):
        if self.event_deltas is None:
            self.event_deltas = dict(EVENT_DELTAS)

    def apply(self, event_type: str) -> int:
        """Apply a named event delta. Returns the actual delta applied."""
        delta = self.event_deltas.get(event_type, 0)
        return self.apply_delta(delta)

    def apply_delta(self, delta: int) -> int:
        """Apply a raw delta. Returns the actual delta applied (clamped)."""
        before = self.current
        self.current = max(0, min(self.maximum, self.current + delta))
        return self.current - before

    def is_critical(self) -> bool:
        return self.current <= CRITICAL_THRESHOLD

    def is_zero(self) -> bool:
        return self.current <= 0

    def bracket(self) -> str:
        if self.current <= CRITICAL_THRESHOLD:
            return "critical"
        if self.current <= LOW_THRESHOLD:
            return "low"
        if self.current <= HIGH_THRESHOLD:
            return "medium"
        return "high"

    def modifier(self) -> float:
        """
        Scale factor 0.25–1.0 applied to dialogue option quality.
        Critical morale means fewer and worse options surface.
        """
        bracket = self.bracket()
        return {"high": 1.0, "medium": 0.75, "low": 0.5, "critical": 0.25}[bracket]

    def percentage(self) -> int:
        return int(100 * self.current / self.maximum)

    def bar(self, width: int = 8) -> str:
        """Return a simple ASCII bar, e.g. '██████░░'."""
        filled = round(width * self.current / self.maximum)
        return "█" * filled + "░" * (width - filled)

    def to_dict(self) -> dict:
        return {"current": self.current, "maximum": self.maximum}

    @classmethod
    def from_dict(cls, d: dict) -> "MoraleMeter":
        return cls(current=d["current"], maximum=d["maximum"])
