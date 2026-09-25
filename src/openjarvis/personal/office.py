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
from openjarvis.personal.hermes import (
    resolve_configured_model,
    resolve_executive_model,
)
from openjarvis.personal.higgsfield import HiggsfieldClient, resolve_credentials
from openjarvis.personal.memory_bridge import MemoryBridge
from openjarvis.personal.omniroute import OmniRouteClient, resolve_omniroute
from openjarvis.personal.planner import plan_from_model_text, plan_request
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
    ) -> None:
        self.store = PersonalStore(db_path)
        self.store.ensure_example_projects()
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
        self._turn: dict[str, Any] = {"eli5": False, "command": None}
        self._calls = threading.local()
        self._run_lock = threading.Lock()
        self._thread_lock = threading.Lock()
        self._threads: dict[str, threading.Thread] = {}

    def close(self) -> None:
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

    def _agent_choices(self, executive: Any, configured: Any) -> dict[str, Any]:
        """One model choice per agent, OmniRoute first when it is reachable."""
        status = self.omniroute.public_status()
        choices: dict[str, Any] = {}
        for spec in list_specialists():
            engine_choice = executive if spec.prefers_hermes else configured
            if status.get("reachable"):
                choices[spec.id] = self.omniroute.choice_for(
                    spec.id,
                    hermes_model=self.hermes_model,
                    prefers_hermes=spec.prefers_hermes,
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

                self._calls.used = ModelChoice(
                    actual or choice.model_id,
                    "omniroute",
                    choice.detail,
                    route="omniroute",
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
        return text.strip() or None

    # -- goals ---------------------------------------------------------------

    def _decorate_goal(self, goal: dict[str, Any]) -> dict[str, Any]:
        status = assess_goal(goal)
        goal["on_track"] = status
        goal["pace"] = pace_label(status)
        return goal

    def list_goals(self) -> list[dict[str, Any]]:
        return [self._decorate_goal(goal) for goal in self.store.list_goals()]

    def create_goal(
        self,
        title: str,
        *,
        target: str = "Completed",
        deadline: str | None = None,
        progress: float = 0,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        goal = self.store.create_goal(
            title.strip(),
            target=target.strip() or "Completed",
            deadline=deadline or None,
            progress=progress,
            milestones=default_milestones(title.strip()),
            project_id=project_id,
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

    def capture_note(self, title: str, body: str, *, tags: str = "") -> dict[str, Any]:
        memory_id = self.memory.store(
            f"{title}\n\n{body}",
            {"tags": tags, "title": title},
        )
        return self.store.add_note(
            title.strip() or "Note",
            body.strip(),
            tags=tags,
            memory_id=memory_id,
        )

    def ask_memory(self, question: str) -> dict[str, Any]:
        notes = self.store.search_notes(question)
        hits = [note["body"] for note in notes]
        for hit in self.memory.search(question):
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
        self, request: str, *, project_id: str | None = None
    ) -> dict[str, Any]:
        text = (request or "").strip()
        if not text:
            raise ValueError("Tell the chief of staff what you need.")
        command = find_command(text, self._loaded_commands())
        project = self.store.get_project(project_id) if project_id else None
        if project is None:
            project = self._project_named_in(text)
        mission = self.store.create_mission(
            text,
            project_id=project["id"] if project else "",
            command=command.name if command else "",
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

    def run_mission(self, request: str) -> dict[str, Any]:
        """Run a mission and wait. Used by tests and the check-in endpoint."""
        mission = self.submit_mission(request)
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
                self.store.set_agent_state("chief_of_staff", "idle", "")

    def _run_locked(self, mission: dict[str, Any]) -> None:
        mission_id = mission["id"]
        request = mission["request"]
        self.store.set_agent_state(
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
        agents = self._agent_choices(executive, configured)
        planner_choice = agents.get("chief_of_staff", configured)
        choices = {
            "executive_assistant": agents["executive_assistant"],
            "configured": planner_choice,
            "agents": agents,
        }
        command = find_command(request, self._loaded_commands())
        self._turn = {"eli5": self.eli5_enabled(), "command": command}
        planned = None
        planner_source = "offline"
        if command is not None:
            planned = plan_request(request, command=command)
            planner_source = "superclaude"
        elif planner_choice.source != "offline":
            worker_ids = ", ".join(
                spec.id for spec in list_specialists(include_chief=False)
            )
            raw_plan = self._generate(
                planner_choice,
                "chief_of_staff",
                _PLAN_INSTRUCTION.format(ids=worker_ids) + f"\n\nRequest:\n{request}",
            )
            planned = plan_from_model_text(raw_plan or "", request=request)
            if planned:
                planner_source = planner_choice.source
        if not planned:
            planned = plan_request(request)
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
        self.store.set_agent_state(
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
                self.store.set_agent_state(spec_id, "idle", "Could not finish")
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
            self.store.set_agent_state(
                "chief_of_staff",
                "done",
                f"Collected {len(deliverables)} {noun}",
            )
        else:
            self.store.set_agent_state(
                "chief_of_staff",
                "idle",
                "Delegation did not finish",
            )
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
        self.store.set_agent_state(spec.id, "working", task["title"])
        a2a = A2ATask(
            input_text=task["brief"],
            metadata={"specialist": spec.id, "mission_id": task["mission_id"]},
        )
        a2a.state = TaskState.WORKING
        self.store.update_task(task["id"], status="working", a2a=a2a.to_dict())
        hits = self._recall(request)
        memory_block = ""
        if hits:
            memory_block = "\n\nRelated memory:\n" + "\n".join(hits)
        model_text = self._generate(choice, spec.id, task["brief"] + memory_block)
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
                goals=self.store.list_goals(),
                eli5=bool(self._turn.get("eli5")),
                persona_note=getattr(command, "instructions", "") or "",
            ),
        )
        project_id = task.get("project_id") or ""
        if produced.goal:
            self.create_goal(
                produced.goal["title"],
                target=produced.goal.get("target") or "Completed",
                deadline=produced.goal.get("deadline"),
                project_id=project_id or None,
            )
        if produced.note:
            self.capture_note(
                produced.note["title"],
                produced.note["body"],
                tags=produced.note.get("tags") or "",
            )
        body = produced.body
        assets: list[dict[str, Any]] = []
        if produced.visual_prompt:
            assets = self.higgsfield.illustrate(
                produced.visual_prompt,
                video=produced.want_video,
            )
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
        self.store.set_agent_state(spec.id, "done", produced.title)
        del node, deliverable
        return body

    def _recall(self, query: str) -> list[str]:
        hits = [note["body"] for note in self.store.search_notes(query, limit=3)]
        for hit in self.memory.search(query, top_k=3):
            if hit not in hits:
                hits.append(hit)
        return hits[:5]

    # -- views ---------------------------------------------------------------

    def roster(self) -> list[dict[str, Any]]:
        states = self.store.agent_states()
        choices = self.model_choices()
        agents = []
        for spec in list_specialists():
            state = states.get(spec.id, {})
            row = spec.to_dict()
            row["status"] = state.get("status") or "idle"
            row["current_work"] = state.get("current_work") or ""
            routed = choices.get("agents") or {}
            if spec.id in routed:
                row["model"] = routed[spec.id]
            elif spec.prefers_hermes:
                row["model"] = choices["executive_assistant"]
            else:
                row["model"] = choices["configured"]
            agents.append(row)
        return agents

    def world(self) -> dict[str, Any]:
        mission = self.store.latest_mission()
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
        projects = self.project_board()
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
        return {
            "agents": self.roster(),
            "edges": edges,
            "works": works,
            "projects": projects,
            "mission": mission,
            "hermes": self.model_choices()["executive_assistant"],
            "eli5": self.eli5_enabled(),
            "higgsfield": self.higgsfield.public_status(),
            "omniroute": self.omniroute.public_status(),
            "commands": [
                item.to_dict() for item in list_commands(self._loaded_commands())
            ],
        }

    def agent_view(self, specialist_id: str) -> dict[str, Any]:
        spec = get_specialist(specialist_id)
        row = next(item for item in self.roster() if item["id"] == spec.id)
        row["tasks"] = self.store.recent_tasks(spec.id)
        row["deliverables"] = self.store.list_deliverables(specialist_id=spec.id)
        row["skills_detail"] = [
            {"name": manifest.name, "description": manifest.description}
            for manifest in spec.skill_manifests()
        ]
        return row

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
            if name and name in lowered and (
                found is None or len(name) > len(found["name"])
            ):
                found = project
        return found

    def project_board(self) -> list[dict[str, Any]]:
        """Projects with the goals and tasks living on them."""
        goals = self.list_goals()
        board = []
        for project in self.store.list_projects():
            row = dict(project)
            row["goals"] = [
                goal for goal in goals if goal.get("project_id") == project["id"]
            ]
            row["tasks"] = self.store.tasks_for_project(project["id"])
            board.append(row)
        loose_goals = [goal for goal in goals if not goal.get("project_id")]
        mission = self.store.latest_mission()
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
