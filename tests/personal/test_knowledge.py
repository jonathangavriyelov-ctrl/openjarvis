"""Knowledge feed: teach, route, recall, and approve a playbook."""

from __future__ import annotations

import io
import zipfile

import pytest

from openjarvis.personal.knowledge import (
    captions_from_json3,
    captions_from_xml,
    extract_text,
    fetch_link,
)
from openjarvis.personal.office import PersonalOffice
from openjarvis.personal.phone import PhoneGate

MCA = (
    "MCA underwriting for a merchant cash advance.\n"
    "Always confirm the stackrate before sending an offer.\n"
    "1. Pull three months of statements.\n"
)


def _world(office: PersonalOffice, name: str) -> dict:
    found = next(item for item in office.store.list_worlds() if item["name"] == name)
    return found


def _brief(office: PersonalOffice, world_id: str, specialist_id: str) -> str:
    member = next(
        row
        for row in office.store.team(world_id)
        if row["specialist_id"] == specialist_id
    )
    return member.get("brief") or ""


def test_mca_lesson_stays_inside_quick_funders(tmp_path):
    office = PersonalOffice(tmp_path / "desk.db")
    try:
        quick = _world(office, "Quick Funders")
        glatt = _world(office, "Glatt Express")
        item = office.teach(text=MCA)
        worlds = {route["world_name"] for route in item["routes"]}
        agents = {route["specialist_id"] for route in item["routes"]}
        assert worlds == {"Quick Funders"}
        assert "executive_assistant" in agents
        assert "marketing_content" not in agents
        assert office.store.knowledge_count(quick["id"]) == 1
        assert office.store.knowledge_count(glatt["id"]) == 0
        assert "stackrate" in " ".join(
            office._recall("stackrate underwriting", quick["id"], "executive_assistant")
        )
        assert office._recall("stackrate", glatt["id"], "second_brain") == []
        before = _brief(office, quick["id"], "executive_assistant")
        assert "stackrate" not in before
        proposals = office.playbooks("pending")
        assert len(proposals) == 1
        assert proposals[0]["specialist_id"] == "executive_assistant"
        office.decide_playbook(proposals[0]["id"], approve=True)
        assert "stackrate" in _brief(office, quick["id"], "executive_assistant")
        detail = office.run_mission(
            "What are today's priorities for underwriting?",
            world_id=quick["id"],
        )
        assistant = next(
            item
            for item in detail["deliverables"]
            if item["specialist_id"] == "executive_assistant"
        )
        assert "stackrate" in assistant["body"]
        other = office.run_mission(
            "What are today's priorities for underwriting?",
            world_id=glatt["id"],
        )
        leaked = " ".join(item["body"] for item in other["deliverables"])
        assert "stackrate" not in leaked
    finally:
        office.close()


def test_content_strategy_reaches_marketing_everywhere(tmp_path):
    office = PersonalOffice(tmp_path / "desk.db")
    try:
        item = office.teach(
            text=(
                "A content strategy for campaigns. "
                "Speak to one audience until the offer is clear."
            )
        )
        marketing = [
            route
            for route in item["routes"]
            if route["specialist_id"] == "marketing_content"
        ]
        assert len(marketing) == len(office.store.list_worlds())
        assert office.playbooks("pending") == []
    finally:
        office.close()


def test_explicit_target_overrides_the_topic(tmp_path):
    office = PersonalOffice(tmp_path / "desk.db")
    try:
        personal = _world(office, "Personal")
        item = office.teach(
            text="Diamond buying notes for a jewelry bench.",
            world_id=personal["id"],
            specialist_id="marketing_content",
        )
        assert [
            (route["world_name"], route["specialist_id"]) for route in item["routes"]
        ] == [("Personal", "marketing_content")]
    finally:
        office.close()


def test_reroute_and_remove_move_the_memory(tmp_path):
    office = PersonalOffice(tmp_path / "desk.db")
    try:
        quick = _world(office, "Quick Funders")
        glatt = _world(office, "Glatt Express")
        item = office.teach(text=MCA)
        moved = office.reroute_knowledge(
            item["id"],
            world_id=glatt["id"],
            specialist_id="marketing_content",
        )
        assert [route["world_name"] for route in moved["routes"]] == ["Glatt Express"]
        assert office._recall("stackrate", quick["id"], "executive_assistant") == []
        assert "stackrate" in " ".join(
            office._recall("stackrate", glatt["id"], "marketing_content")
        )
        office.remove_knowledge(item["id"])
        assert office._recall("stackrate", glatt["id"], "marketing_content") == []
        assert office.list_knowledge() == []
    finally:
        office.close()


def test_files_and_video_captions_are_readable():
    xml = "<transcript><text>Always confirm the stackrate.</text></transcript>"
    assert "stackrate" in captions_from_xml(xml)
    payload = '{"events":[{"segs":[{"utf8":"Pull bank statements."}]}]}'
    assert captions_from_json3(payload) == "Pull bank statements."
    page = (
        "<html><title>MCA underwriting - YouTube</title>"
        '"captionTracks":[{"baseUrl":"https://example.test/cap",'
        '"languageCode":"en"}]</html>'
    )

    def get(url: str) -> str:
        if "example.test/cap" in url:
            return xml
        return page

    fetched = fetch_link("https://youtu.be/abcdefghijk", get=get)
    assert fetched["kind"] == "video"
    assert "stackrate" in fetched["text"]
    assert "MCA underwriting" in fetched["title"]
    assert "stackrate" in extract_text("notes.txt", b"Always confirm the stackrate.")
    pdf = b"(Always confirm the stackrate in the file.)"
    assert "stackrate" in extract_text("lesson.pdf", pdf)
    document = _docx("Always confirm the stackrate in the doc.")
    assert "stackrate" in extract_text("lesson.docx", document)


def test_phone_link_teaches_instead_of_running_a_mission(tmp_path):
    office = PersonalOffice(tmp_path / "desk.db")
    try:
        office.source_reader = lambda url: {
            "title": "MCA underwriting",
            "text": MCA,
            "kind": "video",
        }
        gate = PhoneGate(telegram_chat_ids=("7",))
        reply = gate.reply_for(
            office,
            "telegram",
            "7",
            "https://youtu.be/abcdefghijk",
        )
        assert reply is not None
        assert "Quick Funders" in reply
        assert "Executive Assistant" in reply
        assert office.store.list_missions() == []
    finally:
        office.close()


def test_reject_leaves_the_playbook(tmp_path):
    office = PersonalOffice(tmp_path / "desk.db")
    try:
        quick = _world(office, "Quick Funders")
        before = _brief(office, quick["id"], "executive_assistant")
        office.teach(text=MCA)
        proposal = office.playbooks("pending")[0]
        office.decide_playbook(proposal["id"], approve=False)
        assert _brief(office, quick["id"], "executive_assistant") == before
    finally:
        office.close()


def test_knowledge_api_upload_and_reroute(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from openjarvis.personal.routes import personal_router

    office = PersonalOffice(tmp_path / "desk.db")
    app = FastAPI()
    app.state.personal_office = office
    app.include_router(personal_router)
    client = TestClient(app)
    try:
        created = client.post(
            "/v1/personal/knowledge/file",
            files={"file": ("lesson.txt", io.BytesIO(MCA.encode()), "text/plain")},
            data={"text": ""},
        )
        assert created.status_code == 200, created.text
        item = created.json()
        assert item["kind"] == "file"
        glatt = _world(office, "Glatt Express")
        moved = client.post(
            f"/v1/personal/knowledge/{item['id']}/route",
            json={"world_id": glatt["id"], "specialist_id": "second_brain"},
        )
        assert moved.status_code == 200, moved.text
        assert moved.json()["routes"][0]["world_name"] == "Glatt Express"
        learned = client.get("/v1/personal/knowledge/learned")
        assert learned.status_code == 200
        names = [world["name"] for world in learned.json()["worlds"]]
        assert names == ["Glatt Express"]
    finally:
        office.close()


def _docx(text: str) -> bytes:
    xml = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()
