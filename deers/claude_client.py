"""ClaudeClient: thin wrapper around the Anthropic API."""

from __future__ import annotations

_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_DEFAULT_MAX_TOKENS = 256


class ClaudeClient:
    """
    Minimal Anthropic API client. All game Claude calls go through here.
    Raises ClaudeUnavailable when the API cannot be reached or returns an error,
    so callers can fall back to authored responses cleanly.
    """

    def __init__(self, api_key: str, model: str = _DEFAULT_MODEL):
        try:
            import anthropic
        except ImportError as exc:
            raise ClaudeUnavailable("anthropic package not installed") from exc

        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> str:
        """Send a single-turn completion request. Returns the text of the first content block."""
        return self.chat(system, [{"role": "user", "content": user}], max_tokens)

    def chat(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> str:
        """Send a multi-turn chat request. `messages` is a list of Claude API message dicts."""
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
            )
            return response.content[0].text
        except Exception as exc:
            raise ClaudeUnavailable(str(exc)) from exc


class ClaudeUnavailable(Exception):
    """Raised when the Claude API cannot be reached or returns an error."""


class DummyClaudeClient:
    """
    Test double for ClaudeClient. Returns deterministic configured responses
    without making any network calls.

    Usage::

        # Successful stub
        client = DummyClaudeClient(
            complete_response='{"topic":"freeform","confidence":1.0}',
            chat_response="Get there before 0900.",
        )

        # Failure stub — simulates API unavailability
        client = DummyClaudeClient(raises=True)

    Call history is available on ``complete_calls`` and ``chat_calls`` for
    assertion in tests.
    """

    def __init__(
        self,
        complete_response: str = "{}",
        chat_response: str = "Noted.",
        raises: bool = False,
    ) -> None:
        self.complete_response = complete_response
        self.chat_response = chat_response
        self.raises = raises
        # Each entry is (system, user) / (system, messages)
        self.complete_calls: list[tuple[str, str]] = []
        self.chat_calls: list[tuple[str, list]] = []

    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> str:
        if self.raises:
            raise ClaudeUnavailable("DummyClaudeClient configured to raise")
        self.complete_calls.append((system, user))
        return self.complete_response

    def chat(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> str:
        if self.raises:
            raise ClaudeUnavailable("DummyClaudeClient configured to raise")
        self.chat_calls.append((system, messages))
        return self.chat_response

    @property
    def call_count(self) -> int:
        """Total number of calls made across both methods."""
        return len(self.complete_calls) + len(self.chat_calls)
