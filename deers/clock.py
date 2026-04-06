"""GameClock: in-game time tracking, office hours, and action costs."""

from dataclasses import dataclass, field
from datetime import time

OFFICE_OPEN_MINS = 9 * 60       # 9:00 AM = 540
OFFICE_CLOSE_MINS = 16 * 60     # 4:00 PM = 960
LUNCH_START_MINS = 11 * 60 + 30  # 11:30 AM = 690
LUNCH_END_MINS = 12 * 60 + 30   # 12:30 PM = 750

# Minutes it costs to perform each verb.
ACTION_COSTS: dict[str, int] = {
    "GO": 5,
    "WAIT": 30,
    "TALK": 10,
    "EXAMINE": 2,
    "USE": 5,
    "TAKE": 2,
    "READ": 8,
    "DROP": 1,
    "HELP": 0,
    "STATUS": 0,
}

# Day names for display; Thursday is index 0 (4 days until Monday).
_DAY_NAMES = ["Thursday", "Friday", "Saturday", "Sunday", "Monday"]


@dataclass
class GameClock:
    days_until_monday: int = 4          # Thursday = 4, Friday = 3, ... Monday = 0
    current_minutes: int = OFFICE_OPEN_MINS  # Start at 9:00 AM

    def advance(self, minutes: int) -> list[str]:
        """
        Advance the clock by `minutes`. Returns a list of triggered event type
        strings (e.g. 'office_closed', 'lunch_started', 'lunch_ended').
        """
        if minutes <= 0:
            return []

        events: list[str] = []
        prev = self.current_minutes
        self.current_minutes += minutes

        # Check for lunch window crossing (start)
        if prev < LUNCH_START_MINS <= self.current_minutes:
            events.append("lunch_started")

        # Check for lunch window crossing (end)
        if prev < LUNCH_END_MINS <= self.current_minutes:
            events.append("lunch_ended")

        # Check for office close
        if prev < OFFICE_CLOSE_MINS <= self.current_minutes:
            events.append("office_closed")

        return events

    def is_office_open(self) -> bool:
        """True if within office hours and not at lunch."""
        if self.current_minutes < OFFICE_OPEN_MINS:
            return False
        if self.current_minutes >= OFFICE_CLOSE_MINS:
            return False
        if LUNCH_START_MINS <= self.current_minutes < LUNCH_END_MINS:
            return False
        return True

    def is_lunch(self) -> bool:
        return LUNCH_START_MINS <= self.current_minutes < LUNCH_END_MINS

    def is_closed(self) -> bool:
        return self.current_minutes >= OFFICE_CLOSE_MINS

    def is_monday(self) -> bool:
        return self.days_until_monday <= 0

    def time_display(self) -> str:
        """Return human-readable time like '9:47 AM'."""
        total = self.current_minutes
        hours = (total // 60) % 24
        mins = total % 60
        period = "AM" if hours < 12 else "PM"
        display_hour = hours if hours <= 12 else hours - 12
        if display_hour == 0:
            display_hour = 12
        return f"{display_hour}:{mins:02d} {period}"

    def day_display(self) -> str:
        idx = max(0, min(4, 4 - self.days_until_monday))
        return _DAY_NAMES[idx]

    def time_bracket(self) -> str:
        """'morning' | 'lunch' | 'afternoon'"""
        if self.current_minutes < LUNCH_START_MINS:
            return "morning"
        if self.current_minutes < LUNCH_END_MINS:
            return "lunch"
        return "afternoon"

    def action_cost(self, verb: str) -> int:
        return ACTION_COSTS.get(verb.upper(), 5)

    def to_dict(self) -> dict:
        return {
            "days_until_monday": self.days_until_monday,
            "current_minutes": self.current_minutes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GameClock":
        return cls(
            days_until_monday=d["days_until_monday"],
            current_minutes=d["current_minutes"],
        )
