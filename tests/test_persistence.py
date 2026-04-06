"""Tests for deers/persistence.py — save, load, narrator cache."""

import json
import pytest
from pathlib import Path

from deers.content import load_all
from deers.persistence import (
    SAVE_DIR,
    load_game,
    load_narrator_cache,
    save_exists,
    save_game,
    save_narrator_cache,
)
from deers.state import GameState


@pytest.fixture
def content():
    return load_all()


@pytest.fixture
def state(content):
    return GameState.new_game("TestPlayer", content)


@pytest.fixture(autouse=True)
def clean_saves(tmp_path, monkeypatch):
    """Redirect SAVE_DIR to a temp directory so tests don't pollute the repo."""
    monkeypatch.setattr("deers.persistence.SAVE_DIR", tmp_path)
    yield tmp_path


class TestSaveExists:
    def test_no_save_initially(self):
        assert not save_exists()

    def test_exists_after_save(self, state):
        save_game(state)
        assert save_exists()

    def test_named_slot(self, state):
        assert not save_exists("slot1")
        save_game(state, slot="slot1")
        assert save_exists("slot1")


class TestSaveAndLoad:
    def test_round_trip_player_name(self, state, content):
        save_game(state)
        loaded = load_game(content=content)
        assert loaded.player_name == "TestPlayer"

    def test_round_trip_loop_number(self, state, content):
        state.loop_number = 3
        save_game(state)
        loaded = load_game(content=content)
        assert loaded.loop_number == 3

    def test_round_trip_permanent_knowledge(self, state, content):
        state.permanent_knowledge.add("WORKAROUND_KNOWN")
        state.permanent_knowledge.add("CLERK_NAME_KNOWN")
        save_game(state)
        loaded = load_game(content=content)
        assert "WORKAROUND_KNOWN" in loaded.permanent_knowledge
        assert "CLERK_NAME_KNOWN" in loaded.permanent_knowledge

    def test_round_trip_npc_trust(self, state, content):
        state.npcs["e7"].relationship.trust = 4
        save_game(state)
        loaded = load_game(content=content)
        assert loaded.npcs["e7"].relationship.trust == 4

    def test_round_trip_workaround_called(self, state, content):
        state.workaround_called = True
        save_game(state)
        loaded = load_game(content=content)
        assert loaded.workaround_called

    def test_ephemeral_state_reset_on_load(self, state, content):
        """Queue position and location are ephemeral — load always starts at parking_lot."""
        state.queue_position = 7
        state.current_location_id = "waiting_room"
        save_game(state)
        loaded = load_game(content=content)
        assert loaded.queue_position is None
        assert loaded.current_location_id == "parking_lot"

    def test_load_missing_returns_none(self, content):
        result = load_game(slot="nonexistent", content=content)
        assert result is None

    def test_save_creates_directory(self, state, tmp_path, monkeypatch):
        nested = tmp_path / "deep" / "nested"
        monkeypatch.setattr("deers.persistence.SAVE_DIR", nested)
        save_game(state)
        assert (nested / "autosave.json").exists()

    def test_save_is_valid_json(self, state, tmp_path):
        save_game(state)
        path = tmp_path / "autosave.json"
        data = json.loads(path.read_text())
        assert data["save_version"] == "v1"
        assert data["player_name"] == "TestPlayer"


class TestNarratorCache:
    def test_empty_cache_on_missing_file(self):
        result = load_narrator_cache()
        assert result == {}

    def test_round_trip_cache(self):
        cache = {"parking_lot:1:high:morning": "You are in a parking lot."}
        save_narrator_cache(cache)
        loaded = load_narrator_cache()
        assert loaded == cache

    def test_cache_creates_directory(self, tmp_path, monkeypatch):
        nested = tmp_path / "cache_dir"
        monkeypatch.setattr("deers.persistence.SAVE_DIR", nested)
        save_narrator_cache({"k": "v"})
        assert (nested / "narrator_cache.json").exists()

    def test_corrupt_cache_returns_empty(self, tmp_path):
        cache_path = tmp_path / "narrator_cache.json"
        cache_path.write_text("not valid json", encoding="utf-8")
        result = load_narrator_cache()
        assert result == {}
