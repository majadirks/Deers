"""DEERS IN THE HEADLIGHTS — main entry point."""

import os

from deers.engine import GameEngine


def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    print("DEERS IN THE HEADLIGHTS")
    print("─" * 40)
    name = input("Enter your name: ").strip() or "Contractor"
    print()

    engine = GameEngine(player_name=name, api_key=api_key)
    print(engine.start())
    print()

    while True:
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGame saved.")
            break

        if raw.upper() in ("QUIT", "EXIT", "Q"):
            print("Goodbye.")
            break

        output = engine.handle_input(raw)
        if output:
            print()
            print(output)
            print()


if __name__ == "__main__":
    main()
