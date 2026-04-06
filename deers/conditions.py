"""ConditionScheduler: evaluates all win/lose conditions each turn."""

from __future__ import annotations

from typing import TYPE_CHECKING

from deers.models import LoseCondition, TerminalCondition, WinCondition

if TYPE_CHECKING:
    from deers.state import GameState


class ConditionScheduler:
    """
    Evaluates win and lose conditions against the current GameState.
    Called twice per turn: before and after action processing.
    Returns the first TerminalCondition found, or None.
    """

    def evaluate_all(self, state: "GameState") -> TerminalCondition | None:
        """Check all conditions in priority order. Loses take priority over wins."""
        for check in (
            self._check_morale_collapse,
            self._check_start_date_missed,
            self._check_tailgating,
            self._check_corrected_clerk,
            self._check_cac_issued,
            self._check_workaround_complete,
            self._check_transcendence,
        ):
            result = check(state)
            if result is not None:
                return result
        return None

    # ------------------------------------------------------------------
    # Lose conditions
    # ------------------------------------------------------------------

    def _check_morale_collapse(
        self, state: "GameState"
    ) -> TerminalCondition | None:
        """
        Lose if morale hits zero.
        Exception: carrying coffee grants a one-time reprieve.
        """
        if not state.morale.is_zero():
            return None
        # Check for coffee in inventory (event log approach)
        has_coffee = any(
            e.event_type == "coffee_consumed" and e.loop_number == state.loop_number
            for e in state.event_log
        )
        if has_coffee:
            # Coffee consumed this loop; restore a small amount and don't lose
            state.morale.apply_delta(10)
            return None
        return TerminalCondition(
            kind=LoseCondition.MORALE_COLLAPSE,
            message=(
                "You are standing in the parking lot. You have been standing here "
                "for some time. The thought of going back inside has become "
                "structurally incompatible with continuing. You get in your car.\n\n"
                "GAME OVER: Morale collapse.\n"
                "(You needed coffee. There was a vending machine.)"
            ),
        )

    def _check_start_date_missed(
        self, state: "GameState"
    ) -> TerminalCondition | None:
        """Lose if Monday arrives without a CAC."""
        if not state.clock.is_monday():
            return None
        return TerminalCondition(
            kind=LoseCondition.START_DATE_MISSED,
            message=(
                "It is Monday. You do not have a CAC. You have sent three emails "
                "explaining the situation. No one has responded. Your start date "
                "has technically passed.\n\n"
                "GAME OVER: Start date missed.\n"
                "(Four days was, in retrospect, not enough time.)"
            ),
        )

    def _check_tailgating(
        self, state: "GameState"
    ) -> TerminalCondition | None:
        """
        Lose if the player entered the installation without valid photo ID.
        This flag is set by the GO action when tailgating conditions are met.
        """
        if not state.tailgating_detected:
            return None
        state.tailgating_detected = False  # reset so we can show the message once
        return TerminalCondition(
            kind=LoseCondition.TAILGATING,
            message=(
                "An MP stops you inside the building. You do not have valid photo "
                "identification on your person. The MP is not interested in your "
                "appointment email. You are escorted out.\n\n"
                "GAME OVER: Tailgating.\n"
                "(You needed a valid passport or driver's license to enter.)"
            ),
        )

    def _check_corrected_clerk(
        self, state: "GameState"
    ) -> TerminalCondition | None:
        """
        Lose if the player corrected the clerk in a way that violated protocol.
        This flag is set by the dialogue engine (Phase 7) or directly in tests.
        """
        if not state.corrected_clerk:
            return None
        return TerminalCondition(
            kind=LoseCondition.CORRECTED_CLERK,
            message=(
                "The clerk looks at you for a long moment. They pick up a phone. "
                "They speak briefly into it. They hang up. They tell you that "
                "processing has been suspended pending a review. They do not say "
                "of what. You are asked to leave.\n\n"
                "GAME OVER: Corrected the clerk.\n"
                "(The clerk is always right. Even when they are wrong, they are right.)"
            ),
        )

    # ------------------------------------------------------------------
    # Win conditions
    # ------------------------------------------------------------------

    def _check_cac_issued(
        self, state: "GameState"
    ) -> TerminalCondition | None:
        """
        Standard win: player is at the queue window, DEERS is issuable,
        and they have a queue number.
        """
        if state.current_location_id != "queue_window":
            return None
        if state.queue_position is None:
            return None
        if not state.deers.is_issuable():
            return None
        return TerminalCondition(
            kind=WinCondition.STANDARD,
            message=(
                "The clerk scans your documents. The terminal makes a sound "
                "you have not heard before. The clerk slides a card under the "
                "plexiglass without comment.\n\n"
                "It is a CAC.\n\n"
                "Your name is on it. The photo is acceptable. The expiration date "
                "is fourteen months from today, which will also be a problem, "
                "but not today's problem.\n\n"
                "The clerk is already looking at the next number.\n\n"
                "VICTORY: CAC Issued.\n"
                "(Note: temporary access credentials expire in 90 days. "
                "Please see HR to resolve outstanding DEERS discrepancies.)"
            ),
        )

    def _check_workaround_complete(
        self, state: "GameState"
    ) -> TerminalCondition | None:
        """
        Workaround win: player called the DEERS help desk using the E-7's number.
        Requires WORKAROUND_KNOWN and workaround_called flag.
        """
        if not state.workaround_called:
            return None
        if "WORKAROUND_KNOWN" not in state.permanent_knowledge:
            return None
        return TerminalCondition(
            kind=WinCondition.WORKAROUND,
            message=(
                "The person who answers the DEERS help desk has a voice that "
                "suggests they have answered this call before. They ask for "
                "the case number format the E-7 described. You provide it. "
                "There is a pause. A longer pause. They tell you to go to "
                "the processing window.\n\n"
                "What happens at the processing window is not discussed here. "
                "What you receive is not, technically, a CAC. It is a document "
                "that functions as a CAC for purposes that have not been fully "
                "enumerated. You do not ask questions.\n\n"
                "VICTORY: Workaround Complete.\n"
                "(Whether this will work next time is genuinely unclear.)"
            ),
        )

    def _check_transcendence(
        self, state: "GameState"
    ) -> TerminalCondition | None:
        """
        Transcendence win: the player has completed the full impossible sequence.
        Requires TRANSCENDENCE_UNLOCKED in permanent_knowledge.
        """
        if "TRANSCENDENCE_UNLOCKED" not in state.permanent_knowledge:
            return None
        return TerminalCondition(
            kind=WinCondition.TRANSCENDENCE,
            message=(
                "You are sitting at the window.\n\n"
                "You are on the other side of the window.\n\n"
                "You have been here before. You will be here again. "
                "The form in front of you is familiar in the way that recurring "
                "dreams are familiar — not the content, but the texture of it, "
                "the specific quality of the light.\n\n"
                "Someone approaches. They have an appointment email. It is printed "
                "on paper that has been folded exactly once. Their name, as it "
                "appears in DEERS, is wrong.\n\n"
                "You know this before they say a word.\n\n"
                "VICTORY: Transcendence.\n\n"
                "─────────────────────────────────────────────\n"
                "DEERS IN THE HEADLIGHTS\n"
                "Thank you for playing.\n"
                "─────────────────────────────────────────────"
            ),
        )
