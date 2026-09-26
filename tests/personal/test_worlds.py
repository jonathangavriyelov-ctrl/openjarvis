"""Worlds keep mail, memory, and teams apart."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openjarvis.personal.google_desk import GoogleDesk
from openjarvis.personal.office import OVERALL, PersonalOffice


def _desk(subject: str, meeting: str) -> GoogleDesk:
    def reader(query: str) -> dict:
        del query
        return {
            "inbox": [{"from": "Ada", "subject": subject, "snippet": ""}],
            "meetings": [{"title": meeting, "when": "Tuesday"}],
            "files": [],
        }

    return GoogleDesk(reader=reader)


def _world(office: PersonalOffice, name: str) -> dict:
    found = next(item for item in office.store.list_worlds() if item["name"] == name)
    return found


def test_seed_create_rename_and_keep_personal(tmp_path):
    office = PersonalOffice(tmp_path / "os.db")
    names = {world["name"] for world in office.store.list_worlds()}
    assert names == {"Personal", "Quick Funders"}
    personal = _world(office, "Personal")
    assert office.delete_world(personal["id"]) == "personal"
    assert office.store.get_world(personal["id"]) is not None

    created = office.create_world("Side Studio", summary="A second business.")
    assert created["kind"] == "business"
    renamed = office.rename_world(created["id"], name="Studio North")
    assert renamed is not None
    assert renamed["name"] == "Studio North"
    assert office.delete_world(created["id"]) == "deleted"
    assert office.store.get_world(created["id"]) is None
    assert _world(office, "Quick Funders")
    office.close()


def test_mail_does_not_leak_across_worlds(tmp_path):
    office = PersonalOffice(tmp_path / "os.db")
    personal = _world(office, "Personal")
    funders = _world(office, "Quick Funders")
    office.set_world_google(personal["id"], _desk("personal-only-phrase", "Dentist"))
    office.set_world_google(funders["id"], _desk("business-only-phrase", "Wire"))

    personal_run = office.run_mission("What are today's priorities?")
    personal_blob = personal_run["summary"] + json.dumps(personal_run["deliverables"])
    assert personal_run["world_id"] == personal["id"]
    assert "personal-only-phrase" in personal_blob
    assert "business-only-phrase" not in personal_blob
    notes = " ".join(note["body"] for note in office.store.list_notes())
    assert "business-only-phrase" not in notes

    overall = office.run_mission("What is on today", scope="all")
    assert overall["world_id"] == OVERALL
    assert "personal-only-phrase" in overall["summary"]
    assert "business-only-phrase" in overall["summary"]
    assert "marketing_content" not in {
        item["specialist_id"] for item in overall["deliverables"]
    }

    routed = office.run_mission("Quick Funders priorities", scope="route")
    routed_blob = routed["summary"] + json.dumps(routed["deliverables"])
    assert routed["world_id"] == funders["id"]
    assert "business-only-phrase" in routed_blob
    assert "personal-only-phrase" not in routed_blob
    office.close()


def test_google_account_view_hides_the_secret(tmp_path):
    office = PersonalOffice(tmp_path / "os.db")
    funders = _world(office, "Quick Funders")
    secret = tmp_path / "google.json"
    secret.write_text(
        json.dumps({"refresh_token": "super-secret-token"}),
        encoding="utf-8",
    )
    view = office.connect_google_account(
        funders["id"],
        email="biz@example.com",
        credentials_path=str(secret),
    )
    blob = json.dumps(view)
    assert "credentials_path" not in view
    assert "super-secret-token" not in blob
    assert view["email"] == "biz@example.com"
    repo = Path(__file__).resolve().parents[2]
    inside = repo / "src" / "openjarvis" / "personal" / "office.py"
    with pytest.raises(ValueError):
        office.connect_google_account(
            funders["id"],
            email="other@example.com",
            credentials_path=str(inside),
        )
    office.close()


def test_disabling_marketing_drops_it_from_the_plan(tmp_path):
    office = PersonalOffice(tmp_path / "os.db")
    funders = _world(office, "Quick Funders")
    updated = office.update_world_team(
        funders["id"], "marketing_content", enabled=False
    )
    assert updated is not None
    assert updated["enabled"] is False
    detail = office.run_mission("Draft a launch post for Quick Funders")
    assert detail["world_id"] == funders["id"]
    assert "marketing_content" not in {
        task["specialist_id"] for task in detail["tasks"]
    }
    office.close()


def test_examples_stay_listed_and_worlds_split_them(tmp_path):
    office = PersonalOffice(tmp_path / "os.db")
    names = [project["name"] for project in office.store.list_projects()]
    assert names == ["Quick Funders CRM", "Self Audit"]
    by_name = {project["name"]: project for project in office.store.list_projects()}
    funders = _world(office, "Quick Funders")
    personal = _world(office, "Personal")
    assert by_name["Quick Funders CRM"]["world_id"] == funders["id"]
    assert by_name["Self Audit"]["world_id"] == personal["id"]
    archipelago = office.world(scope="all")
    assert archipelago["projects"] == []
    assert {card["name"] for card in archipelago["worlds"]} == {
        "Personal",
        "Quick Funders",
    }
    office.close()
