"""GameClock: in-game time tracking, office hours, and action costs."""

from dataclasses import dataclass, field

OFFICE_OPEN_MINS = 9 * 60        # 9:00 AM = 540
OFFICE_CLOSE_MINS = 16 * 60      # 4:00 PM = 960
LUNCH_START_MINS = 11 * 60 + 30  # 11:30 AM = 690
LUNCH_END_MINS = 12 * 60 + 30    # 12:30 PM = 750

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

# Day of week by loop number. Loops 1-4 = Mon-Thu; loop 5+ = Friday (deadline).
_LOOP_DAY_NAMES: dict[int, str] = {
    1: "Monday",
    2: "Tuesday",
    3: "Wednesday",
    4: "Thursday",
}


def day_name(loop_number: int) -> str:
    """Return the weekday name for the given loop number.
    Loops 1–4 = Monday–Thursday (gameplay days).
    Loop 5+ = Friday, which is the job start date (triggers deadline lose condition).
    """
    return _LOOP_DAY_NAMES.get(loop_number, "Friday")


@dataclass
class GameClock:
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
        return {"current_minutes": self.current_minutes}

    @classmethod
    def from_dict(cls, d: dict) -> "GameClock":
        return cls(current_minutes=d["current_minutes"])
