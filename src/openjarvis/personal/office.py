"""Chief of staff — plan, delegate through the workflow engine, collect."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from openjarvis.a2a.protocol import A2ATask, AgentCard, TaskState
from openjarvis.core.types import Message, Role
from openjarvis.personal.goals import (
    assess_goal,
    default_milestones,
    pace_label,
)
from openjarvis.personal.google_desk import GoogleDesk, ScopedGoogle, drafts_for
from openjarvis.personal.hermes import (
    resolve_configured_model,
    resolve_executive_model,
)
from openjarvis.personal.higgsfield import HiggsfieldClient, resolve_credentials
from openjarvis.personal.knowledge import KnowledgeFeed
from openjarvis.personal.memory_bridge import MemoryBridge
from openjarvis.personal.omniroute import OmniRouteClient, resolve_omniroute
from openjarvis.personal.phone import PhoneGate, describe_phone
from openjarvis.personal.planner import plan_from_model_text, plan_request
from openjarvis.personal.roi import RoiLedger, estimate_tokens
from openjarvis.personal.specialists import (
    ProduceContext,
    get_specialist,
    list_specialists,
    produce_for,
    render_system_prompt,
)
from openjarvis.personal.store import PersonalStore
from openjarvis.personal.superclaude import (
    find_command,
    list_commands,
    load_command_dir,
    prompt_addons,
)
from openjarvis.workflow.engine import WorkflowEngine
from openjarvis.workflow.graph import WorkflowGraph
from openjarvis.workflow.types import (
    NodeType,
    WorkflowEdge,
    WorkflowNode,
    WorkflowStepResult,
)

logger = logging.getLogger(__name__)

OVERALL = "*"
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _visual_section(assets: list[dict[str, Any]]) -> str:
    lines = ["", "## Pictures and clips"]
    for asset in assets:
        url = asset.get("url") or ""
        if url and asset.get("kind") == "image":
            lines.append(f"![picture]({url})")
        elif url:
            lines.append(f"- Video: {url}")
        else:
            note = asset.get("detail") or asset.get("status") or "No picture yet."
            lines.append(f"- {note}")
    return "\n".join(lines)


_PLAN_INSTRUCTION = (
    "Split the request into tasks. Reply with JSON only, no markdown:\n"
    '{{"tasks":[{{"specialist_id":"...","title":"...","brief":"..."}}]}}\n'
    "Use only these specialist_id values: {ids}."
)


class DelegationEngine(WorkflowEngine):
    """Workflow engine that runs personal specialists instead of JarvisSystem.

    Staging, parallel execution, and workflow events stay in
    :class:`WorkflowEngine`. Each agent node is one delegated specialist.
    """

    def __init__(self, runner: Any, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._runner = runner

    def _run_agent_node(
        self,
        node: WorkflowNode,
        outputs: dict[str, str],
        system: Any,
        graph: WorkflowGraph,
    ) -> WorkflowStepResult:
        del outputs, system, graph
        try:
            output = self._runner(node)
        except Exception as exc:
            logger.exception("Specialist %s failed", node.agent)
            return WorkflowStepResult(
                node_id=node.id,
                success=False,
                output=f"Specialist error: {exc}",
            )
        return WorkflowStepResult(node_id=node.id, success=True, output=output)


class PersonalOffice:
    """The chief of staff's desk: goals, missions, memory, and the team."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        engine: Any = None,
        memory: Any = None,
        scheduler: Any = None,
        bus: Any = None,
        hermes_model: str = "hermes3",
        fallback_model: str = "",
        default_model: str = "",
        schedule_checkins: bool = True,
        higgsfield_key: str = "",
        higgsfield_image_model: str = "",
        higgsfield_video_model: str = "",
        superclaude_dir: str = "",
        higgsfield: HiggsfieldClient | None = None,
        omniroute_enabled: bool = False,
        omniroute_base_url: str = "",
        omniroute_api_key: str = "",
        omniroute_model: str = "auto",
        omniroute_models: dict[str, str] | None = None,
        omniroute: OmniRouteClient | None = None,
        google: GoogleDesk | None = None,
        google_credentials_path: str = "",
        discover_google: bool = False,
        phone: PhoneGate | None = None,
    ) -> None:
        self.store = PersonalStore(db_path)
        self.store.ensure_example_projects()
        self.store.ensure_worlds()
        self._world_google: dict[str, GoogleDesk | ScopedGoogle] = {}
        self.engine = engine
        self.memory = MemoryBridge(memory)
        self.scheduler = scheduler
        self.bus = bus
        self.hermes_model = hermes_model or "hermes3"
        self.fallback_model = fallback_model or ""
        self.default_model = default_model or ""
        self.schedule_checkins = schedule_checkins
        self.superclaude_dir = superclaude_dir or ""
        self.higgsfield = higgsfield or HiggsfieldClient(
            resolve_credentials(higgsfield_key),
            image_model=higgsfield_image_model,
            video_model=higgsfield_video_model,
        )
        if omniroute is not None:
            self.omniroute = omniroute
        else:
            base, key, model = resolve_omniroute(
                enabled=omniroute_enabled,
                base_url=omniroute_base_url,
                api_key=omniroute_api_key,
                model=omniroute_model,
            )
            self.omniroute = OmniRouteClient(
                base,
                key,
                default_model=model,
                agent_models=omniroute_models,
            )
        if google is not None:
            self.google = google
        else:
            path = google_credentials_path or ""
            if discover_google and not path:
                from openjarvis.personal.google_desk import resolve_google_desk_path

                path = resolve_google_desk_path(str(db_path), google_credentials_path)
            self.google = GoogleDesk(path)
        self.phone = phone if phone is not None else PhoneGate()
        self.source_reader = None
        self.feed = KnowledgeFeed(self)
        self.roi = RoiLedger(self)
        self.roi.ensure_defaults()
        self._telegram_token = ""
        self._slack_token = ""
        self._slack_app_token = ""
        self._phone_started = False
        self._phone_listening = {"telegram": False, "slack": False}
        self._phone_notes: dict[str, str] = {"telegram": "", "slack": ""}
        self._phone_channels: dict[str, Any] = {}
        self._turn: dict[str, Any] = {"eli5": False, "command": None}
        self._calls = threading.local()
        self._run_lock = threading.Lock()
        self._thread_lock = threading.Lock()
        self._threads: dict[str, threading.Thread] = {}

    def _presence(
        self,
        specialist_id: str,
        status: str,
        current_work: str,
        world_id: str | None = None,
    ) -> None:
        scope = (
            world_id
            if world_id is not None
            else (self._turn.get("world_id") or OVERALL)
        )
        self.store.set_agent_state(specialist_id, status, current_work)
        self.store.set_scoped_state(str(scope), specialist_id, status, current_work)

    def close(self) -> None:
        for channel in self._phone_channels.values():
            disconnect = getattr(channel, "disconnect", None)
            if disconnect is not None:
                try:
                    disconnect()
                except Exception:
                    logger.debug("Phone channel disconnect failed", exc_info=True)
        self.store.close()

    # -- model selection -----------------------------------------------------

    def _probe_engine(self) -> tuple[list[str], bool]:
        engine = self.engine
        if engine is None:
            return [], False
        try:
            healthy = engine.health() if hasattr(engine, "health") else True
        except Exception:
            logger.debug("Engine health check failed", exc_info=True)
            return [], False
        if not healthy:
            return [], False
        if not hasattr(engine, "list_models"):
            return [], True
        try:
            listed = engine.list_models() or []
        except Exception:
            logger.debug("Engine model list failed", exc_info=True)
            return [], True
        return [str(name) for name in listed if name], True

    def _fallback_id(self) -> str:
        return self.fallback_model or self.default_model

    def model_choices(self) -> dict[str, Any]:
        available, engine_ok = self._probe_engine()
        fallback = self._fallback_id()
        executive = resolve_executive_model(
            self.hermes_model, fallback, available, engine_ok
        )
        configured = resolve_configured_model(fallback, available, engine_ok)
        agents = self._agent_choices(executive, configured)
        return {
            "executive_assistant": agents["executive_assistant"].to_dict(),
            "configured": agents.get("marketing_content", configured).to_dict(),
            "agents": {key: choice.to_dict() for key, choice in agents.items()},
            "hermes_model": self.hermes_model,
            "available": available,
            "omniroute": self.omniroute.public_status(),
        }

    def _choice_for(self, specialist_id: str, choices: dict[str, Any] | None = None):
        from openjarvis.personal.hermes import ModelChoice

        snapshot = choices or self.model_choices()
        agents = snapshot.get("agents") or {}
        if specialist_id in agents:
            raw = agents[specialist_id]
        else:
            key = (
                "executive_assistant"
                if specialist_id == "executive_assistant"
                else "configured"
            )
            raw = snapshot[key]
        if isinstance(raw, ModelChoice):
            return raw
        return ModelChoice(
            raw["model_id"],
            raw["source"],
            raw["detail"],
            route=raw.get("route") or "engine",
        )

    def _agent_choices(
        self,
        executive: Any,
        configured: Any,
        world_id: str = "",
    ) -> dict[str, Any]:
        """One model choice per agent, OmniRoute first when it is reachable."""
        settings = self.roi.settings()
        self.omniroute.strong_model = settings["strong_model"]
        self.omniroute.cheap_model = settings["cheap_model"]
        status = self.omniroute.public_status()
        team = {
            row["specialist_id"]: row
            for row in self.store.team(world_id)
            if world_id and world_id != OVERALL
        }
        choices: dict[str, Any] = {}
        for spec in list_specialists():
            engine_choice = executive if spec.prefers_hermes else configured
            override = (team.get(spec.id) or {}).get("omniroute_model") or ""
            if status.get("reachable"):
                choices[spec.id] = self.omniroute.choice_for(
                    spec.id,
                    hermes_model=self.hermes_model,
                    prefers_hermes=spec.prefers_hermes,
                    model=override,
                )
            else:
                choices[spec.id] = engine_choice
        return choices

    def _engine_choice(self, specialist_id: str) -> Any:
        available, engine_ok = self._probe_engine()
        fallback = self._fallback_id()
        if specialist_id == "executive_assistant":
            return resolve_executive_model(
                self.hermes_model, fallback, available, engine_ok
            )
        return resolve_configured_model(fallback, available, engine_ok)

    def _generate(self, choice: Any, specialist_id: str, user_text: str) -> str | None:
        self._calls.used = choice
        spec = get_specialist(specialist_id)
        extra = prompt_addons(
            self._turn.get("command"),
            eli5=bool(self._turn.get("eli5")),
        )
        world_note = self._team_brief(specialist_id)
        if world_note:
            extra = f"{extra}\n\nThis world:\n{world_note}".strip()
        world_id = str(self._turn.get("world_id") or "")
        choice = self._fit_budget(choice, specialist_id, world_id, user_text)
        self._calls.used = choice
        messages = [
            Message(role=Role.SYSTEM, content=render_system_prompt(spec, extra=extra)),
            Message(role=Role.USER, content=user_text),
        ]
        if getattr(choice, "route", "") == "omniroute":
            payload = [
                {"role": message.role.value, "content": message.content or ""}
                for message in messages
            ]
            answered = self.omniroute.complete(choice.model_id, payload)
            if answered is not None:
                text, actual = answered
                from openjarvis.personal.hermes import ModelChoice

                used = ModelChoice(
                    actual or choice.model_id,
                    "omniroute",
                    choice.detail,
                    route="omniroute",
                )
                self._calls.used = used
                usage = self.omniroute.take_usage()
                self._record_llm(
                    world_id,
                    specialist_id,
                    used.model_id,
                    user_text,
                    text,
                    usage,
                )
                return text
            choice = self._engine_choice(specialist_id)
            self._calls.used = choice
        if choice.source == "offline" or not choice.model_id or self.engine is None:
            return None
        try:
            result = self.engine.generate(
                messages,
                model=choice.model_id,
                temperature=0.4,
                max_tokens=900,
            )
        except Exception:
            logger.debug("Model call failed for %s", specialist_id, exc_info=True)
            return None
        if isinstance(result, dict):
            text = result.get("content") or ""
        else:
            text = str(result or "")
        cleaned = text.strip()
        if cleaned:
            self._record_llm(
                world_id,
                specialist_id,
                choice.model_id,
                user_text,
                cleaned,
                {},
            )
        return cleaned or None

    def _fit_budget(self, choice: Any, specialist_id: str, world_id: str, prompt: str):
        from openjarvis.personal.hermes import ModelChoice

        action, _estimate = self.roi.decide(world_id, specialist_id, prompt)
        if action == "ok":
            return choice
        if action == "downgrade" and self.omniroute.public_status().get("reachable"):
            cheap = self.roi.settings()["cheap_model"]
            return self.omniroute.choice_for(
                "second_brain",
                prefers_hermes=False,
                model=cheap,
            )
        return ModelChoice(
            "",
            "offline",
            "The monthly budget is too close to call a paid model.",
            route="offline",
        )

    def _record_llm(
        self,
        world_id: str,
        specialist_id: str,
        model: str,
        prompt: str,
        text: str,
        usage: dict[str, Any],
    ) -> None:
        if not world_id or world_id == OVERALL:
            world_id = ""
        reported = usage.get("reported_cost")
        self.roi.record_llm(
            world_id=world_id,
            specialist_id=specialist_id,
            model=model,
            input_tokens=int(usage.get("input_tokens") or estimate_tokens(prompt)),
            output_tokens=int(usage.get("output_tokens") or estimate_tokens(text)),
            reported=reported if reported is not None else None,
        )

    # -- goals ---------------------------------------------------------------

    def _decorate_goal(self, goal: dict[str, Any]) -> dict[str, Any]:
        status = assess_goal(goal)
        goal["on_track"] = status
        goal["pace"] = pace_label(status)
        return goal

    def list_goals(self, world_id: str | None = None) -> list[dict[str, Any]]:
        names = {world["id"]: world["name"] for world in self.store.list_worlds()}
        goals = []
        for goal in self.store.list_goals(world_id):
            row = self._decorate_goal(goal)
            row["world_name"] = names.get(goal.get("world_id") or "", "")
            goals.append(row)
        return goals

    def create_goal(
        self,
        title: str,
        *,
        target: str = "Completed",
        deadline: str | None = None,
        progress: float = 0,
        project_id: str | None = None,
        world_id: str | None = None,
    ) -> dict[str, Any]:
        scope = world_id or ""
        if not scope and project_id:
            project = self.store.get_project(project_id)
            scope = (project or {}).get("world_id") or ""
        if not scope:
            personal = self.store.personal_world()
            scope = personal["id"] if personal else ""
        goal = self.store.create_goal(
            title.strip(),
            target=target.strip() or "Completed",
            deadline=deadline or None,
            progress=progress,
            milestones=default_milestones(title.strip()),
            project_id=project_id,
            world_id=scope,
        )
        self._schedule_checkin(goal)
        return self._decorate_goal(goal)

    def update_goal(self, goal_id: str, **fields: Any) -> dict[str, Any] | None:
        goal = self.store.update_goal(goal_id, **fields)
        if goal is None:
            return None
        return self._decorate_goal(goal)

    def set_milestone_done(
        self, milestone_id: str, done: bool
    ) -> dict[str, Any] | None:
        goal = self.store.set_milestone_done(milestone_id, done)
        if goal is None:
            return None
        return self._decorate_goal(goal)

    def _schedule_checkin(self, goal: dict[str, Any]) -> None:
        existing = self.store.list_checkins()
        if any(item.get("goal_id") == goal["id"] for item in existing):
            return
        prompt = (
            "Daily check-in for Jonathan's goal: "
            f"{goal['title']}. Review progress and set today's priorities."
        )
        scheduler_task_id = ""
        if self.scheduler is not None and self.schedule_checkins:
            scheduler_task_id = self._ensure_scheduler_task(goal["id"], prompt)
        self.store.add_checkin(
            prompt,
            goal_id=goal["id"],
            scheduler_task_id=scheduler_task_id,
        )

    def _ensure_scheduler_task(self, goal_id: str, prompt: str) -> str:
        try:
            current = self.scheduler.list_tasks()
        except Exception:
            logger.debug("Scheduler list failed", exc_info=True)
            current = []
        for task in current:
            meta = getattr(task, "metadata", None) or {}
            same_goal = meta.get("goal_id") == goal_id
            if meta.get("personal") == "goal_checkin" and same_goal:
                return str(task.id)
        created = self.scheduler.create_task(
            prompt,
            "interval",
            "86400",
            agent="executive_assistant",
            metadata={"personal": "goal_checkin", "goal_id": goal_id},
        )
        return str(created.id)

    # -- second brain --------------------------------------------------------

    def capture_note(
        self,
        title: str,
        body: str,
        *,
        tags: str = "",
        world_id: str = "",
        specialist_id: str = "",
    ) -> dict[str, Any]:
        scope = world_id or self._personal_id()
        tag_list = tags
        if specialist_id and f"agent:{specialist_id}" not in tag_list:
            tag_list = f"{tag_list},agent:{specialist_id}".strip(",")
        meta: dict[str, Any] = {"tags": tag_list, "title": title, "world_id": scope}
        if specialist_id:
            meta["specialist_id"] = specialist_id
        memory_id = self.memory.store(f"{title}\n\n{body}", meta)
        note = self.store.add_note(
            title.strip() or "Note",
            body.strip(),
            tags=tag_list,
            memory_id=memory_id,
            world_id=scope,
        )
        note["memory_id"] = memory_id
        return note

    def teach(self, **kwargs: Any) -> dict[str, Any]:
        return self.feed.teach(**kwargs)

    def teach_from_phone(self, text: str) -> dict[str, Any] | None:
        return self.feed.teach_from_phone(text)

    def teaching_reply(self, item: dict[str, Any]) -> str:
        return self.feed.teaching_reply(item)

    def list_knowledge(self, world_id: str = "") -> list[dict[str, Any]]:
        return self.feed.list_items(world_id)

    def learned(self, world_id: str = "") -> dict[str, Any]:
        return self.feed.learned(world_id)

    def reroute_knowledge(
        self, item_id: str, *, world_id: str, specialist_id: str
    ) -> dict[str, Any]:
        return self.feed.reroute(
            item_id, world_id=world_id, specialist_id=specialist_id
        )

    def remove_knowledge(self, item_id: str) -> dict[str, Any]:
        return self.feed.remove(item_id)

    def playbooks(self, status: str = "") -> list[dict[str, Any]]:
        return self.feed.playbooks(status)

    def decide_playbook(self, proposal_id: str, *, approve: bool) -> dict[str, Any]:
        return self.feed.decide_playbook(proposal_id, approve=approve)

    def _personal_id(self) -> str:
        personal = self.store.personal_world()
        return personal["id"] if personal else ""

    def _target_world(self, text: str, scope: str) -> str:
        named = self.store.match_world(text)
        if named:
            return named["id"]
        project = self._project_named_in(text)
        if project and project.get("world_id"):
            return str(project["world_id"])
        if scope in ("route", "all"):
            return OVERALL
        return self._personal_id()

    def set_world_google(self, world_id: str, desk: GoogleDesk | ScopedGoogle) -> None:
        """Tests and setup can pin a world's mail without a credentials file."""
        self._world_google[world_id] = desk

    def _google_for(self, world_id: str) -> GoogleDesk | ScopedGoogle:
        if world_id in self._world_google:
            return self._world_google[world_id]
        accounts = []
        if world_id and world_id != OVERALL:
            accounts = self.store.list_google_accounts(world_id)
        desks: list[tuple[str, GoogleDesk]] = []
        for account in accounts:
            path = account.get("credentials_path") or ""
            if path:
                label = account.get("email") or account["id"]
                desks.append((label, GoogleDesk(path)))
        if desks:
            return ScopedGoogle(desks)
        personal_id = self._personal_id()
        if not world_id or world_id == personal_id:
            return self.google
        return GoogleDesk("")

    def _credentials_outside_repo(self, path: str) -> None:
        if not (path or "").strip():
            return
        resolved = Path(path).expanduser().resolve()
        if resolved == _REPO_ROOT or _REPO_ROOT in resolved.parents:
            raise ValueError("Keep Google credentials outside this repository.")

    def _public_account(self, account: dict[str, Any]) -> dict[str, Any]:
        path = account.get("credentials_path") or ""
        connected = GoogleDesk(path).connected() if path else False
        return {
            "id": account["id"],
            "world_id": account.get("world_id") or "",
            "email": account.get("email") or "",
            "label": account.get("label") or "",
            "connected": connected,
        }

    def list_worlds(self) -> list[dict[str, Any]]:
        cards = []
        for world in self.store.list_worlds():
            cards.append(self._world_card(world))
        return cards

    def _world_card(self, world: dict[str, Any]) -> dict[str, Any]:
        world_id = world["id"]
        team = self.store.team(world_id)
        return {
            "id": world_id,
            "name": world["name"],
            "kind": world["kind"],
            "summary": world.get("summary") or "",
            "accent": world.get("accent") or "#7dcea0",
            "mark": world.get("mark") or "",
            "aliases": world.get("aliases") or "",
            "project_count": len(self.store.list_projects(world_id)),
            "goal_count": len(self.store.list_goals(world_id)),
            "agent_count": sum(1 for row in team if row.get("enabled")),
            "knowledge_count": self.store.knowledge_count(world_id),
            "accounts": [
                self._public_account(account)
                for account in self.store.list_google_accounts(world_id)
            ],
            "roi": self.roi.line(world_id),
        }

    def create_world(
        self,
        name: str,
        *,
        summary: str = "",
        accent: str = "#7dcea0",
        kind: str = "business",
    ) -> dict[str, Any]:
        note = f"This world is {name.strip()}."
        if summary.strip():
            note = f"{note} {summary.strip()}"
        briefs = {spec_id: note for spec_id, _picture in self.store._TEAM_SEED}
        world = self.store.create_world(
            name,
            kind=kind,
            summary=summary,
            accent=accent,
            briefs=briefs,
        )
        return self._world_card(world)

    def rename_world(self, world_id: str, **fields: Any) -> dict[str, Any] | None:
        world = self.store.update_world(world_id, **fields)
        if world is None:
            return None
        return self._world_card(world)

    def delete_world(self, world_id: str) -> str:
        return self.store.delete_world(world_id)

    def world_team(self, world_id: str) -> list[dict[str, Any]]:
        return self.store.team(world_id)

    def update_world_team(
        self, world_id: str, specialist_id: str, **fields: Any
    ) -> dict[str, Any] | None:
        return self.store.update_team(world_id, specialist_id, **fields)

    def connect_google_account(
        self,
        world_id: str,
        *,
        email: str,
        credentials_path: str = "",
        label: str = "",
    ) -> dict[str, Any]:
        if self.store.get_world(world_id) is None:
            raise KeyError(world_id)
        self._credentials_outside_repo(credentials_path)
        account = self.store.add_google_account(
            world_id,
            email=email,
            credentials_path=credentials_path,
            label=label,
        )
        self._world_google.pop(world_id, None)
        return self._public_account(account)

    def disconnect_google_account(self, account_id: str) -> bool:
        account = self.store.get_google_account(account_id)
        if account is None:
            return False
        removed = self.store.delete_google_account(account_id)
        self._world_google.pop(account.get("world_id") or "", None)
        return removed

    def _enabled_roster(self, world_id: str) -> list[Any]:
        team = {row["specialist_id"]: row for row in self.store.team(world_id)}
        roster = []
        for spec in list_specialists(include_chief=False):
            row = team.get(spec.id)
            if row is None or row.get("enabled", True):
                roster.append(spec)
        return roster

    def _team_brief(self, specialist_id: str) -> str:
        world_id = str(self._turn.get("world_id") or "")
        if not world_id or world_id == OVERALL:
            return ""
        for row in self.store.team(world_id):
            if row["specialist_id"] == specialist_id:
                return str(row.get("brief") or "")
        return ""

    def _higgsfield_within_budget(self, world_id: str, video: bool) -> bool:
        settings = self.roi.settings()
        prices = settings["prices"]
        amount = float(
            prices.get("higgsfield_video" if video else "higgsfield_image") or 0
        )
        if video:
            amount += float(prices.get("higgsfield_image") or 0)
        spent_world, spent_overall = self.roi._spent(world_id)
        world_cap = float(settings["budgets"]["worlds"].get(world_id) or 0)
        overall_cap = float(settings["budgets"]["overall"] or 0)
        if world_cap and spent_world + amount > world_cap:
            self.roi._alert(world_id, "block")
            return False
        if overall_cap and spent_overall + amount > overall_cap:
            self.roi._alert("", "block")
            return False
        return True

    def _higgsfield_on(self, world_id: str, specialist_id: str) -> bool:
        for row in self.store.team(world_id):
            if row["specialist_id"] == specialist_id:
                return bool(row["higgsfield"])
        return specialist_id == "marketing_content"

    def ask_memory(self, question: str, world_id: str | None = None) -> dict[str, Any]:
        scope = world_id or self._personal_id()
        notes = self.store.search_notes(question, world_id=scope or None)
        hits = [note["body"] for note in notes]
        for hit in self.memory.search(question, world_id=scope or None):
            if hit not in hits:
                hits.append(hit)
        spec_id = "second_brain"
        choice = self._choice_for(spec_id)
        context = "\n\n".join(hits[:6]) or "No notes are stored yet."
        answer = self._generate(
            choice,
            spec_id,
            f"Question:\n{question.strip()}\n\nMemory:\n{context}",
        )
        source = choice.source if answer else "offline"
        if not answer:
            if hits:
                preview = "\n\n".join(f"- {hit[:400]}" for hit in hits[:4])
                answer = f"From the second brain:\n\n{preview}"
            else:
                answer = "Nothing in the second brain matches that yet."
        return {
            "answer": answer,
            "hits": hits[:6],
            "model": {**choice.to_dict(), "source": source},
        }

    # -- missions ------------------------------------------------------------

    def submit_mission(
        self,
        request: str,
        *,
        project_id: str | None = None,
        world_id: str | None = None,
        scope: str = "auto",
    ) -> dict[str, Any]:
        text = (request or "").strip()
        if not text:
            raise ValueError("Tell the chief of staff what you need.")
        command = find_command(text, self._loaded_commands())
        project = self.store.get_project(project_id) if project_id else None
        if project is None:
            project = self._project_named_in(text)
        target = world_id or self._target_world(text, scope)
        if project and project.get("world_id") and not world_id:
            target = project["world_id"]
        mission = self.store.create_mission(
            text,
            project_id=project["id"] if project else "",
            command=command.name if command else "",
            world_id=target,
        )
        thread = threading.Thread(
            target=self._execute,
            args=(mission["id"],),
            name=f"chief-{mission['id']}",
            daemon=True,
        )
        with self._thread_lock:
            self._threads[mission["id"]] = thread
        thread.start()
        stored = self.store.get_mission(mission["id"])
        assert stored is not None
        return stored

    def run_mission(
        self,
        request: str,
        world_id: str | None = None,
        scope: str = "auto",
    ) -> dict[str, Any]:
        """Run a mission and wait. Used by tests and the check-in endpoint."""
        mission = self.submit_mission(request, world_id=world_id, scope=scope)
        thread = self._threads[mission["id"]]
        thread.join()
        return self.mission_detail(mission["id"])

    def mission_detail(self, mission_id: str) -> dict[str, Any]:
        mission = self.store.get_mission(mission_id)
        if mission is None:
            raise KeyError(mission_id)
        mission["tasks"] = self.store.tasks_for(mission_id)
        mission["deliverables"] = [
            item
            for item in self.store.list_deliverables(limit=100)
            if item["mission_id"] == mission_id
        ]
        return mission

    def _execute(self, mission_id: str) -> None:
        with self._run_lock:
            mission = self.store.get_mission(mission_id)
            if mission is None:
                return
            try:
                self._run_locked(mission)
            except Exception as exc:
                logger.exception("Mission %s failed", mission_id)
                self.store.update_mission(
                    mission_id,
                    status="failed",
                    summary=f"The chief of staff stopped: {exc}",
                )
                self._presence("chief_of_staff", "idle", "")

    def _run_overall(self, mission: dict[str, Any]) -> None:
        """Top-level chief: one briefing per world, no specialist mix."""
        mission_id = mission["id"]
        request = mission["request"]
        self._presence(
            "chief_of_staff",
            "working",
            "Reading across worlds",
            world_id=OVERALL,
        )
        self.store.update_mission(mission_id, status="running")
        lines = ["## Across worlds", ""]
        if self.store.match_world(request) is None:
            lines.append(
                "Name a world when the work belongs to one business. "
                "Here is the combined picture."
            )
            lines.append("")
        for world in self.store.list_worlds():
            desk = self._google_for(world["id"])
            try:
                snap = desk.snapshot("")
            except Exception:
                logger.debug("World briefing failed", exc_info=True)
                snap = {"connected": False}
            text = desk.briefing_text(snap) if snap.get("connected") else ""
            lines.append(f"### {world['name']}")
            lines.append(text or "No mail connected for this world.")
            goals = self.store.list_goals(world["id"])
            if goals:
                lines.append("")
                lines.append("Goals:")
                for goal in goals[:6]:
                    lines.append(f"- {goal['title']}")
            lines.append("")
        body = "\n".join(lines).strip()
        self.store.add_deliverable(
            mission_id=mission_id,
            task_id="",
            specialist_id="chief_of_staff",
            title="Across worlds",
            kind="briefing",
            body=body,
            world_id=OVERALL,
        )
        self._presence(
            "chief_of_staff",
            "done",
            "Combined the worlds",
            world_id=OVERALL,
        )
        self.store.update_mission(
            mission_id,
            status="completed",
            summary=body,
            plan=[],
            workflow={},
        )

    def _run_locked(self, mission: dict[str, Any]) -> None:
        mission_id = mission["id"]
        request = mission["request"]
        world_id = mission.get("world_id") or self._personal_id()
        self._turn = {
            "eli5": self.eli5_enabled(),
            "command": None,
            "world_id": world_id,
            "google": {},
        }
        if world_id == OVERALL:
            self._run_overall(mission)
            return
        self._presence(
            "chief_of_staff",
            "working",
            "Breaking the request into tasks",
        )
        self.store.update_mission(mission_id, status="running")
        available, engine_ok = self._probe_engine()
        fallback = self._fallback_id()
        executive = resolve_executive_model(
            self.hermes_model, fallback, available, engine_ok
        )
        configured = resolve_configured_model(fallback, available, engine_ok)
        agents = self._agent_choices(executive, configured, world_id=world_id)
        planner_choice = agents.get("chief_of_staff", configured)
        choices = {
            "executive_assistant": agents["executive_assistant"],
            "configured": planner_choice,
            "agents": agents,
        }
        command = find_command(request, self._loaded_commands())
        desk = self._google_for(world_id)
        roster = self._enabled_roster(world_id)
        self._turn = {
            "eli5": self.eli5_enabled(),
            "command": command,
            "google": self._google_snapshot(request, desk),
            "world_id": world_id,
            "desk": desk,
        }
        planned = None
        planner_source = "offline"
        if command is not None:
            planned = plan_request(request, roster, command=command)
            planner_source = "superclaude"
        elif planner_choice.source != "offline":
            worker_ids = ", ".join(spec.id for spec in roster)
            raw_plan = self._generate(
                planner_choice,
                "chief_of_staff",
                _PLAN_INSTRUCTION.format(ids=worker_ids) + f"\n\nRequest:\n{request}",
            )
            planned = plan_from_model_text(
                raw_plan or "", request=request, specialists=roster
            )
            if planned:
                planner_source = planner_choice.source
        if not planned:
            planned = plan_request(request, roster)
            planner_source = "offline"
        plan_rows = [item.to_dict() for item in planned]
        self.store.update_mission(
            mission_id,
            plan=plan_rows,
            model={
                "planner": configured.to_dict(),
                "planner_source": planner_source if planned else "offline",
                "executive_assistant": executive.to_dict(),
                "command": command.name if command else "",
                "eli5": bool(self._turn.get("eli5")),
            },
        )
        project_id = mission.get("project_id") or ""
        tasks = []
        for index, item in enumerate(planned):
            row = self.store.add_task(
                mission_id,
                item.specialist_id,
                item.title,
                item.brief,
                index,
            )
            row["project_id"] = project_id
            tasks.append(row)
        self._presence(
            "chief_of_staff",
            "working",
            f"Delegating {len(tasks)} task{'s' if len(tasks) != 1 else ''}",
        )
        graph = self._delegation_graph(mission_id, tasks)
        by_id = {task["id"]: task for task in tasks}

        def runner(node: WorkflowNode) -> str:
            try:
                return self._run_specialist(node, by_id[node.id], request, choices)
            except Exception:
                self.store.update_task(node.id, status="failed")
                spec_id = by_id[node.id]["specialist_id"]
                self._presence(spec_id, "idle", "Could not finish")
                raise

        engine = DelegationEngine(runner, bus=self.bus, max_parallel=4)
        result = engine.run(graph, initial_input=request)
        workflow = {
            "name": graph.name,
            "success": result.success,
            "nodes": [
                {
                    "id": node.id,
                    "type": node.node_type.value,
                    "agent": node.agent,
                }
                for node in graph.nodes
            ],
            "edges": [
                {"source": edge.source, "target": edge.target} for edge in graph.edges
            ],
        }
        deliverables = [
            item
            for item in self.store.list_deliverables(limit=100)
            if item["mission_id"] == mission_id
        ]
        task_rows = self.store.tasks_for(mission_id)
        done_count = sum(1 for task in task_rows if task["status"] == "done")
        names = {spec.id: spec.name for spec in list_specialists()}
        lines = ["## Back from the team", ""]
        for item in deliverables:
            who = names.get(item["specialist_id"], item["specialist_id"])
            lines.append(f"- **{who}** — {item['title']}")
        if not deliverables:
            lines.append("- No deliverables were produced.")
        if done_count and done_count < len(task_rows):
            lines.append("")
            lines.append("Some tasks did not finish. The rest is ready to read.")
        summary = "\n".join(lines)
        status = "completed" if done_count else "failed"
        if done_count:
            noun = "deliverable" if len(deliverables) == 1 else "deliverables"
            self._presence(
                "chief_of_staff",
                "done",
                f"Collected {len(deliverables)} {noun}",
            )
        else:
            self._presence(
                "chief_of_staff",
                "idle",
                "Delegation did not finish",
            )
        self._file_proposals(request, mission_id, world_id)
        self.store.update_mission(
            mission_id,
            status=status,
            summary=summary,
            workflow=workflow,
        )

    def _delegation_graph(
        self, mission_id: str, tasks: list[dict[str, Any]]
    ) -> WorkflowGraph:
        graph = WorkflowGraph(name=f"chief-of-staff-{mission_id}")
        for task in tasks:
            graph.add_node(
                WorkflowNode(
                    id=task["id"],
                    node_type=NodeType.AGENT,
                    agent=task["specialist_id"],
                )
            )
        graph.add_node(
            WorkflowNode(
                id="collect",
                node_type=NodeType.TRANSFORM,
                transform_expr="concatenate",
            )
        )
        for task in tasks:
            graph.add_edge(WorkflowEdge(source=task["id"], target="collect"))
        return graph

    def _run_specialist(
        self,
        node: WorkflowNode,
        task: dict[str, Any],
        request: str,
        choices: dict[str, Any],
    ) -> str:
        spec = get_specialist(task["specialist_id"])
        choice = self._choice_for(spec.id, choices)
        self._presence(spec.id, "working", task["title"])
        a2a = A2ATask(
            input_text=task["brief"],
            metadata={"specialist": spec.id, "mission_id": task["mission_id"]},
        )
        a2a.state = TaskState.WORKING
        self.store.update_task(task["id"], status="working", a2a=a2a.to_dict())
        world_id = str(self._turn.get("world_id") or self._personal_id())
        hits = self._recall(request, world_id, spec.id)
        snap = self._turn.get("google") or {}
        desk = self._turn.get("desk") or self._google_for(world_id)
        briefing = ""
        if spec.id == "executive_assistant":
            briefing = desk.briefing_text(snap)
        if spec.id == "second_brain":
            saved = self._save_drive_docs(snap.get("files") or [], world_id)
            for note in saved:
                hits.insert(0, note["body"])
        memory_block = ""
        if hits:
            memory_block = "\n\nRelated memory:\n" + "\n".join(hits)
        prompt = task["brief"] + memory_block
        if briefing:
            prompt = f"{prompt}\n\n{briefing}"
        model_text = self._generate(choice, spec.id, prompt)
        used = getattr(self._calls, "used", None) or choice
        source = used.source if model_text else "offline"
        model_id = used.model_id if model_text else ""
        command = self._turn.get("command")
        produced = produce_for(
            spec,
            ProduceContext(
                request=request,
                brief=task["brief"],
                model_text=model_text,
                memory_hits=hits,
                goals=self.store.list_goals(world_id),
                eli5=bool(self._turn.get("eli5")),
                persona_note=getattr(command, "instructions", "") or "",
                google_briefing=briefing,
                world_note=self._team_brief(spec.id),
            ),
        )
        project_id = task.get("project_id") or ""
        if produced.goal:
            self.create_goal(
                produced.goal["title"],
                target=produced.goal.get("target") or "Completed",
                deadline=produced.goal.get("deadline"),
                project_id=project_id or None,
                world_id=world_id,
            )
        if produced.note:
            self.capture_note(
                produced.note["title"],
                produced.note["body"],
                tags=produced.note.get("tags") or "",
                world_id=world_id,
            )
        body = produced.body
        if briefing and model_text:
            body = f"{body.rstrip()}\n\n{briefing}"
        assets: list[dict[str, Any]] = []
        if produced.visual_prompt and self._higgsfield_on(world_id, spec.id):
            if self._higgsfield_within_budget(world_id, produced.want_video):
                assets = self.higgsfield.illustrate(
                    produced.visual_prompt,
                    video=produced.want_video,
                )
                for asset in assets:
                    if asset.get("status") == "completed":
                        self.roi.record_higgsfield(
                            world_id=world_id,
                            specialist_id=spec.id,
                            kind=str(asset.get("kind") or "image"),
                        )
            else:
                assets = [
                    {
                        "kind": "image",
                        "status": "skipped",
                        "url": "",
                        "detail": "Skipped. This world is at its monthly budget.",
                        "prompt": produced.visual_prompt,
                    }
                ]
            body = f"{body.rstrip()}\n{_visual_section(assets)}"
        deliverable = self.store.add_deliverable(
            mission_id=task["mission_id"],
            task_id=task["id"],
            specialist_id=spec.id,
            title=produced.title,
            kind=produced.kind,
            body=body,
            model_id=model_id,
            model_source=source,
            world_id=world_id,
        )
        for asset in assets:
            self.store.add_media(deliverable["id"], asset)
        a2a.state = TaskState.COMPLETED
        a2a.output_text = body
        self.store.update_task(
            task["id"],
            status="done",
            output=body,
            a2a=a2a.to_dict(),
        )
        self._presence(spec.id, "done", produced.title)
        del node, deliverable
        return body

    def _recall(
        self,
        query: str,
        world_id: str | None = None,
        specialist_id: str | None = None,
    ) -> list[str]:
        scope = world_id or self._personal_id() or None
        hits = []
        for note in self.store.search_notes(query, limit=5, world_id=scope):
            if not self._note_visible(note, specialist_id):
                continue
            hits.append(note["body"])
        for hit in self.memory.search(
            query, top_k=5, world_id=scope, specialist_id=specialist_id
        ):
            if hit not in hits:
                hits.append(hit)
        return hits[:5]

    @staticmethod
    def _note_visible(note: dict[str, Any], specialist_id: str | None) -> bool:
        tags = note.get("tags") or ""
        if "agent:" not in tags:
            return True
        if not specialist_id:
            return True
        return f"agent:{specialist_id}" in tags

    # -- views ---------------------------------------------------------------

    def roster(self, world_id: str | None = None) -> list[dict[str, Any]]:
        if world_id:
            states = self.store.scoped_states(world_id)
            available, engine_ok = self._probe_engine()
            fallback = self._fallback_id()
            executive = resolve_executive_model(
                self.hermes_model, fallback, available, engine_ok
            )
            configured = resolve_configured_model(fallback, available, engine_ok)
            routed = self._agent_choices(executive, configured, world_id=world_id)
            choices = {
                "executive_assistant": routed["executive_assistant"].to_dict(),
                "configured": routed.get("marketing_content", configured).to_dict(),
                "agents": {key: choice.to_dict() for key, choice in routed.items()},
            }
            team = {row["specialist_id"]: row for row in self.store.team(world_id)}
            learned = self.store.learned_counts(world_id)
        else:
            states = self.store.agent_states()
            choices = self.model_choices()
            team = {}
            learned = {}
        agents = []
        for spec in list_specialists():
            state = states.get(spec.id, {})
            row = spec.to_dict()
            row["status"] = state.get("status") or "idle"
            row["current_work"] = state.get("current_work") or ""
            member = team.get(spec.id) or {}
            row["enabled"] = bool(member.get("enabled", True))
            row["higgsfield_enabled"] = bool(
                member.get("higgsfield", spec.id == "marketing_content")
            )
            row["omniroute_model"] = member.get("omniroute_model") or ""
            row["brief"] = member.get("brief") or ""
            row["learned_count"] = learned.get(spec.id, 0)
            routed_models = choices.get("agents") or {}
            if spec.id in routed_models:
                row["model"] = routed_models[spec.id]
            elif spec.prefers_hermes:
                row["model"] = choices["executive_assistant"]
            else:
                row["model"] = choices["configured"]
            agents.append(row)
        return agents

    def world(self, world_id: str | None = None, *, scope: str = "") -> dict[str, Any]:
        if scope == "all":
            return self._archipelago()
        return self._habitat(world_id)

    def _archipelago(self) -> dict[str, Any]:
        chief = self.store.scoped_states(OVERALL).get("chief_of_staff", {})
        return {
            "scope": "all",
            "worlds": self.list_worlds(),
            "projects": [],
            "agents": [],
            "edges": [],
            "works": [],
            "mission": self.store.latest_mission(OVERALL),
            "chief": {
                "id": "chief_of_staff",
                "name": "Chief of Staff",
                "status": chief.get("status") or "idle",
                "current_work": chief.get("current_work") or "",
            },
            "hermes": self.model_choices()["executive_assistant"],
            "eli5": self.eli5_enabled(),
            "higgsfield": self.higgsfield.public_status(),
            "omniroute": self.omniroute.public_status(),
            "google": self.google.public_status(),
            "phone": self.phone_status(),
            "commands": [
                item.to_dict() for item in list_commands(self._loaded_commands())
            ],
        }

    def _habitat(self, world_id: str | None = None) -> dict[str, Any]:
        mission = self.store.latest_mission(world_id)
        edges: list[dict[str, Any]] = []
        if mission is not None:
            for task in self.store.tasks_for(mission["id"]):
                edges.append(
                    {
                        "from": "chief_of_staff",
                        "to": task["specialist_id"],
                        "status": task["status"],
                        "title": task["title"],
                        "task_id": task["id"],
                    }
                )
        projects = self.project_board(world_id)
        works: list[dict[str, Any]] = []
        for project in projects:
            for task in project.get("tasks") or []:
                works.append(
                    {
                        "from": task["specialist_id"],
                        "to": project["id"],
                        "status": task["status"],
                        "title": task["title"],
                    }
                )
        meta = self.store.get_world(world_id) if world_id else None
        desk = self._google_for(world_id) if world_id else self.google
        return {
            "scope": "world" if world_id else "habitat",
            "world": (
                {
                    "id": meta["id"],
                    "name": meta["name"],
                    "kind": meta["kind"],
                    "summary": meta.get("summary") or "",
                    "accent": meta.get("accent") or "",
                }
                if meta
                else None
            ),
            "team": self.store.team(world_id) if world_id else [],
            "accounts": (
                [
                    self._public_account(account)
                    for account in self.store.list_google_accounts(world_id)
                ]
                if world_id
                else []
            ),
            "agents": self.roster(world_id),
            "edges": edges,
            "works": works,
            "projects": projects,
            "mission": mission,
            "hermes": self.model_choices()["executive_assistant"],
            "eli5": self.eli5_enabled(),
            "higgsfield": self.higgsfield.public_status(),
            "omniroute": self.omniroute.public_status(),
            "google": desk.public_status(),
            "phone": self.phone_status(),
            "commands": [
                item.to_dict() for item in list_commands(self._loaded_commands())
            ],
        }

    def agent_view(
        self, specialist_id: str, world_id: str | None = None
    ) -> dict[str, Any]:
        spec = get_specialist(specialist_id)
        row = next(item for item in self.roster(world_id) if item["id"] == spec.id)
        row["tasks"] = self.store.recent_tasks(spec.id)
        row["deliverables"] = self.store.list_deliverables(specialist_id=spec.id)
        row["skills_detail"] = [
            {"name": manifest.name, "description": manifest.description}
            for manifest in spec.skill_manifests()
        ]
        row["learned"] = self.feed.lessons_for(spec.id, world_id)
        return row

    def phone_status(self) -> dict[str, Any]:
        return describe_phone(
            self.phone,
            telegram_token_set=bool(self._telegram_token),
            slack_token_set=bool(self._slack_token),
            telegram_listening=bool(self._phone_listening.get("telegram")),
            slack_listening=bool(self._phone_listening.get("slack")),
            notes=self._phone_notes,
        )

    def briefing(self, world_id: str | None = None) -> dict[str, Any]:
        if not world_id:
            sections = []
            texts = []
            for world in self.store.list_worlds():
                desk = self._google_for(world["id"])
                snap = desk.snapshot("")
                text = desk.briefing_text(snap)
                sections.append(
                    {
                        "id": world["id"],
                        "name": world["name"],
                        "inbox": snap.get("inbox") or [],
                        "meetings": snap.get("meetings") or [],
                        "text": text,
                        "connected": bool(snap.get("connected")),
                    }
                )
                heading = f"## {world['name']}"
                texts.append(
                    f"{heading}\n{text}" if text else f"{heading}\nNo mail connected."
                )
            return {
                "scope": "all",
                "connected": any(section["connected"] for section in sections),
                "worlds": sections,
                "inbox": [],
                "meetings": [],
                "text": "\n\n".join(texts),
                "google": self.google.public_status(),
            }
        desk = self._google_for(world_id)
        snap = desk.snapshot("")
        return {
            "scope": "world",
            "connected": bool(snap.get("connected")),
            "worlds": [],
            "inbox": snap.get("inbox") or [],
            "meetings": snap.get("meetings") or [],
            "text": desk.briefing_text(snap),
            "google": desk.public_status(),
        }

    def pull_drive(self, query: str, world_id: str | None = None) -> dict[str, Any]:
        if not world_id:
            return {
                "connected": False,
                "files": [],
                "notes": [],
                "detail": "Open a world before pulling Drive docs.",
            }
        desk = self._google_for(world_id)
        snap = desk.snapshot(query)
        notes = self._save_drive_docs(snap.get("files") or [], world_id)
        files = [
            {"name": item.get("name") or "", "link": item.get("link") or ""}
            for item in (snap.get("files") or [])
        ]
        return {
            "connected": bool(snap.get("connected")),
            "files": files,
            "notes": notes,
            "detail": "" if snap.get("connected") else "Google Drive is not connected.",
        }

    def approve_proposal(self, proposal_id: str) -> dict[str, Any]:
        """The only path that may send mail or create a calendar event."""
        row = self.store.get_proposal(proposal_id)
        if row is None:
            raise KeyError(proposal_id)
        if row["status"] != "pending":
            return row
        from openjarvis.personal import google_actions

        payload = row.get("payload") or {}
        path = self.google.credentials_path
        account_id = str(payload.get("account_id") or "")
        if account_id:
            account = self.store.get_google_account(account_id)
            if account and account.get("credentials_path"):
                path = account["credentials_path"]
        try:
            detail = google_actions.fulfill(row["kind"], payload, path)
        except PermissionError as exc:
            detail = str(exc)
        except Exception as exc:
            logger.exception("Proposal %s was not sent", proposal_id)
            updated = self.store.update_proposal(
                proposal_id,
                status="pending",
                detail=f"Not sent: {exc}"[:300],
            )
            assert updated is not None
            return updated
        updated = self.store.update_proposal(
            proposal_id, status="approved", detail=detail
        )
        assert updated is not None
        return updated

    def reject_proposal(self, proposal_id: str) -> dict[str, Any]:
        row = self.store.get_proposal(proposal_id)
        if row is None:
            raise KeyError(proposal_id)
        if row["status"] != "pending":
            return row
        updated = self.store.update_proposal(
            proposal_id,
            status="rejected",
            detail="Rejected. Nothing was sent or added to the calendar.",
        )
        assert updated is not None
        return updated

    def _google_snapshot(
        self, request: str, desk: GoogleDesk | ScopedGoogle | None = None
    ) -> dict[str, Any]:
        reader = desk or self.google
        try:
            return reader.snapshot(request)
        except Exception:
            logger.debug("Google snapshot failed", exc_info=True)
            return {"connected": False, "inbox": [], "meetings": [], "files": []}

    def _file_proposals(self, request: str, mission_id: str, world_id: str) -> None:
        accounts = self.store.list_google_accounts(world_id) if world_id else []
        account_id = accounts[0]["id"] if accounts else ""
        for draft in drafts_for(request):
            payload = dict(draft["payload"])
            if account_id:
                payload["account_id"] = account_id
            self.store.add_proposal(
                kind=draft["kind"],
                title=draft["title"],
                payload=payload,
                mission_id=mission_id,
                world_id=world_id,
            )

    def _save_drive_docs(
        self, docs: list[dict[str, Any]], world_id: str = ""
    ) -> list[dict[str, Any]]:
        scope = world_id or self._personal_id()
        existing = {
            note["title"] for note in self.store.list_notes(limit=200, world_id=scope)
        }
        saved = []
        for doc in docs[:3]:
            name = (doc.get("name") or "Untitled").strip()
            title = f"Drive: {name}"
            body = (doc.get("text") or "").strip()
            if not body or title in existing:
                continue
            saved.append(
                self.capture_note(
                    title, body, tags="drive,second-brain", world_id=scope
                )
            )
            existing.add(title)
        return saved

    def eli5_enabled(self) -> bool:
        return self.store.get_setting("eli5", "0") == "1"

    def set_eli5(self, enabled: bool) -> bool:
        self.store.set_setting("eli5", "1" if enabled else "0")
        return self.eli5_enabled()

    def settings_view(self) -> dict[str, Any]:
        return {
            "eli5": self.eli5_enabled(),
            "higgsfield": self.higgsfield.public_status(),
            "omniroute": self.omniroute.public_status(),
            "google": self.google.public_status(),
            "phone": self.phone_status(),
            "commands": [
                item.to_dict() for item in list_commands(self._loaded_commands())
            ],
        }

    def _loaded_commands(self) -> list[Any]:
        return load_command_dir(self.superclaude_dir)

    def _project_named_in(self, text: str) -> dict[str, Any] | None:
        lowered = text.lower()
        found: dict[str, Any] | None = None
        for project in self.store.list_projects():
            name = project["name"].strip().lower()
            if (
                name
                and name in lowered
                and (found is None or len(name) > len(found["name"]))
            ):
                found = project
        return found

    def project_board(self, world_id: str | None = None) -> list[dict[str, Any]]:
        """Projects with the goals and tasks living on them."""
        goals = self.list_goals(world_id)
        board = []
        for project in self.store.list_projects(world_id):
            row = dict(project)
            row["goals"] = [
                goal for goal in goals if goal.get("project_id") == project["id"]
            ]
            row["tasks"] = self.store.tasks_for_project(project["id"])
            board.append(row)
        loose_goals = [goal for goal in goals if not goal.get("project_id")]
        mission = self.store.latest_mission(world_id)
        loose_tasks: list[dict[str, Any]] = []
        if mission is not None and not mission.get("project_id"):
            loose_tasks = self.store.tasks_for(mission["id"])
        if loose_goals or loose_tasks:
            board.append(
                {
                    "id": "",
                    "name": "Right now",
                    "summary": "Work that is not on a named project yet.",
                    "accent": "#9ec9f5",
                    "example": False,
                    "goals": loose_goals,
                    "tasks": loose_tasks,
                }
            )
        return board

    def agent_cards(self) -> list[dict[str, Any]]:
        """A2A agent cards for the team, so they can be discovered later."""
        cards = []
        for spec in list_specialists(include_chief=False):
            card = AgentCard(
                name=spec.name,
                description=spec.description,
                url=f"personal://agents/{spec.id}",
                capabilities=["delegation"],
                skills=list(spec.skills),
            )
            cards.append(card.to_dict())
        return cards
