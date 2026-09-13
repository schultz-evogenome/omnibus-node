import pytest
from pydantic import ValidationError

from omnibus_node import sharing


def test_resolution_order():
    s = sharing.Sharing.model_validate(
        {
            "defaults": {"share": "plots"},
            "people": {"0000-0003-1190-1122": {"share": "all", "name": "D"}, "student": {}},
            "items": {"Secret2024": {"share": "none", "reason": "under review"}},
        }
    )
    assert s.resolve("Secret2024", "0000-0003-1190-1122") == "none"
    assert s.resolve("Open2024", "0000-0003-1190-1122") == "all"
    assert s.resolve("Open2024", "student") == "plots"
    assert s.resolve("Open2024", "nobody") == "plots"


def test_layers_and_order():
    assert sharing.allows("plots", "text")
    assert sharing.allows("plots", "previews")
    assert not sharing.allows("plots", "figure_assets")
    assert sharing.allows("assets", "figure_assets")
    assert not sharing.allows("assets", "notes")
    assert sharing.allows("all", "sources")
    assert sharing.lowest("all", "plots") == "plots"
    assert sharing.rank("none") < sharing.rank("plots") < sharing.rank("assets") < sharing.rank("notes") < sharing.rank("all")


def test_invalid_tier_rejected():
    with pytest.raises(ValidationError):
        sharing.Sharing.model_validate({"defaults": {"share": "everything"}})
    with pytest.raises(ValidationError):
        sharing.Sharing.model_validate({"people": {"x": {"email": "no"}}})


def test_save_and_load(tmp_path):
    s = sharing.Sharing()
    s.people["conchoecia"] = sharing.Person(share="notes", name="Darrin")
    sharing.save(tmp_path / "sharing.yaml", s)
    text = (tmp_path / "sharing.yaml").read_text()
    assert text.startswith("# Sharing tiers")
    back = sharing.load(tmp_path / "sharing.yaml")
    assert back.people["conchoecia"].share == "notes"
    assert back.defaults.share == "plots"
