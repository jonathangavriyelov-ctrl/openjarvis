"""HTTP API for the personal AI OS dashboard."""

from __future__ import annotations

import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from openjarvis.personal.office import PersonalOffice
from openjarvis.personal.specialists import get_specialist

personal_router = APIRouter(prefix="/v1/personal", tags=["personal"])


class MissionRequest(BaseModel):
    request: str = Field(..., min_length=1)
    project_id: Optional[str] = None


class GoalRequest(BaseModel):
    title: str = Field(..., min_length=1)
    target: str = "Completed"
    deadline: Optional[str] = None
    progress: float = 0
    project_id: Optional[str] = None


class GoalUpdateRequest(BaseModel):
    title: Optional[str] = None
    target: Optional[str] = None
    deadline: Optional[str] = None
    progress: Optional[float] = None
    notes: Optional[str] = None
    project_id: Optional[str] = None


class SettingsRequest(BaseModel):
    eli5: Optional[bool] = None


class ProjectRequest(BaseModel):
    name: str = Field(..., min_length=1)
    summary: str = ""
    accent: str = "#7dcea0"


class ProjectUpdateRequest(BaseModel):
    name: Optional[str] = None
    summary: Optional[str] = None
    accent: Optional[str] = None


class MilestoneRequest(BaseModel):
    done: bool = True


class NoteRequest(BaseModel):
    title: str = ""
    body: str = Field(..., min_length=1)
    tags: str = ""


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)


def _office_from_app(request: Request) -> PersonalOffice:
    """Return the process-wide office, creating it from server config once."""
    existing = getattr(request.app.state, "personal_office", None)
    if existing is not None:
        return existing

    config = getattr(request.app.state, "config", None)
    personal = getattr(config, "personal", None) if config is not None else None
    db_path = os.environ.get("OPENJARVIS_PERSONAL_DB", "")
    hermes_model = os.environ.get("OPENJARVIS_HERMES_MODEL", "")
    fallback = ""
    if personal is not None:
        db_path = db_path or getattr(personal, "db_path", "") or ""
        hermes_model = hermes_model or getattr(personal, "hermes_model", "") or ""
        fallback = getattr(personal, "fallback_model", "") or ""
    if not db_path:
        from openjarvis.core.paths import get_config_dir

        db_path = str(get_config_dir() / "personal_os.db")
    intelligence = getattr(config, "intelligence", None) if config is not None else None
    default_model = getattr(request.app.state, "model", "") or ""
    if not fallback and intelligence is not None:
        fallback = getattr(intelligence, "default_model", "") or ""
    schedule_checkins = True
    higgsfield_key = ""
    image_model = ""
    video_model = ""
    superclaude_dir = ""
    if personal is not None:
        schedule_checkins = bool(getattr(personal, "schedule_checkins", True))
        higgsfield_key = getattr(personal, "higgsfield_key", "") or ""
        image_model = getattr(personal, "higgsfield_image_model", "") or ""
        video_model = getattr(personal, "higgsfield_video_model", "") or ""
        superclaude_dir = getattr(personal, "superclaude_dir", "") or ""
    office = PersonalOffice(
        db_path,
        engine=getattr(request.app.state, "engine", None),
        memory=getattr(request.app.state, "memory_backend", None),
        scheduler=getattr(request.app.state, "task_scheduler", None),
        bus=getattr(request.app.state, "bus", None),
        hermes_model=hermes_model or "hermes3",
        fallback_model=fallback,
        default_model=default_model or fallback,
        schedule_checkins=schedule_checkins,
        higgsfield_key=higgsfield_key,
        higgsfield_image_model=image_model,
        higgsfield_video_model=video_model,
        superclaude_dir=superclaude_dir,
    )
    request.app.state.personal_office = office
    return office


def _goal_or_404(office: PersonalOffice, goal_id: str) -> dict[str, Any]:
    for goal in office.list_goals():
        if goal["id"] == goal_id:
            return goal
    raise HTTPException(status_code=404, detail="Goal not found")


@personal_router.get("/world")
def personal_world(request: Request) -> dict[str, Any]:
    """Eco-world snapshot: who is here, what they are doing, who delegated."""
    return _office_from_app(request).world()


@personal_router.get("/roster")
def personal_roster(request: Request) -> dict[str, Any]:
    office = _office_from_app(request)
    return {"agents": office.roster(), "cards": office.agent_cards()}


@personal_router.get("/hermes")
def personal_hermes(request: Request) -> dict[str, Any]:
    """Which model the Executive Assistant will call."""
    return _office_from_app(request).model_choices()


@personal_router.get("/agents/{specialist_id}")
def personal_agent(specialist_id: str, request: Request) -> dict[str, Any]:
    office = _office_from_app(request)
    try:
        get_specialist(specialist_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return office.agent_view(specialist_id)


@personal_router.post("/missions")
def personal_submit_mission(body: MissionRequest, request: Request) -> dict[str, Any]:
    """Hand a request to the chief of staff. Poll the mission until it settles."""
    office = _office_from_app(request)
    try:
        mission = office.submit_mission(body.request, project_id=body.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return mission


@personal_router.get("/missions")
def personal_list_missions(request: Request) -> dict[str, Any]:
    office = _office_from_app(request)
    return {"missions": office.store.list_missions()}


@personal_router.get("/missions/{mission_id}")
def personal_get_mission(mission_id: str, request: Request) -> dict[str, Any]:
    office = _office_from_app(request)
    try:
        return office.mission_detail(mission_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Mission not found") from exc


@personal_router.post("/checkin")
def personal_checkin(request: Request) -> dict[str, Any]:
    """Ask the executive assistant for today's priorities against open goals."""
    office = _office_from_app(request)
    goals = office.list_goals()
    if goals:
        lines = [
            f"- {goal['title']} ({goal['pace']}, {int(goal['progress'])}%)"
            for goal in goals[:8]
        ]
        board = "\n".join(lines)
    else:
        board = "- No goals yet."
    prompt = (
        "Daily check-in. Review Jonathan's goals and set today's three priorities.\n"
        f"{board}"
    )
    return office.run_mission(prompt)


@personal_router.get("/goals")
def personal_list_goals(request: Request) -> dict[str, Any]:
    office = _office_from_app(request)
    return {"goals": office.list_goals(), "checkins": office.store.list_checkins()}


@personal_router.post("/goals")
def personal_create_goal(body: GoalRequest, request: Request) -> dict[str, Any]:
    office = _office_from_app(request)
    progress = max(0.0, min(100.0, body.progress))
    return office.create_goal(
        body.title,
        target=body.target,
        deadline=body.deadline,
        progress=progress,
        project_id=body.project_id,
    )


@personal_router.patch("/goals/{goal_id}")
def personal_update_goal(
    goal_id: str,
    body: GoalUpdateRequest,
    request: Request,
) -> dict[str, Any]:
    office = _office_from_app(request)
    fields = body.model_dump(exclude_unset=True)
    if "progress" in fields and fields["progress"] is not None:
        fields["progress"] = max(0.0, min(100.0, float(fields["progress"])))
    goal = office.update_goal(goal_id, **fields)
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    return goal


@personal_router.post("/goals/{goal_id}/milestones/{milestone_id}")
def personal_milestone(
    goal_id: str,
    milestone_id: str,
    body: MilestoneRequest,
    request: Request,
) -> dict[str, Any]:
    office = _office_from_app(request)
    _goal_or_404(office, goal_id)
    goal = office.set_milestone_done(milestone_id, body.done)
    if goal is None or goal["id"] != goal_id:
        raise HTTPException(status_code=404, detail="Milestone not found")
    return goal


@personal_router.get("/deliverables")
def personal_deliverables(request: Request, specialist_id: str = "") -> dict[str, Any]:
    office = _office_from_app(request)
    return {"deliverables": office.store.list_deliverables(specialist_id=specialist_id)}


@personal_router.get("/notes")
def personal_notes(request: Request) -> dict[str, Any]:
    office = _office_from_app(request)
    return {"notes": office.store.list_notes()}


@personal_router.post("/notes")
def personal_capture_note(body: NoteRequest, request: Request) -> dict[str, Any]:
    office = _office_from_app(request)
    title = body.title.strip() or body.body.strip().split("\n", 1)[0][:80]
    return office.capture_note(title, body.body, tags=body.tags)


@personal_router.post("/notes/ask")
def personal_ask(body: AskRequest, request: Request) -> dict[str, Any]:
    return _office_from_app(request).ask_memory(body.question)


@personal_router.get("/settings")
def personal_settings(request: Request) -> dict[str, Any]:
    return _office_from_app(request).settings_view()


@personal_router.put("/settings")
def personal_update_settings(body: SettingsRequest, request: Request) -> dict[str, Any]:
    office = _office_from_app(request)
    if body.eli5 is not None:
        office.set_eli5(body.eli5)
    return office.settings_view()


@personal_router.get("/projects")
def personal_projects(request: Request) -> dict[str, Any]:
    return {"projects": _office_from_app(request).project_board()}


@personal_router.post("/projects")
def personal_create_project(body: ProjectRequest, request: Request) -> dict[str, Any]:
    office = _office_from_app(request)
    return office.store.create_project(
        body.name, summary=body.summary, accent=body.accent
    )


@personal_router.patch("/projects/{project_id}")
def personal_update_project(
    project_id: str,
    body: ProjectUpdateRequest,
    request: Request,
) -> dict[str, Any]:
    project = _office_from_app(request).store.update_project(
        project_id, **body.model_dump(exclude_unset=True)
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@personal_router.delete("/projects/{project_id}")
def personal_delete_project(project_id: str, request: Request) -> dict[str, Any]:
    deleted = _office_from_app(request).store.delete_project(project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"deleted": True}
