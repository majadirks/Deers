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
        try:
            message = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return message.content[0].text
        except Exception as exc:
            raise ClaudeUnavailable(str(exc)) from exc


class ClaudeUnavailable(Exception):
    """Raised when the Claude API cannot be reached or returns an error."""
