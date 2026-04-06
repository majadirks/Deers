"""Persistence: save/load game state and narrator cache."""

from __future__ import annotations

import json
from pathlib import Path

SAVE_DIR = Path("saves")
_SAVE_EXT = ".json"
_NARRATOR_CACHE_FILE = "narrator_cache.json"


def _save_path(slot: str) -> Path:
    return SAVE_DIR / f"{slot}{_SAVE_EXT}"


def save_exists(slot: str = "autosave") -> bool:
    return _save_path(slot).exists()


def save_game(state: "GameState", slot: str = "autosave") -> None:  # noqa: F821
    """Serialize permanent state to saves/<slot>.json."""
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    data = state.to_dict()
    path = _save_path(slot)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_game(slot: str = "autosave", content: dict | None = None) -> "GameState | None":  # noqa: F821
    """Load permanent state from saves/<slot>.json. Returns None if not found."""
    from deers.state import GameState

    path = _save_path(slot)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return GameState.from_dict(data, content)


# ---------------------------------------------------------------------------
# Narrator cache (keyed on location/loop/morale/time bracket)
# ---------------------------------------------------------------------------

def load_narrator_cache() -> dict[str, str]:
    path = SAVE_DIR / _NARRATOR_CACHE_FILE
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_narrator_cache(cache: dict[str, str]) -> None:
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    path = SAVE_DIR / _NARRATOR_CACHE_FILE
    path.write_text(json.dumps(cache, indent=2), encoding="utf-8")
