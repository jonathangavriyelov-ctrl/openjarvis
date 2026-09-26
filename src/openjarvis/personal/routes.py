"""HTTP API for the personal AI OS dashboard."""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from openjarvis.personal.gate import request_unlocked
from openjarvis.personal.google_desk import resolve_google_desk_path
from openjarvis.personal.office import PersonalOffice
from openjarvis.personal.phone import resolve_phone_gate, start_phone
from openjarvis.personal.specialists import get_specialist

logger = logging.getLogger(__name__)

def require_session(request: Request) -> None:
    """Block desk data until the browser holds a session or an API key."""
    if not request_unlocked(request):
        raise HTTPException(status_code=401, detail="Sign in required")


personal_router = APIRouter(
    prefix="/v1/personal",
    tags=["personal"],
    dependencies=[Depends(require_session)],
)


def mount_personal(app) -> None:  # noqa: ANN001
    """Attach the sign-in routes and the locked desk routes."""
    from openjarvis.personal.auth_routes import auth_router

    app.include_router(auth_router)
    app.include_router(personal_router)


class MissionRequest(BaseModel):
    request: str = Field(..., min_length=1)
    project_id: Optional[str] = None
    world_id: Optional[str] = None
    scope: str = "auto"


class GoalRequest(BaseModel):
    title: str = Field(..., min_length=1)
    target: str = "Completed"
    deadline: Optional[str] = None
    progress: float = 0
    project_id: Optional[str] = None
    world_id: Optional[str] = None


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
    world_id: Optional[str] = None


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
    world_id: str = ""


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    world_id: str = ""


class DrivePullRequest(BaseModel):
    query: str = Field(..., min_length=1)
    world_id: str = ""


class WorldRequest(BaseModel):
    name: str = Field(..., min_length=1)
    summary: str = ""
    accent: str = "#7dcea0"
    kind: str = "business"


class WorldUpdateRequest(BaseModel):
    name: Optional[str] = None
    summary: Optional[str] = None
    accent: Optional[str] = None


class TeamUpdateRequest(BaseModel):
    enabled: Optional[bool] = None
    omniroute_model: Optional[str] = None
    higgsfield: Optional[bool] = None
    brief: Optional[str] = None


class AccountRequest(BaseModel):
    email: str = Field(..., min_length=1)
    credentials_path: str = ""
    label: str = ""


def _first(*values: object) -> str:
    for value in values:
        if value and str(value).strip():
            return str(value).strip()
    return ""


def _office_from_app(request: Request) -> PersonalOffice:
    """Return the process-wide office, creating it from server config once."""
    existing = getattr(request.app.state, "personal_office", None)
    if existing is not None:
        return existing

    config = getattr(request.app.state, "config", None)
    personal = getattr(config, "personal", None) if config is not None else None
    db_path = os.environ.get("OPENJARVIS_PERSONAL_DB", "")
    hermes_model = os.environ.get("OPENJARVIS_HERMES_MODEL", "")
    fallback = os.environ.get("OPENJARVIS_FALLBACK_MODEL", "")
    if personal is not None:
        db_path = db_path or getattr(personal, "db_path", "") or ""
        hermes_model = hermes_model or getattr(personal, "hermes_model", "") or ""
        fallback = fallback or getattr(personal, "fallback_model", "") or ""
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
    omniroute_enabled = False
    omniroute_base_url = ""
    omniroute_api_key = ""
    omniroute_model = "auto"
    omniroute_models: dict[str, str] = {}
    if personal is not None:
        schedule_checkins = bool(getattr(personal, "schedule_checkins", True))
        higgsfield_key = getattr(personal, "higgsfield_key", "") or ""
        image_model = getattr(personal, "higgsfield_image_model", "") or ""
        video_model = getattr(personal, "higgsfield_video_model", "") or ""
        superclaude_dir = getattr(personal, "superclaude_dir", "") or ""
        omniroute_enabled = bool(getattr(personal, "omniroute_enabled", False))
        omniroute_base_url = getattr(personal, "omniroute_base_url", "") or ""
        omniroute_api_key = getattr(personal, "omniroute_api_key", "") or ""
        omniroute_model = getattr(personal, "omniroute_model", "") or "auto"
        raw_models = getattr(personal, "omniroute_models", None) or {}
        if isinstance(raw_models, dict):
            omniroute_models = {
                str(key): str(value) for key, value in raw_models.items()
            }
    channel = getattr(config, "channel", None) if config is not None else None
    telegram_cfg = getattr(channel, "telegram", None)
    slack_cfg = getattr(channel, "slack", None)
    google_path = resolve_google_desk_path(
        db_path,
        _first(getattr(personal, "google_credentials_path", "") if personal else ""),
    )
    phone = resolve_phone_gate(
        _first(
            getattr(personal, "telegram_chat_id", "") if personal else "",
            getattr(telegram_cfg, "allowed_chat_ids", ""),
        ),
        _first(
            getattr(personal, "slack_user_id", "") if personal else "",
            getattr(slack_cfg, "allowed_user_ids", ""),
        ),
    )
    telegram_token = _first(
        os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        getattr(telegram_cfg, "bot_token", ""),
    )
    slack_bot = _first(
        os.environ.get("SLACK_BOT_TOKEN", ""),
        getattr(slack_cfg, "bot_token", ""),
    )
    slack_app = _first(
        os.environ.get("SLACK_APP_TOKEN", ""),
        getattr(slack_cfg, "app_token", ""),
    )
    office = PersonalOffice(
        db_path,
        engine=getattr(request.app.state, "engine", None),
        memory=getattr(request.app.state, "memory_backend", None),
        scheduler=getattr(request.app.state, "task_scheduler", None),
        bus=getattr(request.app.state, "bus", None),
        hermes_model=hermes_model or "hermes3:8b",
        fallback_model=fallback or "qwen3.5:4b",
        default_model=default_model or fallback,
        schedule_checkins=schedule_checkins,
        higgsfield_key=higgsfield_key,
        higgsfield_image_model=image_model,
        higgsfield_video_model=video_model,
        superclaude_dir=superclaude_dir,
        omniroute_enabled=omniroute_enabled,
        omniroute_base_url=omniroute_base_url,
        omniroute_api_key=omniroute_api_key,
        omniroute_model=omniroute_model,
        omniroute_models=omniroute_models,
        google_credentials_path=google_path,
        phone=phone,
    )
    request.app.state.personal_office = office
    try:
        start_phone(
            office,
            telegram_token=telegram_token,
            slack_bot_token=slack_bot,
            slack_app_token=slack_app,
        )
    except Exception:
        logger.exception("Phone bridge did not start")
    return office


def _goal_or_404(office: PersonalOffice, goal_id: str) -> dict[str, Any]:
    for goal in office.list_goals():
        if goal["id"] == goal_id:
            return goal
    raise HTTPException(status_code=404, detail="Goal not found")


@personal_router.get("/world")
def personal_world(
    request: Request, world_id: str = "", scope: str = ""
) -> dict[str, Any]:
    """Eco-world snapshot. scope=all is the archipelago; world_id zooms in."""
    return _office_from_app(request).world(world_id or None, scope=scope)


@personal_router.get("/worlds")
def personal_worlds(request: Request) -> dict[str, Any]:
    return {"worlds": _office_from_app(request).list_worlds()}


@personal_router.post("/worlds")
def personal_create_world(body: WorldRequest, request: Request) -> dict[str, Any]:
    office = _office_from_app(request)
    if body.kind == "personal":
        raise HTTPException(
            status_code=400, detail="The Personal world already exists."
        )
    try:
        return office.create_world(
            body.name,
            summary=body.summary,
            accent=body.accent,
            kind=body.kind,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@personal_router.patch("/worlds/{world_id}")
def personal_update_world(
    world_id: str, body: WorldUpdateRequest, request: Request
) -> dict[str, Any]:
    world = _office_from_app(request).rename_world(
        world_id, **body.model_dump(exclude_unset=True)
    )
    if world is None:
        raise HTTPException(status_code=404, detail="World not found")
    return world


@personal_router.delete("/worlds/{world_id}")
def personal_delete_world(world_id: str, request: Request) -> dict[str, Any]:
    result = _office_from_app(request).delete_world(world_id)
    if result == "personal":
        raise HTTPException(status_code=400, detail="The Personal world stays.")
    if result == "missing":
        raise HTTPException(status_code=404, detail="World not found")
    return {"deleted": True}


@personal_router.get("/worlds/{world_id}/team")
def personal_world_team(world_id: str, request: Request) -> dict[str, Any]:
    office = _office_from_app(request)
    if office.store.get_world(world_id) is None:
        raise HTTPException(status_code=404, detail="World not found")
    return {"team": office.world_team(world_id)}


@personal_router.put("/worlds/{world_id}/team/{specialist_id}")
def personal_update_team(
    world_id: str,
    specialist_id: str,
    body: TeamUpdateRequest,
    request: Request,
) -> dict[str, Any]:
    row = _office_from_app(request).update_world_team(
        world_id, specialist_id, **body.model_dump(exclude_unset=True)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Team member not found")
    return row


@personal_router.post("/worlds/{world_id}/accounts")
def personal_add_account(
    world_id: str, body: AccountRequest, request: Request
) -> dict[str, Any]:
    office = _office_from_app(request)
    try:
        return office.connect_google_account(
            world_id,
            email=body.email,
            credentials_path=body.credentials_path,
            label=body.label,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="World not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@personal_router.delete("/worlds/{world_id}/accounts/{account_id}")
def personal_delete_account(
    world_id: str, account_id: str, request: Request
) -> dict[str, Any]:
    del world_id
    removed = _office_from_app(request).disconnect_google_account(account_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"deleted": True}


@personal_router.get("/roster")
def personal_roster(request: Request) -> dict[str, Any]:
    office = _office_from_app(request)
    return {"agents": office.roster(), "cards": office.agent_cards()}


@personal_router.get("/hermes")
def personal_hermes(request: Request) -> dict[str, Any]:
    """Which model the Executive Assistant will call."""
    return _office_from_app(request).model_choices()


@personal_router.get("/agents/{specialist_id}")
def personal_agent(
    specialist_id: str, request: Request, world_id: str = ""
) -> dict[str, Any]:
    office = _office_from_app(request)
    try:
        get_specialist(specialist_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return office.agent_view(specialist_id, world_id or None)


@personal_router.post("/missions")
def personal_submit_mission(body: MissionRequest, request: Request) -> dict[str, Any]:
    """Hand a request to the chief of staff. Poll the mission until it settles."""
    office = _office_from_app(request)
    try:
        mission = office.submit_mission(
            body.request,
            project_id=body.project_id,
            world_id=body.world_id,
            scope=body.scope or "auto",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return mission


@personal_router.get("/missions")
def personal_list_missions(request: Request, world_id: str = "") -> dict[str, Any]:
    office = _office_from_app(request)
    return {"missions": office.store.list_missions(world_id=world_id or None)}


@personal_router.get("/missions/{mission_id}")
def personal_get_mission(mission_id: str, request: Request) -> dict[str, Any]:
    office = _office_from_app(request)
    try:
        return office.mission_detail(mission_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Mission not found") from exc


@personal_router.post("/checkin")
def personal_checkin(request: Request, world_id: str = "") -> dict[str, Any]:
    """Ask the executive assistant for today's priorities against open goals."""
    office = _office_from_app(request)
    goals = office.list_goals(world_id or None)
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
    return office.run_mission(prompt, world_id=world_id or None)


@personal_router.get("/goals")
def personal_list_goals(request: Request, world_id: str = "") -> dict[str, Any]:
    office = _office_from_app(request)
    return {
        "goals": office.list_goals(world_id or None),
        "checkins": office.store.list_checkins(),
    }


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
        world_id=body.world_id,
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
def personal_deliverables(
    request: Request, specialist_id: str = "", world_id: str = ""
) -> dict[str, Any]:
    office = _office_from_app(request)
    return {
        "deliverables": office.store.list_deliverables(
            specialist_id=specialist_id, world_id=world_id or None
        )
    }


@personal_router.get("/notes")
def personal_notes(request: Request, world_id: str = "") -> dict[str, Any]:
    office = _office_from_app(request)
    return {"notes": office.store.list_notes(world_id=world_id or None)}


@personal_router.post("/notes")
def personal_capture_note(body: NoteRequest, request: Request) -> dict[str, Any]:
    office = _office_from_app(request)
    title = body.title.strip() or body.body.strip().split("\n", 1)[0][:80]
    return office.capture_note(title, body.body, tags=body.tags, world_id=body.world_id)


@personal_router.post("/notes/ask")
def personal_ask(body: AskRequest, request: Request) -> dict[str, Any]:
    return _office_from_app(request).ask_memory(
        body.question, world_id=body.world_id or None
    )


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
def personal_projects(request: Request, world_id: str = "") -> dict[str, Any]:
    return {"projects": _office_from_app(request).project_board(world_id or None)}


@personal_router.post("/projects")
def personal_create_project(body: ProjectRequest, request: Request) -> dict[str, Any]:
    office = _office_from_app(request)
    return office.store.create_project(
        body.name,
        summary=body.summary,
        accent=body.accent,
        world_id=body.world_id or office._personal_id(),
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


@personal_router.get("/briefing")
def personal_briefing(request: Request, world_id: str = "") -> dict[str, Any]:
    """Inbox and upcoming meetings. Empty when Google is not connected."""
    return _office_from_app(request).briefing(world_id or None)


@personal_router.get("/proposals")
def personal_proposals(request: Request) -> dict[str, Any]:
    office = _office_from_app(request)
    return {"proposals": office.store.list_proposals()}


@personal_router.post("/proposals/{proposal_id}/approve")
def personal_approve_proposal(proposal_id: str, request: Request) -> dict[str, Any]:
    """Jonathan's approval. This is the only route that may send or schedule."""
    office = _office_from_app(request)
    try:
        return office.approve_proposal(proposal_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Proposal not found") from exc


@personal_router.post("/proposals/{proposal_id}/reject")
def personal_reject_proposal(proposal_id: str, request: Request) -> dict[str, Any]:
    office = _office_from_app(request)
    try:
        return office.reject_proposal(proposal_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Proposal not found") from exc


@personal_router.post("/drive/pull")
def personal_drive_pull(body: DrivePullRequest, request: Request) -> dict[str, Any]:
    return _office_from_app(request).pull_drive(
        body.query, world_id=body.world_id or None
    )


@personal_router.get("/phone")
def personal_phone(request: Request) -> dict[str, Any]:
    return _office_from_app(request).phone_status()


class KnowledgeRequest(BaseModel):
    text: str = ""
    url: str = ""
    title: str = ""
    world_id: str = ""
    specialist_id: str = ""


class KnowledgeRouteRequest(BaseModel):
    world_id: str = Field(..., min_length=1)
    specialist_id: str = Field(..., min_length=1)


def _knowledge_error(exc: Exception) -> None:
    if isinstance(exc, KeyError):
        raise HTTPException(
            status_code=404, detail="That lesson was not found"
        ) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise exc


@personal_router.get("/knowledge")
def personal_list_knowledge(request: Request, world_id: str = "") -> dict[str, Any]:
    office = _office_from_app(request)
    return {"items": office.list_knowledge(world_id)}


@personal_router.get("/knowledge/learned")
def personal_learned(request: Request, world_id: str = "") -> dict[str, Any]:
    return _office_from_app(request).learned(world_id)


@personal_router.get("/knowledge/playbooks")
def personal_playbooks(request: Request, status: str = "") -> dict[str, Any]:
    return {"playbooks": _office_from_app(request).playbooks(status)}


@personal_router.post("/knowledge")
def personal_teach(body: KnowledgeRequest, request: Request) -> dict[str, Any]:
    office = _office_from_app(request)
    try:
        return office.teach(
            text=body.text,
            url=body.url,
            title=body.title,
            world_id=body.world_id,
            specialist_id=body.specialist_id,
        )
    except (KeyError, ValueError) as exc:
        _knowledge_error(exc)
        raise


@personal_router.post("/knowledge/file")
def personal_teach_file(
    request: Request,
    file: UploadFile = File(...),
    text: str = Form(""),
    url: str = Form(""),
    title: str = Form(""),
    world_id: str = Form(""),
    specialist_id: str = Form(""),
) -> dict[str, Any]:
    office = _office_from_app(request)
    try:
        return office.teach(
            text=text,
            url=url,
            title=title,
            filename=file.filename or "upload",
            data=file.file.read(),
            world_id=world_id,
            specialist_id=specialist_id,
        )
    except (KeyError, ValueError) as exc:
        _knowledge_error(exc)
        raise


@personal_router.post("/knowledge/{item_id}/route")
def personal_reroute_knowledge(
    item_id: str, body: KnowledgeRouteRequest, request: Request
) -> dict[str, Any]:
    office = _office_from_app(request)
    try:
        return office.reroute_knowledge(
            item_id, world_id=body.world_id, specialist_id=body.specialist_id
        )
    except (KeyError, ValueError) as exc:
        _knowledge_error(exc)
        raise


@personal_router.delete("/knowledge/{item_id}")
def personal_remove_knowledge(item_id: str, request: Request) -> dict[str, Any]:
    office = _office_from_app(request)
    try:
        return office.remove_knowledge(item_id)
    except KeyError as exc:
        _knowledge_error(exc)
        raise


@personal_router.post("/knowledge/playbooks/{proposal_id}/approve")
def personal_approve_playbook(proposal_id: str, request: Request) -> dict[str, Any]:
    office = _office_from_app(request)
    try:
        return office.decide_playbook(proposal_id, approve=True)
    except (KeyError, ValueError) as exc:
        _knowledge_error(exc)
        raise


@personal_router.post("/knowledge/playbooks/{proposal_id}/reject")
def personal_reject_playbook(proposal_id: str, request: Request) -> dict[str, Any]:
    office = _office_from_app(request)
    try:
        return office.decide_playbook(proposal_id, approve=False)
    except KeyError as exc:
        _knowledge_error(exc)
        raise


class RevenueRequest(BaseModel):
    world_id: str = Field(..., min_length=1)
    amount: float
    note: str = ""
    source: str = "manual"


class RoiSettingsRequest(BaseModel):
    hourly_rate: Optional[float] = None
    minutes_per_task: Optional[float] = None
    strong_model: Optional[str] = None
    cheap_model: Optional[str] = None
    budgets: Optional[dict[str, Any]] = None
    prices: Optional[dict[str, Any]] = None
    recurring: Optional[list[dict[str, Any]]] = None


@personal_router.get("/roi")
def personal_roi(request: Request) -> dict[str, Any]:
    return _office_from_app(request).roi.report()


@personal_router.post("/roi/revenue")
def personal_roi_revenue(body: RevenueRequest, request: Request) -> dict[str, Any]:
    office = _office_from_app(request)
    try:
        office.roi.add_revenue(
            world_id=body.world_id,
            amount=body.amount,
            note=body.note,
            source=body.source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return office.roi.report()


@personal_router.put("/roi/settings")
def personal_roi_settings(body: RoiSettingsRequest, request: Request) -> dict[str, Any]:
    office = _office_from_app(request)
    payload = body.model_dump(exclude_none=True)
    try:
        office.roi.save_settings(payload)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return office.roi.report()
