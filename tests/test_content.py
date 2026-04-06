"""Phase 1 tests: content loading and validation."""

import pytest
from deers.content import load_all, load_toml


def test_load_all_runs():
    data = load_all()
    assert set(data.keys()) == {"deers_fields", "documents", "locations", "npcs", "prompts"}


def test_all_toml_files_parse():
    for filename in ["deers_fields.toml", "documents.toml", "locations.toml", "npcs.toml", "prompts.toml"]:
        result = load_toml(filename)
        assert result is not None


def test_deers_field_count():
    data = load_all()
    assert len(data["deers_fields"]["field"]) == 8


def test_deers_field_fix_methods_valid():
    valid = {"ON_SITE", "HR", "FSO", "CONGRESSIONAL", "IMPOSSIBLE"}
    data = load_all()
    for f in data["deers_fields"]["field"]:
        assert f["fix_method"] in valid, f"Invalid fix_method on field {f['name']}: {f['fix_method']}"


def test_exactly_one_impossible_field():
    data = load_all()
    impossible = [f for f in data["deers_fields"]["field"] if f["fix_method"] == "IMPOSSIBLE"]
    assert len(impossible) == 1
    assert impossible[0]["name"] == "dod_id"


def test_all_npcs_have_fallback_line():
    data = load_all()
    for npc in data["npcs"]["npc"]:
        assert "fallback_line" in npc, f"NPC {npc['id']} missing fallback_line"
        assert npc["fallback_line"], f"NPC {npc['id']} has empty fallback_line"


def test_document_count():
    data = load_all()
    assert len(data["documents"]["document"]) == 10


def test_location_count():
    data = load_all()
    assert len(data["locations"]["location"]) == 7


def test_npc_count():
    data = load_all()
    assert len(data["npcs"]["npc"]) == 5


def test_all_deers_fields_have_required_keys():
    required = {"name", "display_name", "fix_method", "fixing_documents", "blocking", "flavor_text"}
    data = load_all()
    for f in data["deers_fields"]["field"]:
        missing = required - set(f.keys())
        assert not missing, f"Field {f.get('name', '?')} missing keys: {missing}"


def test_all_documents_have_required_keys():
    required = {"id", "display_name", "description", "fixes_fields", "can_be_photocopied", "fallback_examine_text"}
    data = load_all()
    for doc in data["documents"]["document"]:
        missing = required - set(doc.keys())
        assert not missing, f"Document {doc.get('id', '?')} missing keys: {missing}"


def test_all_locations_have_required_keys():
    required = {"id", "name", "base_time_cost_minutes", "static_description", "static_facts"}
    data = load_all()
    for loc in data["locations"]["location"]:
        missing = required - set(loc.keys())
        assert not missing, f"Location {loc.get('id', '?')} missing keys: {missing}"


def test_prompts_have_required_sections():
    data = load_all()
    assert "narrator" in data["prompts"]
    assert "parser" in data["prompts"]
    assert "dialogue" in data["prompts"]
    assert "system" in data["prompts"]["narrator"]
    assert "system" in data["prompts"]["parser"]
    assert "system_template" in data["prompts"]["dialogue"]


def test_clearance_level_is_fso_fixable():
    """clearance_level + dod_id together = IMPOSSIBLE gate; clearance alone must be FSO-fixable."""
    data = load_all()
    clearance = next(f for f in data["deers_fields"]["field"] if f["name"] == "clearance_level")
    assert clearance["fix_method"] == "FSO"
