"""Orchestration tests for the personal chief of staff."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from openjarvis.a2a.protocol import TaskState
from openjarvis.core.events import EventBus, EventType
from openjarvis.personal.goals import (
    assess_goal,
    parse_deadline,
    propose_goal,
)
from openjarvis.personal.hermes import (
    resolve_configured_model,
    resolve_executive_model,
)
from openjarvis.personal.office import PersonalOffice
from openjarvis.personal.planner import plan_from_model_text, plan_request
from openjarvis.personal.specialists import (
    Produced,
    Specialist,
    get_specialist,
    register_specialist,
    unregister_specialist,
)
from openjarvis.scheduler.scheduler import TaskScheduler
from openjarvis.scheduler.store import SchedulerStore
from openjarvis.tools.storage._stubs import RetrievalResult


class _Engine:
    def __init__(self, models, reply):
        self.models = list(models)
        self.reply = reply
        self.calls = []
        self.systems = []

    def health(self):
        return True

    def list_models(self):
        return list(self.models)

    def generate(self, messages, *, model, temperature=0.7, max_tokens=1024, **kwargs):
        del temperature, max_tokens, kwargs
        user = messages[-1].content or ""
        system = messages[0].content or ""
        self.calls.append(model)
        self.systems.append(system)
        if callable(self.reply):
            return {"content": self.reply(user, system, model)}
        return {"content": self.reply}


class _Memory:
    def __init__(self):
        self.docs = []

    def store(self, content, *, source="", metadata=None):
        self.docs.append({"content": content, "source": source, "metadata": metadata})
        return f"mem-{len(self.docs)}"

    def search(self, query, top_k=5):
        del query
        return [
            RetrievalResult(content=doc["content"], score=1.0, source=doc["source"])
            for doc in self.docs[:top_k]
        ]


def test_planner_routes_to_matching_specialists():
    goal = plan_request("Set a goal to ship the dashboard by 2026-12-01")
    assert [task.specialist_id for task in goal] == ["executive_assistant"]

    content = plan_request("Draft a launch post and a content calendar")
    assert [task.specialist_id for task in content] == ["marketing_content"]

    memory = plan_request("Remember that the product voice stays calm")
    assert [task.specialist_id for task in memory] == ["second_brain"]

    general = plan_request("Prepare the Monday brief")
    assert [task.specialist_id for task in general] == [
        "executive_assistant",
        "second_brain",
    ]


def test_custom_specialist_is_delegated_to():
    spec = Specialist(
        id="finance_clerk",
        name="Finance Clerk",
        title="watches the ledger",
        description="Books and balances.",
        niche="Stream",
        accent="#88c0d0",
        skills=(),
        triggers=("ledger",),
        system_prompt="You keep the ledger.",
        kind="brief",
        produce=lambda ctx: Produced(
            title="Ledger note",
            kind="brief",
            body=f"Recorded: {ctx.request}",
        ),
    )
    register_specialist(spec)
    try:
        planned = plan_request("Update the ledger before Friday")
        assert [task.specialist_id for task in planned] == ["finance_clerk"]
        with pytest.raises(ValueError):
            unregister_specialist("executive_assistant")
    finally:
        unregister_specialist("finance_clerk")
    assert all(task.specialist_id != "finance_clerk" for task in plan_request("hello"))


def test_countable_asks_become_separate_tasks():
    ideas = plan_request("Draft 3 Instagram post ideas")
    marketing = [task for task in ideas if task.specialist_id == "marketing_content"]
    assert len(marketing) == 3
    assert [task.title for task in marketing] == [
        "Instagram post idea 1 of 3",
        "Instagram post idea 2 of 3",
        "Instagram post idea 3 of 3",
    ]
    assert "Write only this piece (1 of 3)" in marketing[0].brief
    others = [task for task in ideas if task.specialist_id != "marketing_content"]
    assert len(others) == 1

    capped = [
        task
        for task in plan_request("Draft 12 posts")
        if task.specialist_id == "marketing_content"
    ]
    assert len(capped) == 5
    assert capped[0].title == "post 1 of 5"

    single = plan_request("Draft a launch post and a content calendar")
    assert [task.specialist_id for task in single] == ["marketing_content"]


def test_model_plan_keeps_parallel_pieces_and_fills_a_short_plan():
    one = json.dumps(
        {
            "tasks": [
                {
                    "specialist_id": "marketing_content",
                    "title": "Instagram Post Idea #1",
                    "brief": "Only the first idea.",
                }
            ]
        }
    )
    expanded = plan_from_model_text(one, request="Draft 3 Instagram post ideas")
    assert expanded is not None
    assert len(expanded) == 3
    assert expanded[0].specialist_id == "marketing_content"
    assert expanded[0].title == "Instagram post idea 1 of 3"

    three = json.dumps(
        {
            "tasks": [
                {"specialist_id": "marketing_content", "title": "A", "brief": "a"},
                {"specialist_id": "marketing_content", "title": "B", "brief": "b"},
                {"specialist_id": "marketing_content", "title": "C", "brief": "c"},
            ]
        }
    )
    kept = plan_from_model_text(three, request="Draft 3 Instagram post ideas")
    assert kept is not None
    assert [task.title for task in kept] == ["A", "B", "C"]


def test_model_plan_overrides_keywords_when_it_names_real_specialists():
    raw = json.dumps(
        {
            "tasks": [
                {
                    "specialist_id": "second_brain",
                    "title": "Keep the positioning",
                    "brief": "Store the positioning.",
                },
                {"specialist_id": "not_a_real_agent", "title": "Ignore", "brief": "No"},
            ]
        }
    )
    planned = plan_from_model_text(raw, request="Draft a launch post")
    assert planned is not None
    assert [task.specialist_id for task in planned] == ["second_brain"]
    assert plan_from_model_text("not json", request="Draft a post") is None


def test_executive_assistant_prefers_hermes3_8b_then_any_local_model():
    exact = resolve_executive_model(
        "hermes3:8b",
        "qwen3.5:4b",
        ["qwen3.5:4b", "hermes3:8b"],
        True,
    )
    assert exact.source == "hermes"
    assert exact.model_id == "hermes3:8b"

    qwen = resolve_executive_model(
        "hermes3:8b",
        "qwen3.5:4b",
        ["llama3", "qwen3.5:4b"],
        True,
    )
    assert qwen.source == "fallback"
    assert qwen.model_id == "qwen3.5:4b"

    other = resolve_executive_model(
        "hermes3:8b",
        "",
        ["llama3"],
        True,
    )
    assert other.model_id == "llama3"


def test_hermes_resolution_prefers_installed_hermes_then_falls_back():
    exact = resolve_executive_model(
        "hermes3",
        "qwen3.5:4b",
        ["qwen3.5:4b", "hermes3:8b"],
        True,
    )
    assert exact.source == "hermes"
    assert exact.model_id == "hermes3:8b"

    other = resolve_executive_model(
        "hermes3",
        "qwen3.5:4b",
        ["nous-hermes2", "qwen3.5:4b"],
        True,
    )
    assert other.source == "hermes"
    assert other.model_id == "nous-hermes2"

    fallback = resolve_executive_model(
        "hermes3",
        "qwen3.5:4b",
        ["qwen3.5:4b"],
        True,
    )
    assert fallback.source == "fallback"
    assert fallback.model_id == "qwen3.5:4b"

    offline = resolve_executive_model("hermes3", "qwen3.5:4b", [], False)
    assert offline.source == "offline"
    assert offline.model_id == ""

    configured = resolve_configured_model("qwen3.5:4b", ["qwen3.5:4b"], True)
    assert configured.model_id == "qwen3.5:4b"

    from openjarvis.personal.hermes import listed_variant

    assert listed_variant("hermes3", ["qwen3.5:4b", "hermes3:8b"]) == "hermes3:8b"
    assert listed_variant("hermes3", ["hermes3-8b"]) == "hermes3-8b"
    assert listed_variant("qwen3", ["qwen3.5:4b", "qwen3:8b"]) == "qwen3:8b"
    assert listed_variant("hermes3", ["hermes4:8b"]) is None


def test_goal_pace_and_deadline_parsing():
    assert parse_deadline("ship by 2026-12-01").startswith("2026-12-01")
    assert parse_deadline("ship by June 1, 2026").startswith("2026-06-01")
    in_ten = parse_deadline(
        "finish in 10 days",
        today=datetime(2026, 1, 1, tzinfo=timezone.utc).date(),
    )
    assert in_ten.startswith("2026-01-11")

    proposed = propose_goal(
        "Set a goal to ship the AI OS by 2026-12-01. Target: working dashboard."
    )
    assert proposed is not None
    assert proposed["target"] == "working dashboard"
    assert proposed["deadline"].startswith("2026-12-01")
    packed = propose_goal(
        "Set a goal to launch the product by 2026-12-01, draft a post, "
        "and remember the voice. Target: a working dashboard."
    )
    assert packed is not None
    assert packed["title"] == "launch the product by 2026-12-01"
    assert packed["target"] == "a working dashboard"
    assert propose_goal("Daily check-in for the goal board") is None

    created = "2026-01-01T00:00:00+00:00"
    deadline = "2026-01-11T00:00:00+00:00"
    halfway = datetime(2026, 1, 6, tzinfo=timezone.utc)
    base = {
        "progress": 0,
        "created_at": created,
        "deadline": deadline,
    }
    assert assess_goal({**base, "progress": 100}, now=halfway) == "complete"
    assert assess_goal({**base, "progress": 45}, now=halfway) == "on_track"
    assert assess_goal({**base, "progress": 30}, now=halfway) == "at_risk"
    assert assess_goal({**base, "progress": 0}, now=halfway) == "behind"
    assert assess_goal({**base, "deadline": ""}, now=halfway) == "on_track"
    late = datetime(2026, 1, 12, tzinfo=timezone.utc)
    assert assess_goal(base, now=late) == "behind"


def test_mission_delegates_and_collects_deliverables(tmp_path):
    bus = EventBus(record_history=True)
    memory = _Memory()
    scheduler = TaskScheduler(SchedulerStore(tmp_path / "sched.db"))
    office = PersonalOffice(
        tmp_path / "personal.db",
        memory=memory,
        scheduler=scheduler,
        bus=bus,
    )
    try:
        detail = office.run_mission(
            "Set a goal to launch the product by 2026-12-01, draft a post, "
            "and remember the calm voice. Target: a working dashboard."
        )
        ids = [task["specialist_id"] for task in detail["tasks"]]
        assert ids == [
            "executive_assistant",
            "marketing_content",
            "second_brain",
        ]
        assert detail["status"] == "completed"
        assert {item["specialist_id"] for item in detail["deliverables"]} == set(ids)
        completed = TaskState.COMPLETED.value
        assert all(task["a2a"]["state"] == completed for task in detail["tasks"])
        assert detail["workflow"]["success"] is True
        agent_nodes = [
            node["id"]
            for node in detail["workflow"]["nodes"]
            if node["type"] == "agent"
        ]
        assert detail["workflow"]["edges"] == [
            {"source": node_id, "target": "collect"} for node_id in agent_nodes
        ]
        stages = office._delegation_graph("preview", detail["tasks"]).execution_stages()
        assert stages[0] == sorted(agent_nodes)
        assert stages[1] == ["collect"]

        goals = office.list_goals()
        assert len(goals) == 1
        assert goals[0]["deadline"].startswith("2026-12-01")
        assert goals[0]["target"] == "a working dashboard"
        assert goals[0]["on_track"] == "on_track"
        assert len(goals[0]["milestones"]) == 3
        assert office.store.list_checkins()[0]["scheduler_task_id"]
        scheduled = scheduler.list_tasks()
        assert scheduled[0].agent == "executive_assistant"
        assert scheduled[0].metadata["personal"] == "goal_checkin"

        notes = office.store.list_notes()
        assert notes
        assert memory.docs
        assert memory.docs[0]["source"] == "personal.second_brain"

        world = office.world()
        assert world["mission"]["id"] == detail["id"]
        assert {edge["to"] for edge in world["edges"]} == set(ids)
        chief = next(
            agent for agent in world["agents"] if agent["id"] == "chief_of_staff"
        )
        assert chief["status"] == "done"
        workers = [
            agent for agent in world["agents"] if agent["id"] != "chief_of_staff"
        ]
        assert any(agent["status"] == "done" for agent in workers)
        kinds = {event.event_type for event in bus.history}
        assert EventType.WORKFLOW_START in kinds
        assert EventType.WORKFLOW_END in kinds

        answer = office.ask_memory("calm voice")
        assert "calm" in answer["answer"].lower()
    finally:
        scheduler.stop()
        office.close()


def test_executive_assistant_uses_hermes_and_other_agents_use_fallback(tmp_path):
    engine = _Engine(
        ["hermes3:8b", "qwen3.5:4b"],
        "## Prepared\n\nThe next step is written down.",
    )

    def reply(user, system, model):
        del system, model
        if "Split the request" in user:
            return "no plan"
        return "## Prepared\n\nThe next step is written down."

    engine.reply = reply
    office = PersonalOffice(
        tmp_path / "personal.db",
        engine=engine,
        hermes_model="hermes3",
        fallback_model="qwen3.5:4b",
    )
    try:
        detail = office.run_mission(
            "Set today's priorities and draft a launch post about the calm voice"
        )
        by_agent = {item["specialist_id"]: item for item in detail["deliverables"]}
        assert by_agent["executive_assistant"]["model_id"] == "hermes3:8b"
        assert by_agent["executive_assistant"]["model_source"] == "hermes"
        assert by_agent["marketing_content"]["model_id"] == "qwen3.5:4b"
        assert by_agent["marketing_content"]["model_source"] == "fallback"
        assert any("personal-goal-tracking" in system for system in engine.systems)
        assert get_specialist("executive_assistant").prefers_hermes is True
    finally:
        office.close()


def test_model_plan_is_what_the_chief_delegates(tmp_path):
    def reply(user, system, model):
        del system, model
        if "Split the request" in user:
            return json.dumps(
                {
                    "tasks": [
                        {
                            "specialist_id": "second_brain",
                            "title": "Keep this",
                            "brief": "Store the positioning.",
                        }
                    ]
                }
            )
        return "## Noted\n\nStored."

    office = PersonalOffice(
        tmp_path / "personal.db",
        engine=_Engine(["qwen3.5:4b"], reply),
        fallback_model="qwen3.5:4b",
    )
    try:
        detail = office.run_mission("Draft a launch post")
        assert [task["specialist_id"] for task in detail["tasks"]] == ["second_brain"]
        assert detail["model"]["planner_source"] == "fallback"
    finally:
        office.close()


def test_missing_hermes_falls_back_without_failing_the_mission(tmp_path):
    engine = _Engine(["qwen3.5:4b"], "## Priorities\n\n1. Ship the next slice.")

    def reply(user, system, model):
        del system, model
        if "Split the request" in user:
            return "nope"
        return "## Priorities\n\n1. Ship the next slice."

    engine.reply = reply
    office = PersonalOffice(
        tmp_path / "personal.db",
        engine=engine,
        hermes_model="hermes3",
        fallback_model="qwen3.5:4b",
    )
    try:
        detail = office.run_mission("What are today's priorities?")
        assistant = detail["deliverables"][0]
        assert assistant["specialist_id"] == "executive_assistant"
        assert assistant["model_source"] == "fallback"
        assert assistant["model_id"] == "qwen3.5:4b"
        hermes = office.model_choices()["executive_assistant"]
        assert hermes["source"] == "fallback"
    finally:
        office.close()


def test_personal_api_round_trip(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from openjarvis.personal.routes import mount_personal

    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path / "oj-home"))
    monkeypatch.delenv("OPENJARVIS_PERSONAL_OS", raising=False)
    monkeypatch.delenv("OPENJARVIS_API_KEY", raising=False)
    office = PersonalOffice(tmp_path / "personal.db")
    app = FastAPI()
    app.state.personal_office = office
    mount_personal(app)
    client = TestClient(app)
    setup = client.post(
        "/v1/personal/auth/setup",
        json={"password": "correct-horse"},
    )
    assert setup.status_code == 200, setup.text
    try:
        created = client.post(
            "/v1/personal/goals",
            json={
                "title": "Ship the personal OS",
                "target": "Dashboard in daily use",
                "deadline": "2026-12-01T23:59:59+00:00",
                "progress": 20,
            },
        )
        assert created.status_code == 200
        goal = created.json()
        assert goal["on_track"] == "on_track"
        assert goal["milestones"][0]["done"] is False

        moved = client.post(
            f"/v1/personal/goals/{goal['id']}/milestones/{goal['milestones'][0]['id']}",
            json={"done": True},
        )
        assert moved.status_code == 200
        assert moved.json()["progress"] == 25

        submitted = client.post(
            "/v1/personal/missions",
            json={"request": "Remember the pricing principle: charge for the outcome"},
        )
        assert submitted.status_code == 200
        mission_id = submitted.json()["id"]
        detail = {}
        for _ in range(20):
            detail = client.get(f"/v1/personal/missions/{mission_id}").json()
            if detail["status"] in {"completed", "failed"}:
                break
        assert detail["status"] == "completed"
        assert detail["tasks"][0]["specialist_id"] == "second_brain"

        world = client.get("/v1/personal/world").json()
        assert any(edge["to"] == "second_brain" for edge in world["edges"])
        notes = client.get("/v1/personal/notes").json()["notes"]
        assert notes
        asked = client.post(
            "/v1/personal/notes/ask",
            json={"question": "pricing principle"},
        )
        assert asked.status_code == 200
        assert "pricing" in asked.json()["answer"].lower()
        library = client.get("/v1/personal/deliverables").json()["deliverables"]
        assert library
        agent = client.get("/v1/personal/agents/second_brain").json()
        assert agent["status"] == "done"
        hermes = client.get("/v1/personal/hermes").json()
        assert hermes["executive_assistant"]["source"] == "offline"
    finally:
        office.close()
