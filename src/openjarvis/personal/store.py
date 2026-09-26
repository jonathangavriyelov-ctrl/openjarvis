"""SQLite state for the personal AI OS.

The database lives under the OpenJarvis home (default ``~/.openjarvis``),
same as the scheduler and session stores. Tests and the demo pass an explicit
path so nothing is read from a developer's real home directory.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _month_bounds(month: str) -> tuple[str, str]:
    """Inclusive start and exclusive end for a ``YYYY-MM`` stamp."""
    year_text, month_text = month.split("-", 1)
    year = int(year_text)
    mon = int(month_text)
    start = f"{year:04d}-{mon:02d}-01"
    if mon == 12:
        end = f"{year + 1:04d}-01-01"
    else:
        end = f"{year:04d}-{mon + 1:02d}-01"
    return start, end


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


_CATALOG_VERSION = "jonathan-2"
_CRM_SUMMARY = (
    "Merchant cash advance pipeline. "
    "github.com/jonathangavriyelov-ctrl/quick-funders-crm. "
    "Live at quick-funders-crm-kappa.vercel.app."
)
_AUDIT_PROJECT_SUMMARY = (
    "Personal finance audit. "
    "github.com/jonathangavriyelov-ctrl/self-audit. "
    "Live at self-audit-nine.vercel.app."
)
_PLACEHOLDER_SUMMARIES = {
    "",
    "Leads, deals, and the next follow-up.",
    "Money in, money out, and what to check.",
    "Jonathan's own mail, calendar, notes, and goals.",
    "The funding business: its pipeline, mail, and docs.",
}


def _briefs(world: str, lines: dict[str, str]) -> dict[str, str]:
    shared = f"You work only inside {world}. Do not use another world's mail or notes."
    return {key: f"{text} {shared}" for key, text in lines.items()}


_WORLD_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "name": "Quick Funders",
        "kind": "business",
        "mark": "advance",
        "aliases": "mca",
        "accent": "#1f8a70",
        "summary": (
            "Merchant cash advance business. Deals, funders, and the Quick Funders CRM."
        ),
        "higgsfield": {"marketing_content": 1},
        "briefs": _briefs(
            "Quick Funders",
            {
                "chief_of_staff": (
                    "You run Quick Funders, a merchant cash advance business. "
                    "Push lead follow-up and pipeline nudges. "
                    "Any outbound message stays a draft until Jonathan approves it."
                ),
                "executive_assistant": (
                    "Follow up Quick Funders leads and nudge stalled deals. "
                    "Track funder deadlines. "
                    "Any outbound message stays a draft until Jonathan approves it."
                ),
                "marketing_content": (
                    "You market Quick Funders, a merchant cash advance company. "
                    "Write for brokers and merchants about funding, "
                    "and draft follow-ups. "
                    "Any outbound message stays a draft until Jonathan approves it."
                ),
                "second_brain": (
                    "Remember Quick Funders deals, funders, and CRM notes."
                ),
            },
        ),
    },
    {
        "name": "JWJ / Gavco",
        "kind": "business",
        "mark": "gem",
        "aliases": "jwj, gavco",
        "accent": "#c6a15b",
        "summary": "Jewelry business. Pieces, clients, and the bench.",
        "higgsfield": {"marketing_content": 1},
        "briefs": _briefs(
            "JWJ / Gavco",
            {
                "chief_of_staff": (
                    "You run JWJ / Gavco, a jewelry business. "
                    "Ask for content and client re-engagement. "
                    "Any outbound message stays a draft until Jonathan approves it."
                ),
                "executive_assistant": (
                    "Re-engage jewelry clients and keep orders "
                    "and appointments moving. "
                    "Any outbound message stays a draft until Jonathan approves it."
                ),
                "marketing_content": (
                    "You market JWJ / Gavco, a jewelry business. "
                    "Draft jewelry content and customer re-engagement "
                    "about pieces, clients, and the bench. "
                    "Any outbound message stays a draft until Jonathan approves it."
                ),
                "second_brain": "Remember jewelry clients, pieces, and orders.",
            },
        ),
    },
    {
        "name": "Glatt Express",
        "kind": "business",
        "mark": "market",
        "aliases": "glatt",
        "accent": "#8c2f39",
        "summary": "Kosher meat and food distribution.",
        "higgsfield": {"marketing_content": 1},
        "briefs": _briefs(
            "Glatt Express",
            {
                "chief_of_staff": (
                    "You run Glatt Express, a kosher meat distribution business. "
                    "Ask for content and customer re-engagement. "
                    "Any outbound message stays a draft until Jonathan approves it."
                ),
                "executive_assistant": (
                    "Re-engage Glatt Express shops and track orders and deliveries. "
                    "Any outbound message stays a draft until Jonathan approves it."
                ),
                "marketing_content": (
                    "You market Glatt Express, a kosher meat and food distributor. "
                    "Draft content and customer re-engagement "
                    "about product, delivery, and kashrut. "
                    "Any outbound message stays a draft until Jonathan approves it."
                ),
                "second_brain": (
                    "Remember Glatt Express products, shops, and deliveries."
                ),
            },
        ),
    },
    {
        "name": "Personal",
        "kind": "personal",
        "mark": "home",
        "aliases": "",
        "accent": "#7eb6e0",
        "summary": "Jonathan's own life, calendar, and private notes.",
        "higgsfield": {"marketing_content": 1},
        "briefs": _briefs(
            "Personal",
            {
                "chief_of_staff": (
                    "You run Jonathan's personal life, not his businesses."
                ),
                "executive_assistant": (
                    "This is Jonathan's personal calendar and private goals."
                ),
                "marketing_content": (
                    "This is Jonathan's personal life, not a company. "
                    "Keep any words private."
                ),
                "second_brain": "Remember personal notes. Leave the businesses out.",
            },
        ),
    },
    {
        "name": "Self Financial Audit",
        "kind": "finance",
        "mark": "ledger",
        "aliases": "self audit, personal finance",
        "accent": "#c4a15a",
        "summary": ("Personal finance audit. The related project is Self Audit."),
        "higgsfield": {"marketing_content": 0},
        "briefs": _briefs(
            "Self Financial Audit",
            {
                "chief_of_staff": (
                    "You run Jonathan's personal finance audit, not a sales desk."
                ),
                "executive_assistant": (
                    "Track money in, money out, and what still needs a check."
                ),
                "marketing_content": (
                    "This is a personal finance audit, not a public brand. "
                    "Write plain internal notes."
                ),
                "second_brain": "Store personal-finance findings for the Self Audit.",
            },
        ),
    },
)

_OLD_PLAYBOOKS: dict[str, dict[str, str]] = {
    "Quick Funders": _briefs(
        "Quick Funders",
        {
            "chief_of_staff": (
                "You run Quick Funders, a merchant cash advance business."
            ),
            "executive_assistant": (
                "Track Quick Funders deals, funder follow-ups, and deadlines."
            ),
            "marketing_content": (
                "You market Quick Funders, a merchant cash advance company. "
                "Write for brokers and merchants about funding."
            ),
            "second_brain": "Remember Quick Funders deals, funders, and CRM notes.",
        },
    ),
    "JWJ / Gavco": _briefs(
        "JWJ / Gavco",
        {
            "chief_of_staff": "You run JWJ / Gavco, a jewelry business.",
            "executive_assistant": (
                "Keep the jewelry bench, client orders, and appointments on track."
            ),
            "marketing_content": (
                "You market JWJ / Gavco, a jewelry business. "
                "Write about pieces, clients, and the bench."
            ),
            "second_brain": "Remember jewelry clients, pieces, and orders.",
        },
    ),
    "Glatt Express": _briefs(
        "Glatt Express",
        {
            "chief_of_staff": (
                "You run Glatt Express, a kosher meat distribution business."
            ),
            "executive_assistant": (
                "Track Glatt Express orders, deliveries, and shop follow-ups."
            ),
            "marketing_content": (
                "You market Glatt Express, a kosher meat and food distributor. "
                "Write about product, delivery, and kashrut."
            ),
            "second_brain": "Remember Glatt Express products, shops, and deliveries.",
        },
    ),
}


_SCHEMA = """
CREATE TABLE IF NOT EXISTS goals (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    target TEXT NOT NULL DEFAULT '',
    deadline TEXT,
    progress REAL NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS milestones (
    id TEXT PRIMARY KEY,
    goal_id TEXT NOT NULL,
    title TEXT NOT NULL,
    target_progress REAL NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    position INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS missions (
    id TEXT PRIMARY KEY,
    request TEXT NOT NULL,
    status TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    plan_json TEXT NOT NULL DEFAULT '[]',
    workflow_json TEXT NOT NULL DEFAULT '{}',
    model_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL,
    specialist_id TEXT NOT NULL,
    title TEXT NOT NULL,
    brief TEXT NOT NULL,
    status TEXT NOT NULL,
    a2a_json TEXT NOT NULL DEFAULT '{}',
    output TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deliverables (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    specialist_id TEXT NOT NULL,
    title TEXT NOT NULL,
    kind TEXT NOT NULL,
    body TEXT NOT NULL,
    model_id TEXT NOT NULL DEFAULT '',
    model_source TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'second_brain',
    memory_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_state (
    specialist_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    current_work TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checkins (
    id TEXT PRIMARY KEY,
    goal_id TEXT,
    prompt TEXT NOT NULL,
    schedule_type TEXT NOT NULL,
    schedule_value TEXT NOT NULL,
    next_run TEXT,
    scheduler_task_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    accent TEXT NOT NULL DEFAULT '#7dcea0',
    example INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS media (
    id TEXT PRIMARY KEY,
    deliverable_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    prompt TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    url TEXT NOT NULL DEFAULT '',
    request_id TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    detail TEXT NOT NULL DEFAULT '',
    mission_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS worlds (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'business',
    summary TEXT NOT NULL DEFAULT '',
    accent TEXT NOT NULL DEFAULT '#7dcea0',
    mark TEXT NOT NULL DEFAULT '',
    aliases TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS world_team (
    world_id TEXT NOT NULL,
    specialist_id TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    omniroute_model TEXT NOT NULL DEFAULT '',
    higgsfield INTEGER NOT NULL DEFAULT 0,
    brief TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (world_id, specialist_id)
);
CREATE TABLE IF NOT EXISTS google_accounts (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    email TEXT NOT NULL DEFAULT '',
    label TEXT NOT NULL DEFAULT '',
    credentials_path TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS knowledge_items (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    kind TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL,
    summary TEXT NOT NULL,
    lessons_json TEXT NOT NULL DEFAULT '[]',
    sops_json TEXT NOT NULL DEFAULT '[]',
    ideas_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS knowledge_routes (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL,
    world_id TEXT NOT NULL,
    specialist_id TEXT NOT NULL,
    note_id TEXT NOT NULL DEFAULT '',
    memory_id TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS playbook_proposals (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    specialist_id TEXT NOT NULL,
    item_id TEXT NOT NULL DEFAULT '',
    proposed_brief TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS spend_entries (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL DEFAULT '',
    specialist_id TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    amount REAL NOT NULL DEFAULT 0,
    detail TEXT NOT NULL DEFAULT '',
    month TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS revenue_entries (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    amount REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    note TEXT NOT NULL DEFAULT '',
    month TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS budget_alerts (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL DEFAULT '',
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    month TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scoped_agent_state (
    world_id TEXT NOT NULL,
    specialist_id TEXT NOT NULL,
    status TEXT NOT NULL,
    current_work TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (world_id, specialist_id)
);
"""


class PersonalStore:
    """Thread-safe SQLite store for goals, missions, and deliverables."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        for statement in (
            "ALTER TABLE goals ADD COLUMN project_id TEXT",
            "ALTER TABLE missions ADD COLUMN project_id TEXT",
            "ALTER TABLE missions ADD COLUMN command TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE goals ADD COLUMN world_id TEXT",
            "ALTER TABLE projects ADD COLUMN world_id TEXT",
            "ALTER TABLE missions ADD COLUMN world_id TEXT",
            "ALTER TABLE notes ADD COLUMN world_id TEXT",
            "ALTER TABLE deliverables ADD COLUMN world_id TEXT",
            "ALTER TABLE proposals ADD COLUMN world_id TEXT",
            "ALTER TABLE worlds ADD COLUMN mark TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE worlds ADD COLUMN aliases TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE world_team ADD COLUMN brief TEXT NOT NULL DEFAULT ''",
        ):
            try:
                self._conn.execute(statement)
            except sqlite3.OperationalError:
                pass
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _one(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row else None

    # -- goals ---------------------------------------------------------------

    def create_goal(
        self,
        title: str,
        *,
        target: str = "",
        deadline: str | None = None,
        progress: float = 0,
        milestones: list[dict[str, Any]] | None = None,
        notes: str = "",
        project_id: str | None = None,
        world_id: str | None = None,
    ) -> dict[str, Any]:
        goal_id = _new_id()
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO goals (id, title, target, deadline, progress, notes, "
                "project_id, world_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    goal_id,
                    title,
                    target,
                    deadline,
                    progress,
                    notes,
                    project_id or None,
                    world_id or None,
                    now,
                    now,
                ),
            )
            for index, item in enumerate(milestones or []):
                self._conn.execute(
                    "INSERT INTO milestones (id, goal_id, title, target_progress, "
                    "done, position) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        _new_id(),
                        goal_id,
                        item.get("title") or f"Milestone {index + 1}",
                        float(item.get("target_progress") or 0),
                        1 if item.get("done") else 0,
                        index,
                    ),
                )
            self._sync_milestones(goal_id, progress)
            self._conn.commit()
        goal = self.get_goal(goal_id)
        assert goal is not None
        return goal

    def _sync_milestones(self, goal_id: str, progress: float) -> None:
        self._conn.execute(
            "UPDATE milestones SET done = CASE WHEN target_progress <= ? THEN 1 "
            "ELSE done END WHERE goal_id = ?",
            (progress, goal_id),
        )

    def list_goals(self, world_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if world_id:
                rows = self._conn.execute(
                    "SELECT * FROM goals WHERE world_id = ? ORDER BY created_at DESC",
                    (world_id,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM goals ORDER BY created_at DESC"
                ).fetchall()
            return [self._goal_with_milestones(dict(row)) for row in rows]

    def get_goal(self, goal_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM goals WHERE id = ?", (goal_id,)
            ).fetchone()
            if row is None:
                return None
            return self._goal_with_milestones(dict(row))

    def _goal_with_milestones(self, goal: dict[str, Any]) -> dict[str, Any]:
        rows = self._conn.execute(
            "SELECT * FROM milestones WHERE goal_id = ? ORDER BY position",
            (goal["id"],),
        ).fetchall()
        goal["milestones"] = [
            {
                "id": row["id"],
                "title": row["title"],
                "target_progress": row["target_progress"],
                "done": bool(row["done"]),
            }
            for row in rows
        ]
        return goal

    def update_goal(self, goal_id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = ("title", "target", "deadline", "progress", "notes")
        sets: list[str] = []
        values: list[Any] = []
        if "project_id" in fields:
            sets.append("project_id = ?")
            values.append(fields["project_id"] or None)
        for key in allowed:
            if key in fields and fields[key] is not None:
                sets.append(f"{key} = ?")
                values.append(fields[key])
        if not sets:
            return self.get_goal(goal_id)
        sets.append("updated_at = ?")
        values.append(_now())
        values.append(goal_id)
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE goals SET {', '.join(sets)} WHERE id = ?",
                values,
            )
            if cur.rowcount == 0:
                return None
            if "progress" in fields and fields["progress"] is not None:
                self._sync_milestones(goal_id, float(fields["progress"]))
            self._conn.commit()
        return self.get_goal(goal_id)

    def set_milestone_done(
        self, milestone_id: str, done: bool
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM milestones WHERE id = ?", (milestone_id,)
            ).fetchone()
            if row is None:
                return None
            self._conn.execute(
                "UPDATE milestones SET done = ? WHERE id = ?",
                (1 if done else 0, milestone_id),
            )
            if done:
                self._conn.execute(
                    "UPDATE goals SET progress = MAX(progress, ?), updated_at = ? "
                    "WHERE id = ?",
                    (row["target_progress"], _now(), row["goal_id"]),
                )
            self._conn.commit()
            goal_id = row["goal_id"]
        return self.get_goal(goal_id)

    # -- missions ------------------------------------------------------------

    def create_mission(
        self,
        request: str,
        *,
        project_id: str = "",
        command: str = "",
        world_id: str = "",
    ) -> dict[str, Any]:
        mission_id = _new_id()
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO missions (id, request, status, project_id, command, "
                "world_id, created_at, updated_at) "
                "VALUES (?, ?, 'planning', ?, ?, ?, ?, ?)",
                (
                    mission_id,
                    request,
                    project_id or None,
                    command,
                    world_id or None,
                    now,
                    now,
                ),
            )
            self._conn.commit()
        mission = self.get_mission(mission_id)
        assert mission is not None
        return mission

    def update_mission(self, mission_id: str, **fields: Any) -> None:
        mapping = {
            "status": "status",
            "summary": "summary",
            "plan": "plan_json",
            "workflow": "workflow_json",
            "model": "model_json",
        }
        sets: list[str] = []
        values: list[Any] = []
        for key, column in mapping.items():
            if key not in fields:
                continue
            value = fields[key]
            if key in {"plan", "workflow", "model"}:
                value = json.dumps(value)
            sets.append(f"{column} = ?")
            values.append(value)
        if not sets:
            return
        sets.append("updated_at = ?")
        values.append(_now())
        values.append(mission_id)
        with self._lock:
            self._conn.execute(
                f"UPDATE missions SET {', '.join(sets)} WHERE id = ?",
                values,
            )
            self._conn.commit()

    def _mission(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["plan"] = json.loads(data.pop("plan_json") or "[]")
        data["workflow"] = json.loads(data.pop("workflow_json") or "{}")
        data["model"] = json.loads(data.pop("model_json") or "{}")
        return data

    def get_mission(self, mission_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM missions WHERE id = ?", (mission_id,)
            ).fetchone()
        return self._mission(row) if row else None

    def list_missions(
        self, limit: int = 20, world_id: str | None = None
    ) -> list[dict[str, Any]]:
        with self._lock:
            if world_id:
                rows = self._conn.execute(
                    "SELECT * FROM missions WHERE world_id = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (world_id, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM missions ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._mission(row) for row in rows]

    def latest_mission(self, world_id: str | None = None) -> dict[str, Any] | None:
        missions = self.list_missions(limit=1, world_id=world_id)
        return missions[0] if missions else None

    # -- tasks and deliverables ----------------------------------------------

    def add_task(
        self,
        mission_id: str,
        specialist_id: str,
        title: str,
        brief: str,
        position: int,
    ) -> dict[str, Any]:
        task_id = _new_id()
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO tasks (id, mission_id, specialist_id, title, brief, "
                "status, position, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
                (task_id, mission_id, specialist_id, title, brief, position, now, now),
            )
            self._conn.commit()
        task = self.get_task(task_id)
        assert task is not None
        return task

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["a2a"] = json.loads(data.pop("a2a_json") or "{}")
        return data

    def update_task(self, task_id: str, **fields: Any) -> None:
        sets: list[str] = []
        values: list[Any] = []
        if "status" in fields:
            sets.append("status = ?")
            values.append(fields["status"])
        if "output" in fields:
            sets.append("output = ?")
            values.append(fields["output"])
        if "a2a" in fields:
            sets.append("a2a_json = ?")
            values.append(json.dumps(fields["a2a"]))
        if not sets:
            return
        sets.append("updated_at = ?")
        values.append(_now())
        values.append(task_id)
        with self._lock:
            self._conn.execute(
                f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?",
                values,
            )
            self._conn.commit()

    def tasks_for(self, mission_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE mission_id = ? ORDER BY position",
                (mission_id,),
            ).fetchall()
        tasks = []
        for row in rows:
            data = dict(row)
            data["a2a"] = json.loads(data.pop("a2a_json") or "{}")
            tasks.append(data)
        return tasks

    def recent_tasks(self, specialist_id: str, limit: int = 8) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE specialist_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (specialist_id, limit),
            ).fetchall()
        tasks = []
        for row in rows:
            data = dict(row)
            data["a2a"] = json.loads(data.pop("a2a_json") or "{}")
            tasks.append(data)
        return tasks

    def add_deliverable(
        self,
        *,
        mission_id: str,
        task_id: str,
        specialist_id: str,
        title: str,
        kind: str,
        body: str,
        model_id: str = "",
        model_source: str = "",
        world_id: str = "",
    ) -> dict[str, Any]:
        deliverable_id = _new_id()
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO deliverables (id, mission_id, task_id, specialist_id, "
                "title, kind, body, model_id, model_source, world_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    deliverable_id,
                    mission_id,
                    task_id,
                    specialist_id,
                    title,
                    kind,
                    body,
                    model_id,
                    model_source,
                    world_id or None,
                    now,
                ),
            )
            self._conn.commit()
        item = self.get_deliverable(deliverable_id)
        assert item is not None
        return item

    def get_deliverable(self, deliverable_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM deliverables WHERE id = ?", (deliverable_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_deliverables(
        self,
        *,
        specialist_id: str = "",
        world_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        if specialist_id:
            clauses.append("specialist_id = ?")
            values.append(specialist_id)
        if world_id:
            clauses.append("world_id = ?")
            values.append(world_id)
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        values.append(limit)
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM deliverables "
                + where
                + "ORDER BY created_at DESC LIMIT ?",
                values,
            ).fetchall()
            items = []
            for row in rows:
                data = dict(row)
                data["media"] = self._media_rows(data["id"])
                items.append(data)
            return items

    # -- notes ---------------------------------------------------------------

    def add_note(
        self,
        title: str,
        body: str,
        *,
        tags: str = "",
        source: str = "second_brain",
        memory_id: str = "",
        world_id: str = "",
    ) -> dict[str, Any]:
        note_id = _new_id()
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO notes (id, title, body, tags, source, memory_id, "
                "world_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (note_id, title, body, tags, source, memory_id, world_id or None, now),
            )
            self._conn.commit()
        return {
            "id": note_id,
            "title": title,
            "body": body,
            "tags": tags,
            "source": source,
            "memory_id": memory_id,
            "world_id": world_id or None,
            "created_at": now,
        }

    def list_notes(
        self, limit: int = 50, world_id: str | None = None
    ) -> list[dict[str, Any]]:
        with self._lock:
            if world_id:
                rows = self._conn.execute(
                    "SELECT * FROM notes WHERE world_id = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (world_id, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM notes ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def search_notes(
        self,
        query: str,
        limit: int = 5,
        world_id: str | None = None,
    ) -> list[dict[str, Any]]:
        words = []
        for raw in (query or "").split():
            word = raw.replace("%", "").replace("_", "")
            if len(word) > 2:
                words.append(word)
            if len(words) == 6:
                break
        if not words:
            return []
        clauses = []
        values: list[Any] = []
        for word in words:
            clauses.append("(title LIKE ? OR body LIKE ? OR tags LIKE ?)")
            like = f"%{word}%"
            values.extend([like, like, like])
        scope = ""
        if world_id:
            scope = " AND world_id = ?"
            values.append(world_id)
        values.append(limit)
        sql = (
            "SELECT * FROM notes WHERE ("
            + " OR ".join(clauses)
            + ")"
            + scope
            + " ORDER BY created_at DESC LIMIT ?"
        )
        with self._lock:
            rows = self._conn.execute(sql, values).fetchall()
        return [dict(row) for row in rows]

    # -- agent presence ------------------------------------------------------

    def set_agent_state(
        self, specialist_id: str, status: str, current_work: str
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO agent_state (specialist_id, status, current_work, "
                "updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(specialist_id) DO UPDATE SET status = excluded.status, "
                "current_work = excluded.current_work, "
                "updated_at = excluded.updated_at",
                (specialist_id, status, current_work, _now()),
            )
            self._conn.commit()

    def agent_states(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM agent_state").fetchall()
        return {row["specialist_id"]: dict(row) for row in rows}

    # -- check-ins -----------------------------------------------------------

    def add_checkin(
        self,
        prompt: str,
        *,
        goal_id: str = "",
        schedule_type: str = "interval",
        schedule_value: str = "86400",
        scheduler_task_id: str = "",
    ) -> dict[str, Any]:
        checkin_id = _new_id()
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO checkins (id, goal_id, prompt, schedule_type, "
                "schedule_value, scheduler_task_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    checkin_id,
                    goal_id or None,
                    prompt,
                    schedule_type,
                    schedule_value,
                    scheduler_task_id,
                    now,
                ),
            )
            self._conn.commit()
        return {
            "id": checkin_id,
            "goal_id": goal_id,
            "prompt": prompt,
            "schedule_type": schedule_type,
            "schedule_value": schedule_value,
            "scheduler_task_id": scheduler_task_id,
            "created_at": now,
        }

    def list_checkins(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM checkins ORDER BY created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    # -- projects, settings, media ------------------------------------------

    def ensure_example_projects(self) -> None:
        """Seed two example projects once. Deleting them does not bring them back."""
        if self.get_setting("examples_seeded") == "1":
            return
        self.set_setting("examples_seeded", "1")
        with self._lock:
            count = self._conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
            if count:
                return
        self.create_project(
            "Quick Funders CRM",
            summary=_CRM_SUMMARY,
            accent="#1f8a70",
            example=True,
        )
        self.create_project(
            "Self Audit",
            summary=_AUDIT_PROJECT_SUMMARY,
            accent="#c4a15a",
            example=True,
        )

    def create_project(
        self,
        name: str,
        *,
        summary: str = "",
        accent: str = "#7dcea0",
        example: bool = False,
        world_id: str = "",
    ) -> dict[str, Any]:
        project_id = _new_id()
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO projects (id, name, summary, accent, example, "
                "world_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    project_id,
                    name.strip(),
                    summary.strip(),
                    accent,
                    int(example),
                    world_id or None,
                    now,
                    now,
                ),
            )
            self._conn.commit()
        project = self.get_project(project_id)
        assert project is not None
        return project

    def list_projects(self, world_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if world_id:
                rows = self._conn.execute(
                    "SELECT * FROM projects WHERE world_id = ? ORDER BY created_at",
                    (world_id,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM projects ORDER BY created_at"
                ).fetchall()
        return [self._project(row) for row in rows]

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        return self._project(row) if row else None

    def update_project(self, project_id: str, **fields: Any) -> dict[str, Any] | None:
        sets: list[str] = []
        values: list[Any] = []
        for key in ("name", "summary", "accent"):
            if key in fields and fields[key] is not None:
                sets.append(f"{key} = ?")
                values.append(fields[key])
        if not sets:
            return self.get_project(project_id)
        sets.append("updated_at = ?")
        values.append(_now())
        values.append(project_id)
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE projects SET {', '.join(sets)} WHERE id = ?",
                values,
            )
            self._conn.commit()
            if cur.rowcount == 0:
                return None
        return self.get_project(project_id)

    def delete_project(self, project_id: str) -> bool:
        with self._lock:
            self._conn.execute(
                "UPDATE goals SET project_id = NULL WHERE project_id = ?",
                (project_id,),
            )
            self._conn.execute(
                "UPDATE missions SET project_id = NULL WHERE project_id = ?",
                (project_id,),
            )
            cur = self._conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            self._conn.commit()
        return cur.rowcount > 0

    @staticmethod
    def _project(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["example"] = bool(data.get("example"))
        return data

    def get_setting(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else default

    _TEAM_SEED = (
        ("chief_of_staff", 0),
        ("executive_assistant", 0),
        ("marketing_content", 1),
        ("second_brain", 0),
    )

    def ensure_worlds(self) -> None:
        """Seed Jonathan's worlds once, and fill any that an older desk missed."""
        if self.get_setting("worlds_catalog") == _CATALOG_VERSION:
            self._upgrade_revenue_playbooks()
            return
        by_name = {world["name"]: world for world in self.list_worlds()}
        ids: dict[str, str] = {}
        for spec in _WORLD_CATALOG:
            current = by_name.get(spec["name"])
            if current is None:
                created = self.create_world(
                    spec["name"],
                    kind=spec["kind"],
                    summary=spec["summary"],
                    accent=spec["accent"],
                    mark=spec["mark"],
                    aliases=spec["aliases"],
                    briefs=spec["briefs"],
                    higgsfield=spec["higgsfield"],
                )
                ids[spec["name"]] = created["id"]
            else:
                ids[spec["name"]] = current["id"]
                self._refresh_catalog_world(current, spec)
        self._assign_catalog_projects(ids)
        personal_id = ids.get("Personal") or ""
        if personal_id:
            self._backfill_world(personal_id)
        self.set_setting("worlds_seeded", "1")
        self.set_setting("worlds_catalog", _CATALOG_VERSION)
        self._upgrade_revenue_playbooks()

    def _refresh_catalog_world(
        self, current: dict[str, Any], spec: dict[str, Any]
    ) -> None:
        """Fill identity on a world that was seeded before this catalog."""
        fields: dict[str, str] = {}
        old_summary = (current.get("summary") or "").strip()
        if old_summary in _PLACEHOLDER_SUMMARIES or not old_summary:
            fields["summary"] = spec["summary"]
            fields["accent"] = spec["accent"]
        if not (current.get("mark") or "").strip():
            fields["mark"] = spec["mark"]
        if not (current.get("aliases") or "").strip():
            fields["aliases"] = spec["aliases"]
        if fields:
            self.update_world(current["id"], **fields)
        briefs = spec["briefs"]
        higgs = spec["higgsfield"]
        for row in self.team(current["id"]):
            if (row.get("brief") or "").strip():
                continue
            self.update_team(
                current["id"],
                row["specialist_id"],
                brief=briefs.get(row["specialist_id"], ""),
                higgsfield=bool(higgs.get(row["specialist_id"], row["higgsfield"])),
            )

    def _upgrade_revenue_playbooks(self) -> None:
        """Replace untouched seed briefs with the revenue playbooks."""
        if self.get_setting("revenue_playbooks") == "1":
            return
        by_name = {world["name"]: world for world in self.list_worlds()}
        for spec in _WORLD_CATALOG:
            world = by_name.get(spec["name"])
            if world is None:
                continue
            previous = _OLD_PLAYBOOKS.get(spec["name"], {})
            for row in self.team(world["id"]):
                current = (row.get("brief") or "").strip()
                old = (previous.get(row["specialist_id"]) or "").strip()
                new = spec["briefs"].get(row["specialist_id"], "")
                if current and current != old:
                    continue
                if new:
                    self.update_team(world["id"], row["specialist_id"], brief=new)
        self.set_setting("revenue_playbooks", "1")

    def _assign_catalog_projects(self, ids: dict[str, str]) -> None:
        personal_id = ids.get("Personal") or ""
        funders_id = ids.get("Quick Funders") or personal_id
        audit_id = ids.get("Self Financial Audit") or personal_id
        for project in self.list_projects():
            name = project["name"].lower()
            if "quick funders" in name and funders_id:
                target = funders_id
                summary = _CRM_SUMMARY
                accent = "#1f8a70"
            elif "self audit" in name and audit_id:
                target = audit_id
                summary = _AUDIT_PROJECT_SUMMARY
                accent = "#c4a15a"
            elif not project.get("world_id") and personal_id:
                target = personal_id
                summary = ""
                accent = ""
            else:
                continue
            self.set_project_world(project["id"], target)
            old = (project.get("summary") or "").strip()
            if summary and old in _PLACEHOLDER_SUMMARIES:
                self.update_project(project["id"], summary=summary, accent=accent)

    def create_world(
        self,
        name: str,
        *,
        kind: str = "business",
        summary: str = "",
        accent: str = "#7dcea0",
        mark: str = "",
        aliases: str = "",
        briefs: dict[str, str] | None = None,
        higgsfield: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        world_id = _new_id()
        now = _now()
        if kind == "personal":
            kind_name = "personal"
        elif kind == "finance":
            kind_name = "finance"
        else:
            kind_name = "business"
        notes = briefs or {}
        pictures = higgsfield or {}
        with self._lock:
            self._conn.execute(
                "INSERT INTO worlds (id, name, kind, summary, accent, mark, "
                "aliases, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    world_id,
                    name.strip(),
                    kind_name,
                    summary.strip(),
                    accent,
                    mark,
                    aliases,
                    now,
                    now,
                ),
            )
            for specialist_id, default_picture in self._TEAM_SEED:
                picture = pictures.get(specialist_id, default_picture)
                self._conn.execute(
                    "INSERT INTO world_team (world_id, specialist_id, enabled, "
                    "omniroute_model, higgsfield, brief) VALUES (?, ?, 1, '', ?, ?)",
                    (
                        world_id,
                        specialist_id,
                        int(picture),
                        notes.get(specialist_id, ""),
                    ),
                )
            self._conn.commit()
        world = self.get_world(world_id)
        assert world is not None
        return world

    def list_worlds(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM worlds ORDER BY kind DESC, created_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_world(self, world_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM worlds WHERE id = ?", (world_id,)
            ).fetchone()
        return dict(row) if row else None

    def personal_world(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM worlds WHERE kind = 'personal' "
                "ORDER BY created_at LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def match_world(self, text: str) -> dict[str, Any] | None:
        import re

        lowered = (text or "").lower()
        found: dict[str, Any] | None = None
        found_len = -1
        for world in self.list_worlds():
            extra = world.get("aliases") or ""
            labels = [world["name"], *[part.strip() for part in extra.split(",")]]
            for label in labels:
                name = label.strip().lower()
                if not name:
                    continue
                if re.search(rf"\b{re.escape(name)}\b", lowered) and (
                    found is None or len(name) > found_len
                ):
                    found = world
                    found_len = len(name)
        return found

    def update_world(self, world_id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = ("name", "summary", "accent", "mark", "aliases")
        sets: list[str] = []
        values: list[Any] = []
        for key in allowed:
            if key in fields and fields[key] is not None:
                sets.append(f"{key} = ?")
                values.append(str(fields[key]).strip())
        if not sets:
            return self.get_world(world_id)
        sets.append("updated_at = ?")
        values.append(_now())
        values.append(world_id)
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE worlds SET {', '.join(sets)} WHERE id = ?",
                values,
            )
            self._conn.commit()
        if cur.rowcount == 0:
            return None
        return self.get_world(world_id)

    def delete_world(self, world_id: str) -> str:
        world = self.get_world(world_id)
        if world is None:
            return "missing"
        if world["kind"] == "personal":
            return "personal"
        with self._lock:
            mission_ids = [
                row["id"]
                for row in self._conn.execute(
                    "SELECT id FROM missions WHERE world_id = ?", (world_id,)
                ).fetchall()
            ]
            for mission_id in mission_ids:
                self._conn.execute(
                    "DELETE FROM tasks WHERE mission_id = ?", (mission_id,)
                )
            for table in (
                "projects",
                "goals",
                "missions",
                "notes",
                "deliverables",
                "proposals",
                "world_team",
                "google_accounts",
                "scoped_agent_state",
            ):
                self._conn.execute(
                    f"DELETE FROM {table} WHERE world_id = ?",
                    (world_id,),
                )
            self._conn.execute("DELETE FROM worlds WHERE id = ?", (world_id,))
            self._conn.commit()
        return "deleted"

    def set_project_world(self, project_id: str, world_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE projects SET world_id = ?, updated_at = ? WHERE id = ?",
                (world_id, _now(), project_id),
            )
            self._conn.commit()

    def _backfill_world(self, personal_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE goals SET world_id = ("
                "SELECT projects.world_id FROM projects "
                "WHERE projects.id = goals.project_id) "
                "WHERE goals.project_id IS NOT NULL "
                "AND (goals.world_id IS NULL OR goals.world_id = '')"
            )
            self._conn.execute(
                "UPDATE missions SET world_id = ("
                "SELECT projects.world_id FROM projects "
                "WHERE projects.id = missions.project_id) "
                "WHERE missions.project_id IS NOT NULL "
                "AND (missions.world_id IS NULL OR missions.world_id = '')"
            )
            for table in ("goals", "missions", "notes", "deliverables", "proposals"):
                self._conn.execute(
                    f"UPDATE {table} SET world_id = ? "
                    "WHERE world_id IS NULL OR world_id = ''",
                    (personal_id,),
                )
            self._conn.commit()

    def team(self, world_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM world_team WHERE world_id = ? ORDER BY specialist_id",
                (world_id,),
            ).fetchall()
        team = []
        for row in rows:
            data = dict(row)
            data["enabled"] = bool(data["enabled"])
            data["higgsfield"] = bool(data["higgsfield"])
            team.append(data)
        return team

    def update_team(
        self, world_id: str, specialist_id: str, **fields: Any
    ) -> dict[str, Any] | None:
        current = next(
            (
                row
                for row in self.team(world_id)
                if row["specialist_id"] == specialist_id
            ),
            None,
        )
        if current is None:
            return None
        enabled = 1 if fields.get("enabled", current["enabled"]) else 0
        higgsfield = 1 if fields.get("higgsfield", current["higgsfield"]) else 0
        model = fields.get("omniroute_model", current["omniroute_model"])
        brief = fields.get("brief", current.get("brief") or "")
        with self._lock:
            self._conn.execute(
                "UPDATE world_team SET enabled = ?, omniroute_model = ?, "
                "higgsfield = ?, brief = ? WHERE world_id = ? AND specialist_id = ?",
                (
                    enabled,
                    str(model or ""),
                    higgsfield,
                    str(brief or ""),
                    world_id,
                    specialist_id,
                ),
            )
            self._conn.commit()
        return next(
            row for row in self.team(world_id) if row["specialist_id"] == specialist_id
        )

    def add_google_account(
        self,
        world_id: str,
        *,
        email: str,
        credentials_path: str = "",
        label: str = "",
    ) -> dict[str, Any]:
        account_id = _new_id()
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO google_accounts (id, world_id, email, label, "
                "credentials_path, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    account_id,
                    world_id,
                    email.strip(),
                    (label or email).strip(),
                    credentials_path.strip(),
                    now,
                ),
            )
            self._conn.commit()
        account = self.get_google_account(account_id)
        assert account is not None
        return account

    def list_google_accounts(self, world_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if world_id:
                rows = self._conn.execute(
                    "SELECT * FROM google_accounts WHERE world_id = ? "
                    "ORDER BY created_at",
                    (world_id,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM google_accounts ORDER BY created_at"
                ).fetchall()
        return [dict(row) for row in rows]

    def get_google_account(self, account_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM google_accounts WHERE id = ?", (account_id,)
            ).fetchone()
        return dict(row) if row else None

    def delete_google_account(self, account_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM google_accounts WHERE id = ?", (account_id,)
            )
            self._conn.commit()
        return cur.rowcount > 0

    def set_scoped_state(
        self, world_id: str, specialist_id: str, status: str, current_work: str
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO scoped_agent_state (world_id, specialist_id, status, "
                "current_work, updated_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(world_id, specialist_id) DO UPDATE SET "
                "status = excluded.status, current_work = excluded.current_work, "
                "updated_at = excluded.updated_at",
                (world_id or "*", specialist_id, status, current_work, _now()),
            )
            self._conn.commit()

    def scoped_states(self, world_id: str) -> dict[str, dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM scoped_agent_state WHERE world_id = ?",
                (world_id or "*",),
            ).fetchall()
        return {row["specialist_id"]: dict(row) for row in rows}

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self._conn.commit()

    def add_media(self, deliverable_id: str, asset: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        row = {
            "id": _new_id(),
            "deliverable_id": deliverable_id,
            "kind": asset.get("kind") or "image",
            "prompt": asset.get("prompt") or "",
            "status": asset.get("status") or "skipped",
            "url": asset.get("url") or "",
            "request_id": asset.get("request_id") or "",
            "detail": asset.get("detail") or "",
            "created_at": now,
        }
        with self._lock:
            self._conn.execute(
                "INSERT INTO media (id, deliverable_id, kind, prompt, status, url, "
                "request_id, detail, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row["id"],
                    row["deliverable_id"],
                    row["kind"],
                    row["prompt"],
                    row["status"],
                    row["url"],
                    row["request_id"],
                    row["detail"],
                    row["created_at"],
                ),
            )
            self._conn.commit()
        return row

    def add_proposal(
        self,
        *,
        kind: str,
        title: str,
        payload: dict[str, Any],
        mission_id: str = "",
        world_id: str = "",
    ) -> dict[str, Any]:
        now = _now()
        row_id = _new_id()
        with self._lock:
            self._conn.execute(
                "INSERT INTO proposals (id, kind, title, payload_json, status, "
                "detail, mission_id, world_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'pending', '', ?, ?, ?, ?)",
                (
                    row_id,
                    kind,
                    title,
                    json.dumps(payload),
                    mission_id,
                    world_id or None,
                    now,
                    now,
                ),
            )
            self._conn.commit()
        stored = self.get_proposal(row_id)
        assert stored is not None
        return stored

    def get_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM proposals WHERE id = ?", (proposal_id,)
            ).fetchone()
        return self._proposal(row) if row else None

    def list_proposals(self, limit: int = 40) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM proposals ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._proposal(row) for row in rows]

    def update_proposal(
        self,
        proposal_id: str,
        *,
        status: str,
        detail: str = "",
    ) -> dict[str, Any] | None:
        with self._lock:
            self._conn.execute(
                "UPDATE proposals SET status = ?, detail = ?, updated_at = ? "
                "WHERE id = ?",
                (status, detail, _now(), proposal_id),
            )
            self._conn.commit()
        return self.get_proposal(proposal_id)

    @staticmethod
    def _proposal(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["payload"] = json.loads(data.pop("payload_json") or "{}")
        return data

    def _media_rows(self, deliverable_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM media WHERE deliverable_id = ? ORDER BY created_at",
            (deliverable_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def tasks_for_project(
        self, project_id: str, limit: int = 8
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT tasks.* FROM tasks JOIN missions "
                "ON missions.id = tasks.mission_id "
                "WHERE missions.project_id = ? "
                "ORDER BY tasks.updated_at DESC LIMIT ?",
                (project_id, limit),
            ).fetchall()
        tasks = []
        for row in rows:
            data = dict(row)
            data["a2a"] = json.loads(data.pop("a2a_json") or "{}")
            tasks.append(data)
        return tasks

    def delete_note(self, note_id: str) -> None:
        if not note_id:
            return
        with self._lock:
            self._conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            self._conn.commit()

    def add_knowledge_item(
        self,
        *,
        title: str,
        kind: str,
        source: str,
        body: str,
        summary: str,
        lessons: list[str],
        sops: list[str],
        ideas: list[str],
    ) -> dict[str, Any]:
        item_id = _new_id()
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO knowledge_items (id, title, kind, source, body, "
                "summary, lessons_json, sops_json, ideas_json, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)",
                (
                    item_id,
                    title,
                    kind,
                    source,
                    body,
                    summary,
                    json.dumps(lessons),
                    json.dumps(sops),
                    json.dumps(ideas),
                    now,
                ),
            )
            self._conn.commit()
        item = self.get_knowledge_item(item_id)
        assert item is not None
        return item

    def get_knowledge_item(self, item_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM knowledge_items WHERE id = ?", (item_id,)
            ).fetchone()
        return self._knowledge_item(row) if row else None

    def list_knowledge_items(self, status: str = "active") -> list[dict[str, Any]]:
        with self._lock:
            if status:
                rows = self._conn.execute(
                    "SELECT * FROM knowledge_items WHERE status = ? "
                    "ORDER BY created_at DESC",
                    (status,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM knowledge_items ORDER BY created_at DESC"
                ).fetchall()
        return [self._knowledge_item(row) for row in rows]

    def set_knowledge_status(self, item_id: str, status: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE knowledge_items SET status = ? WHERE id = ?",
                (status, item_id),
            )
            self._conn.commit()

    def add_knowledge_route(
        self,
        *,
        item_id: str,
        world_id: str,
        specialist_id: str,
        note_id: str = "",
        memory_id: str = "",
        reason: str = "",
    ) -> dict[str, Any]:
        route_id = _new_id()
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO knowledge_routes (id, item_id, world_id, "
                "specialist_id, note_id, memory_id, reason, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    route_id,
                    item_id,
                    world_id,
                    specialist_id,
                    note_id,
                    memory_id,
                    reason,
                    now,
                ),
            )
            self._conn.commit()
        return {
            "id": route_id,
            "item_id": item_id,
            "world_id": world_id,
            "specialist_id": specialist_id,
            "note_id": note_id,
            "memory_id": memory_id,
            "reason": reason,
            "created_at": now,
        }

    def list_knowledge_routes(self, item_id: str = "") -> list[dict[str, Any]]:
        with self._lock:
            if item_id:
                rows = self._conn.execute(
                    "SELECT * FROM knowledge_routes WHERE item_id = ? "
                    "ORDER BY created_at",
                    (item_id,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM knowledge_routes ORDER BY created_at"
                ).fetchall()
        return [dict(row) for row in rows]

    def delete_knowledge_routes(self, item_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM knowledge_routes WHERE item_id = ?", (item_id,)
            )
            self._conn.commit()

    def knowledge_count(self, world_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(DISTINCT item_id) AS n FROM knowledge_routes "
                "WHERE world_id = ?",
                (world_id,),
            ).fetchone()
        return int(row["n"]) if row else 0

    def learned_counts(self, world_id: str) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT specialist_id, COUNT(DISTINCT item_id) AS n "
                "FROM knowledge_routes WHERE world_id = ? GROUP BY specialist_id",
                (world_id,),
            ).fetchall()
        return {row["specialist_id"]: int(row["n"]) for row in rows}

    def add_playbook_proposal(
        self,
        *,
        world_id: str,
        specialist_id: str,
        item_id: str,
        proposed_brief: str,
        reason: str,
    ) -> dict[str, Any]:
        proposal_id = _new_id()
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO playbook_proposals (id, world_id, specialist_id, "
                "item_id, proposed_brief, reason, status, detail, created_at, "
                "updated_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', '', ?, ?)",
                (
                    proposal_id,
                    world_id,
                    specialist_id,
                    item_id,
                    proposed_brief,
                    reason,
                    now,
                    now,
                ),
            )
            self._conn.commit()
        proposal = self.get_playbook_proposal(proposal_id)
        assert proposal is not None
        return proposal

    def get_playbook_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM playbook_proposals WHERE id = ?", (proposal_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_playbook_proposals(self, status: str = "") -> list[dict[str, Any]]:
        with self._lock:
            if status:
                rows = self._conn.execute(
                    "SELECT * FROM playbook_proposals WHERE status = ? "
                    "ORDER BY created_at DESC",
                    (status,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM playbook_proposals ORDER BY created_at DESC"
                ).fetchall()
        return [dict(row) for row in rows]

    def update_playbook_proposal(
        self, proposal_id: str, *, status: str, detail: str = ""
    ) -> dict[str, Any] | None:
        with self._lock:
            self._conn.execute(
                "UPDATE playbook_proposals SET status = ?, detail = ?, "
                "updated_at = ? WHERE id = ?",
                (status, detail, _now(), proposal_id),
            )
            self._conn.commit()
        return self.get_playbook_proposal(proposal_id)

    @staticmethod
    def _knowledge_item(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["lessons"] = json.loads(data.pop("lessons_json") or "[]")
        data["sops"] = json.loads(data.pop("sops_json") or "[]")
        data["ideas"] = json.loads(data.pop("ideas_json") or "[]")
        return data

    def add_spend(
        self,
        *,
        world_id: str,
        specialist_id: str,
        kind: str,
        amount: float,
        month: str,
        model: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        detail: str = "",
    ) -> dict[str, Any]:
        spend_id = _new_id()
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO spend_entries (id, world_id, specialist_id, kind, "
                "model, input_tokens, output_tokens, amount, detail, month, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    spend_id,
                    world_id or "",
                    specialist_id or "",
                    kind,
                    model,
                    int(input_tokens),
                    int(output_tokens),
                    float(amount),
                    detail,
                    month,
                    now,
                ),
            )
            self._conn.commit()
        return {"id": spend_id, "amount": float(amount), "month": month}

    def spend_rows(self, month: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM spend_entries WHERE month = ? ORDER BY created_at",
                (month,),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_revenue(
        self,
        *,
        world_id: str,
        amount: float,
        month: str,
        source: str = "manual",
        note: str = "",
    ) -> dict[str, Any]:
        revenue_id = _new_id()
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO revenue_entries (id, world_id, amount, source, "
                "note, month, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (revenue_id, world_id, float(amount), source, note, month, now),
            )
            self._conn.commit()
        return {
            "id": revenue_id,
            "world_id": world_id,
            "amount": float(amount),
            "source": source,
            "note": note,
            "month": month,
            "created_at": now,
        }

    def revenue_rows(self, month: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM revenue_entries WHERE month = ? ORDER BY created_at",
                (month,),
            ).fetchall()
        return [dict(row) for row in rows]

    def completed_task_count(self, month: str, world_id: str = "") -> int:
        start, end = _month_bounds(month)
        with self._lock:
            if world_id:
                row = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM tasks JOIN missions "
                    "ON missions.id = tasks.mission_id "
                    "WHERE tasks.status = 'done' AND missions.world_id = ? "
                    "AND tasks.updated_at >= ? AND tasks.updated_at < ?",
                    (world_id, start, end),
                ).fetchone()
            else:
                row = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM tasks "
                    "WHERE status = 'done' AND updated_at >= ? "
                    "AND updated_at < ?",
                    (start, end),
                ).fetchone()
        return int(row["n"]) if row else 0

    def add_budget_alert(
        self, *, world_id: str, level: str, message: str, month: str
    ) -> dict[str, Any] | None:
        with self._lock:
            existing = self._conn.execute(
                "SELECT id FROM budget_alerts WHERE world_id = ? AND level = ? "
                "AND month = ? LIMIT 1",
                (world_id or "", level, month),
            ).fetchone()
            if existing:
                return None
            alert_id = _new_id()
            now = _now()
            self._conn.execute(
                "INSERT INTO budget_alerts (id, world_id, level, message, "
                "month, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (alert_id, world_id or "", level, message, month, now),
            )
            self._conn.commit()
        return {
            "id": alert_id,
            "world_id": world_id or "",
            "level": level,
            "message": message,
            "month": month,
            "created_at": now,
        }

    def budget_alerts(self, month: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM budget_alerts WHERE month = ? ORDER BY created_at",
                (month,),
            ).fetchall()
        return [dict(row) for row in rows]
