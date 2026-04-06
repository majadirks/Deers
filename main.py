"""DEERS IN THE HEADLIGHTS — main entry point."""

import os

from deers.engine import GameEngine
from deers.persistence import load_game, save_game, save_exists


def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")

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
            save_game(engine.state)
            print("\nGame saved.")
            break

        if raw.upper() in ("QUIT", "EXIT", "Q"):
            save_game(engine.state)
            print("Game saved. Goodbye.")
            break

        output = engine.handle_input(raw)
        if output:
            print()
            print(output)
            print()


if __name__ == "__main__":
    main()
