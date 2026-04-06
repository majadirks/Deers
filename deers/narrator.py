"""NarratorEngine: generate atmospheric location descriptions via Claude.

Cache key: {location_id}:{loop_number}:{morale_bracket}:{time_bracket}
Cache is in-memory during play and persisted to saves/narrator_cache.json on
loop reset and quit. Falls back to static_description on API failure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from deers.claude_client import ClaudeClient, ClaudeUnavailable
from deers.clock import day_name

if TYPE_CHECKING:
    from deers.state import GameState

# Generous token budget: 80 words ≈ 110 tokens; 150 gives Claude room to breathe
# without burning context on descriptions.
_LOCATION_MAX_TOKENS = 150


class NarratorEngine:
    """
    Generates and caches location descriptions using Claude.

    The cache is keyed on (location, loop, morale bracket, time bracket) so
    that descriptions are stable within a single visit but change meaningfully
    as morale drops, the day progresses, and the loop count rises.

    All public methods are safe to call whether or not Claude is available;
    `describe_location` falls back to authored static text on API failure.
    """

    def __init__(
        self,
        client: ClaudeClient,
        system_prompt: str,
        cache: dict[str, str] | None = None,
    ):
        self._client = client
        self._system = system_prompt
        self.cache: dict[str, str] = cache if cache is not None else {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def describe_location(self, state: "GameState") -> str:
        """
        Return a narrated location description.

        Hits the cache first. On cache miss calls Claude and caches the result.
        Falls back to authored static text if Claude is unavailable.
        """
        key = cache_key(state)
        if key in self.cache:
            return self.cache[key]

        try:
            description = self._generate(state)
        except ClaudeUnavailable:
            return _fallback_description(state)

        self.cache[key] = description
        return description

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_content(
        cls,
        client: ClaudeClient,
        content: dict,
        cache: dict[str, str] | None = None,
    ) -> "NarratorEngine":
        system_prompt = content["prompts"]["narrator"]["system"]
        return cls(client, system_prompt, cache)

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _generate(self, state: "GameState") -> str:
        user_msg = build_location_user_message(state)
        return self._client.complete(self._system, user_msg, max_tokens=_LOCATION_MAX_TOKENS)


# ---------------------------------------------------------------------------
# Cache key (module-level so tests can call it directly)
# ---------------------------------------------------------------------------

def cache_key(state: "GameState") -> str:
    """Return the cache key for the current game state."""
    return (
        f"{state.current_location_id}:"
        f"{state.loop_number}:"
        f"{state.morale.bracket()}:"
        f"{state.clock.time_bracket()}"
    )


# ---------------------------------------------------------------------------
# User message builder (module-level for testability)
# ---------------------------------------------------------------------------

def build_location_user_message(state: "GameState") -> str:
    """Build the user-turn message sent to Claude for a location description."""
    loc = state.current_location()
    npcs = [npc.display_name(state) for npc in loc.present_npcs(state)]

    facts_lines = _format_facts(loc.static_facts)

    lines = [
        f"LOCATION: {loc.name}",
        f"BASE_DESCRIPTION: {loc.static_description}",
        "ENVIRONMENTAL_DETAILS:",
    ]
    lines.extend(f"  {fl}" for fl in facts_lines)
    lines += [
        f"NPCS_PRESENT: {', '.join(npcs) if npcs else 'none'}",
        f"LOOP: {state.loop_number}  DAY: {day_name(state.loop_number)}",
        f"TIME: {state.clock.time_display()} ({state.clock.time_bracket()})",
        f"MORALE: {state.morale.bracket()} ({state.morale.percentage()}%)",
        "",
        "Write the location description. Second person, present tense, "
        "3-5 sentences, under 80 words. No lists. No exits. No available actions.",
    ]
    return "\n".join(lines)


def _format_facts(facts: dict) -> list[str]:
    """Flatten a static_facts dict into displayable key: value strings."""
    result = []
    for k, v in facts.items():
        if isinstance(v, list):
            result.append(f"{k}: {', '.join(str(i) for i in v)}")
        elif isinstance(v, bool):
            result.append(f"{k}: {'yes' if v else 'no'}")
        else:
            result.append(f"{k}: {v}")
    return result


# ---------------------------------------------------------------------------
# Fallback (used when Claude is unavailable mid-session)
# ---------------------------------------------------------------------------

def _fallback_description(state: "GameState") -> str:
    """
    Authored fallback used when Claude is unavailable.
    Returns the location's static description plus any NPCs present.
    Does NOT list exits — the player can use STATUS or EXAMINE.
    """
    loc = state.current_location()
    npcs_here = [npc.display_name(state) for npc in loc.present_npcs(state)]
    parts = [loc.static_description]
    if npcs_here:
        parts.append(f"\n\nPresent: {', '.join(npcs_here)}.")
    return "".join(parts)
