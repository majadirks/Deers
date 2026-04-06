"""DEERS IN THE HEADLIGHTS — main entry point."""

import json
from pathlib import Path

from deers.engine import GameEngine
from deers.persistence import load_game, save_exists


def _load_api_key() -> str | None:
    """Read anthropic_api_key from secrets.json, if present."""
    path = Path("secrets.json")
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("anthropic_api_key") or None
    except (json.JSONDecodeError, OSError):
        return None


def main() -> None:
    api_key = _load_api_key()

    print("DEERS IN THE HEADLIGHTS")
    print("─" * 40)

    engine: GameEngine | None = None

    if save_exists():
        raw = input("Continue saved game? [Y/n]: ").strip().lower()
        if raw in ("", "y", "yes"):
            state = load_game()
            if state is not None:
                engine = GameEngine(player_name=state.player_name, api_key=api_key)
                engine.state = state
                print(f"\nWelcome back, {state.player_name}.")
            else:
                print("(Save file could not be loaded — starting new game.)")

    if engine is None:
        name = input("Enter your name: ").strip() or "Contractor"
        engine = GameEngine(player_name=name, api_key=api_key)

    print()
    print(engine.start())
    print()

    while True:
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            engine.save()
            print("\nGame saved.")
            break

        if raw.upper() in ("QUIT", "EXIT", "Q"):
            engine.save()
            print("Game saved. Goodbye.")
            break

        output = engine.handle_input(raw)
        if output:
            print()
            print(output)
            print()

        if engine.is_game_over:
            break


if __name__ == "__main__":
    main()
