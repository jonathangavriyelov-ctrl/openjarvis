"""Higgsfield, SuperClaude commands, ELI5, and editable projects."""

from __future__ import annotations

from openjarvis.personal.higgsfield import HiggsfieldClient, resolve_credentials
from openjarvis.personal.office import PersonalOffice
from openjarvis.personal.superclaude import find_command, load_command_dir


def test_higgsfield_skips_without_a_key(monkeypatch):
    monkeypatch.delenv("HF_KEY", raising=False)
    monkeypatch.delenv("HF_CREDENTIALS", raising=False)
    monkeypatch.delenv("HIGGSFIELD_API_KEY", raising=False)
    monkeypatch.delenv("HF_API_KEY_ID", raising=False)
    monkeypatch.delenv("HF_API_KEY_SECRET", raising=False)
    assert resolve_credentials("") == ""
    assets = HiggsfieldClient("").illustrate("a launch poster")
    assert assets[0]["status"] == "skipped"
    assert "not connected" in assets[0]["detail"]
    assert HiggsfieldClient("").public_status()["configured"] is False


def test_higgsfield_submits_and_polls_without_leaking_the_key():
    calls: list[tuple] = []

    def http(method, url, payload, header):
        calls.append((method, url, payload, header))
        if method == "POST" and "text-to-video" in url:
            return (
                200,
                {
                    "status": "queued",
                    "request_id": "vid",
                    "status_url": "https://api.higgsfield.ai/requests/vid/status",
                },
            )
        if method == "POST":
            return (
                200,
                {
                    "status": "queued",
                    "request_id": "abc",
                    "status_url": "https://api.higgsfield.ai/requests/abc/status",
                },
            )
        if url.endswith("/vid/status"):
            return (
                200,
                {
                    "status": "completed",
                    "video": {"url": "https://cdn.example/clip.mp4"},
                },
            )
        return (
            200,
            {"status": "completed", "images": [{"url": "https://cdn.example/pic.jpg"}]},
        )

    client = HiggsfieldClient(
        "test-id:test-secret",
        http=http,
        sleeper=lambda _seconds: None,
        max_polls=2,
    )
    assets = client.illustrate("a poster and a clip", video=True)
    assert assets[0]["url"] == "https://cdn.example/pic.jpg"
    assert assets[1]["kind"] == "video"
    assert assets[1]["url"] == "https://cdn.example/clip.mp4"
    assert calls[0][0] == "POST"
    assert calls[0][1].endswith("higgsfield-ai/soul/v2/standard")
    assert calls[0][3] == "Key test-id:test-secret"
    assert "test-secret" not in str(client.public_status())
    assert all("test-secret" not in asset["detail"] for asset in assets)


def test_superclaude_command_routes_and_loads_a_file(tmp_path):
    command = find_command("/sc:brainstorm the offer")
    assert command is not None
    assert command.specialists == ("marketing_content", "second_brain")
    assert command.mode == "brainstorming"
    (tmp_path / "brand.md").write_text(
        "name: brand\ndescription: Design the brand voice for marketing.\n",
        encoding="utf-8",
    )
    loaded = load_command_dir(tmp_path)
    assert loaded[0].name == "brand"
    assert loaded[0].source == "file"
    assert "marketing_content" in loaded[0].specialists
    office = PersonalOffice(tmp_path / "os.db", superclaude_dir=str(tmp_path))
    detail = office.run_mission("/sc:brand a line for the homepage")
    assert detail["command"] == "brand"
    assert {task["specialist_id"] for task in detail["tasks"]} == {"marketing_content"}


def test_eli5_changes_the_offline_brief(tmp_path):
    office = PersonalOffice(tmp_path / "os.db")
    office.set_eli5(True)
    detail = office.run_mission("/sc:pm what should I do today")
    body = detail["deliverables"][0]["body"]
    assert "What to do today" in body
    assert office.world()["eli5"] is True


def test_projects_are_editable_and_receive_work(tmp_path):
    office = PersonalOffice(tmp_path / "os.db")
    names = [project["name"] for project in office.store.list_projects()]
    assert names == ["Quick Funders CRM", "Self Audit"]
    assert all(project["example"] for project in office.store.list_projects())
    crm = office.store.list_projects()[0]
    renamed = office.store.update_project(
        crm["id"], name="Quick Funders CRM", summary="Deals."
    )
    assert renamed is not None
    assert renamed["summary"] == "Deals."
    detail = office.run_mission("Draft a launch clip for Quick Funders CRM")
    assert detail["project_id"] == crm["id"]
    world = office.world()
    plot = next(item for item in world["projects"] if item["id"] == crm["id"])
    assert plot["tasks"]
    assert any(work["to"] == crm["id"] for work in world["works"])
    office.store.delete_project(crm["id"])
    again = PersonalOffice(tmp_path / "os.db")
    left = [project["name"] for project in again.store.list_projects()]
    assert "Quick Funders CRM" not in left
    office.close()
    again.close()


def test_marketing_records_a_skipped_picture_without_a_key(tmp_path, monkeypatch):
    monkeypatch.delenv("HF_KEY", raising=False)
    monkeypatch.delenv("HF_CREDENTIALS", raising=False)
    monkeypatch.delenv("HIGGSFIELD_API_KEY", raising=False)
    monkeypatch.delenv("HF_API_KEY_ID", raising=False)
    monkeypatch.delenv("HF_API_KEY_SECRET", raising=False)
    office = PersonalOffice(tmp_path / "os.db")
    detail = office.run_mission("Draft a launch post")
    marketing = next(
        item
        for item in detail["deliverables"]
        if item["specialist_id"] == "marketing_content"
    )
    assert "not connected" in marketing["body"]
    assert marketing["media"][0]["status"] == "skipped"
    assert office.world()["higgsfield"]["configured"] is False
    office.close()
