import tomllib
from pathlib import Path

CONTENT_DIR = Path(__file__).parent.parent / "content"


def load_toml(filename: str) -> dict:
    with open(CONTENT_DIR / filename, "rb") as f:
        return tomllib.load(f)


def load_all() -> dict:
    return {
        "deers_fields": load_toml("deers_fields.toml"),
        "documents": load_toml("documents.toml"),
        "locations": load_toml("locations.toml"),
        "npcs": load_toml("npcs.toml"),
        "prompts": load_toml("prompts.toml"),
    }
