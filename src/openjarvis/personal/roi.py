"""Cost, value, and budget for the personal desk.

Spend is recorded per world and per agent. Token cost comes from OmniRoute
when the gateway reports it, and otherwise from a price table Jonathan can
edit. A monthly cap warns at 80 percent, switches to a cheaper model before
the next paid call, and refuses that call when even the cheap model would
go over the cap.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

SETTINGS_KEY = "roi"

DEFAULT_PRICES: dict[str, Any] = {
    "strong": {"input": 5.0, "output": 15.0},
    "hermes": {"input": 0.4, "output": 0.4},
    "cheap": {"input": 0.15, "output": 0.6},
    "default": {"input": 1.0, "output": 3.0},
    "higgsfield_image": 0.08,
    "higgsfield_video": 0.40,
    "models": {},
}

DEFAULT_OVERALL_BUDGET = 80.0
DEFAULT_WORLD_BUDGET = {"business": 25.0, "personal": 10.0, "finance": 10.0}
DEFAULT_HOURLY_RATE = 50.0
DEFAULT_MINUTES = 15.0


def current_month(now: datetime | None = None) -> str:
    stamp = now or datetime.now(timezone.utc)
    return f"{stamp.year:04d}-{stamp.month:02d}"


def estimate_tokens(text: str) -> int:
    return max(1, (len(text or "") + 3) // 4)


def tier_for(specialist_id: str) -> str:
    if specialist_id == "chief_of_staff":
        return "strong"
    if specialist_id == "executive_assistant":
        return "hermes"
    if specialist_id == "second_brain":
        return "cheap"
    return "default"


def _rate(prices: dict[str, Any], tier: str, model: str = "") -> dict[str, float]:
    models = prices.get("models") or {}
    if model and isinstance(models.get(model), dict):
        raw = models[model]
    else:
        raw = prices.get(tier) or prices.get("default") or DEFAULT_PRICES["default"]
    return {
        "input": float(raw.get("input") or 0),
        "output": float(raw.get("output") or 0),
    }


def token_cost(
    prices: dict[str, Any],
    tier: str,
    input_tokens: int,
    output_tokens: int,
    *,
    model: str = "",
) -> float:
    """USD from a per-million-token price table."""
    rate = _rate(prices, tier, model)
    cost = (
        int(input_tokens) * rate["input"] + int(output_tokens) * rate["output"]
    ) / 1_000_000
    return round(cost, 6)


def call_cost(
    prices: dict[str, Any],
    tier: str,
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    reported: float | None,
) -> float:
    """Prefer OmniRoute's reported USD, otherwise the price table."""
    if reported is not None and reported >= 0:
        return round(float(reported), 6)
    return token_cost(
        prices,
        tier,
        input_tokens,
        output_tokens,
        model=model,
    )


def budget_action(
    *,
    spent_world: float,
    spent_overall: float,
    world_cap: float,
    overall_cap: float,
    estimated: float,
    tier: str,
) -> str:
    """Return ``ok``, ``downgrade``, or ``block``.

    A cap of 0 is unset. Near a cap (80 percent) the next call uses the cheap
    tier. A call that would pass the cap is not sent.
    """
    rooms: list[float] = []
    ratios: list[float] = []
    if overall_cap > 0:
        rooms.append(overall_cap - spent_overall)
        ratios.append((spent_overall + estimated) / overall_cap)
    if world_cap > 0:
        rooms.append(world_cap - spent_world)
        ratios.append((spent_world + estimated) / world_cap)
    if not rooms:
        return "ok"
    room = min(rooms)
    if room <= 0 or estimated > room:
        return "block" if tier == "cheap" else "downgrade"
    if any(ratio >= 0.8 for ratio in ratios) and tier != "cheap":
        return "downgrade"
    return "ok"


def _money(value: float) -> float:
    return round(float(value), 4)


def picture(
    *,
    cost: float,
    revenue: float,
    hours: float,
    hourly_rate: float,
    budget: float,
) -> dict[str, Any]:
    time_value = _money(hours * hourly_rate)
    value = _money(revenue + time_value)
    net = _money(value - cost)
    ratio = None
    if cost > 0:
        ratio = round((value - cost) / cost, 4)
    alert = ""
    if budget > 0 and cost >= budget:
        alert = "blocked"
    elif budget > 0 and cost >= budget * 0.8:
        alert = "warn"
    return {
        "cost": _money(cost),
        "revenue": _money(revenue),
        "hours_saved": round(hours, 2),
        "time_value": time_value,
        "value": value,
        "net": net,
        "roi": ratio,
        "paying": value > 0 and value >= cost,
        "budget": _money(budget),
        "alert": alert,
    }


class RoiLedger:
    """Read and write the desk's month of cost and value."""

    def __init__(self, office: Any) -> None:
        self.office = office

    def ensure_defaults(self) -> None:
        if self.office.store.get_setting(SETTINGS_KEY, ""):
            return
        worlds = {}
        for world in self.office.store.list_worlds():
            kind = world.get("kind") or "business"
            worlds[world["id"]] = DEFAULT_WORLD_BUDGET.get(kind, 25.0)
        self.save_settings(
            {
                "hourly_rate": DEFAULT_HOURLY_RATE,
                "minutes_per_task": DEFAULT_MINUTES,
                "budgets": {"overall": DEFAULT_OVERALL_BUDGET, "worlds": worlds},
                "prices": DEFAULT_PRICES,
                "recurring": [],
                "strong_model": "",
                "cheap_model": "",
            }
        )

    def settings(self) -> dict[str, Any]:
        raw = self.office.store.get_setting(SETTINGS_KEY, "")
        try:
            saved = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            saved = {}
        if not isinstance(saved, dict):
            saved = {}
        prices = dict(DEFAULT_PRICES)
        custom = saved.get("prices") if isinstance(saved.get("prices"), dict) else {}
        for key, value in custom.items():
            prices[key] = value
        budgets = saved.get("budgets") if isinstance(saved.get("budgets"), dict) else {}
        raw_worlds = budgets.get("worlds")
        world_caps = raw_worlds if isinstance(raw_worlds, dict) else {}
        raw_recurring = saved.get("recurring")
        recurring = raw_recurring if isinstance(raw_recurring, list) else []
        return {
            "hourly_rate": float(saved.get("hourly_rate") or DEFAULT_HOURLY_RATE),
            "minutes_per_task": float(saved.get("minutes_per_task") or DEFAULT_MINUTES),
            "budgets": {
                "overall": float(budgets.get("overall") or 0),
                "worlds": {str(key): float(value) for key, value in world_caps.items()},
            },
            "prices": prices,
            "recurring": [item for item in recurring if isinstance(item, dict)],
            "strong_model": str(saved.get("strong_model") or ""),
            "cheap_model": str(saved.get("cheap_model") or ""),
        }

    def save_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        saved = self.office.store.get_setting(SETTINGS_KEY, "")
        current = (
            self.settings()
            if saved
            else {
                "hourly_rate": DEFAULT_HOURLY_RATE,
                "minutes_per_task": DEFAULT_MINUTES,
                "budgets": {"overall": 0, "worlds": {}},
                "prices": DEFAULT_PRICES,
                "recurring": [],
                "strong_model": "",
                "cheap_model": "",
            }
        )
        if "hourly_rate" in payload:
            current["hourly_rate"] = max(0.0, float(payload["hourly_rate"]))
        if "minutes_per_task" in payload:
            current["minutes_per_task"] = max(0.0, float(payload["minutes_per_task"]))
        if "strong_model" in payload:
            current["strong_model"] = str(payload["strong_model"] or "")
        if "cheap_model" in payload:
            current["cheap_model"] = str(payload["cheap_model"] or "")
        if isinstance(payload.get("budgets"), dict):
            current["budgets"] = payload["budgets"]
        if isinstance(payload.get("prices"), dict):
            current["prices"] = payload["prices"]
        if isinstance(payload.get("recurring"), list):
            current["recurring"] = payload["recurring"]
        self.office.store.set_setting(SETTINGS_KEY, json.dumps(current))
        return self.settings()

    def record_llm(
        self,
        *,
        world_id: str,
        specialist_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        reported: float | None = None,
    ) -> float:
        settings = self.settings()
        amount = call_cost(
            settings["prices"],
            tier_for(specialist_id),
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            reported=reported,
        )
        detail = "omniroute" if reported is not None else "price table"
        self.office.store.add_spend(
            world_id=world_id,
            specialist_id=specialist_id,
            kind="llm",
            amount=amount,
            month=current_month(),
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            detail=detail,
        )
        self._note_threshold(world_id)
        return amount

    def record_higgsfield(
        self, *, world_id: str, specialist_id: str, kind: str
    ) -> float:
        settings = self.settings()
        prices = settings["prices"]
        key = "higgsfield_video" if kind == "video" else "higgsfield_image"
        amount = float(prices.get(key) or 0)
        self.office.store.add_spend(
            world_id=world_id,
            specialist_id=specialist_id,
            kind="higgsfield",
            amount=amount,
            month=current_month(),
            model=kind,
            detail="Higgsfield",
        )
        self._note_threshold(world_id)
        return amount

    def add_revenue(
        self, *, world_id: str, amount: float, note: str = "", source: str = "manual"
    ) -> dict[str, Any]:
        if amount <= 0:
            raise ValueError("Revenue has to be more than zero.")
        if self.office.store.get_world(world_id) is None:
            raise ValueError("That world does not exist.")
        return self.office.store.add_revenue(
            world_id=world_id,
            amount=amount,
            month=current_month(),
            source=source if source in {"manual", "hook"} else "manual",
            note=note.strip(),
        )

    def decide(
        self, world_id: str, specialist_id: str, prompt: str
    ) -> tuple[str, float]:
        """Whether this call may use its normal model."""
        settings = self.settings()
        tier = tier_for(specialist_id)
        estimated = token_cost(
            settings["prices"],
            tier,
            estimate_tokens(prompt) + 200,
            900,
        )
        spent_world, spent_overall = self._spent(world_id)
        caps = settings["budgets"]
        action = budget_action(
            spent_world=spent_world,
            spent_overall=spent_overall,
            world_cap=float(caps["worlds"].get(world_id) or 0),
            overall_cap=float(caps["overall"] or 0),
            estimated=estimated,
            tier=tier,
        )
        if action == "downgrade":
            cheap_estimate = token_cost(
                settings["prices"],
                "cheap",
                estimate_tokens(prompt) + 200,
                900,
            )
            again = budget_action(
                spent_world=spent_world,
                spent_overall=spent_overall,
                world_cap=float(caps["worlds"].get(world_id) or 0),
                overall_cap=float(caps["overall"] or 0),
                estimated=cheap_estimate,
                tier="cheap",
            )
            if again == "block":
                action = "block"
        if action != "ok":
            self._alert(world_id, action)
        return action, estimated

    def line(self, world_id: str) -> dict[str, Any]:
        report = self.report()
        for world in report["worlds"]:
            if world["id"] == world_id:
                return {
                    "cost": world["cost"],
                    "value": world["value"],
                    "net": world["net"],
                    "paying": world["paying"],
                    "alert": world["alert"],
                }
        return {"cost": 0, "value": 0, "net": 0, "paying": False, "alert": ""}

    def report(self) -> dict[str, Any]:
        month = current_month()
        settings = self.settings()
        rate = settings["hourly_rate"]
        minutes = settings["minutes_per_task"]
        spend = self.office.store.spend_rows(month)
        revenue = self.office.store.revenue_rows(month)
        names = {
            world["id"]: world["name"] for world in self.office.store.list_worlds()
        }
        worlds = []
        for world in self.office.store.list_worlds():
            worlds.append(
                self._world_row(
                    world,
                    spend,
                    revenue,
                    settings,
                    rate,
                    minutes,
                    month,
                )
            )
        llm = sum(row["amount"] for row in spend if row["kind"] == "llm")
        pictures = sum(row["amount"] for row in spend if row["kind"] == "higgsfield")
        recurring = sum(
            float(item.get("amount") or 0) for item in settings["recurring"]
        )
        cost = llm + pictures + recurring
        revenue_total = sum(row["amount"] for row in revenue)
        hours = self.office.store.completed_task_count(month) * minutes / 60
        overall = picture(
            cost=cost,
            revenue=revenue_total,
            hours=hours,
            hourly_rate=rate,
            budget=float(settings["budgets"]["overall"] or 0),
        )
        overall["llm"] = _money(llm)
        overall["higgsfield"] = _money(pictures)
        overall["recurring"] = _money(recurring)
        agents = self._agents(spend, names)
        gateway = self._gateway()
        return {
            "month": month,
            "overall": overall,
            "worlds": worlds,
            "agents": agents,
            "alerts": self.office.store.budget_alerts(month),
            "gateway": gateway,
            "settings": {
                "hourly_rate": rate,
                "minutes_per_task": minutes,
                "budgets": settings["budgets"],
                "prices": settings["prices"],
                "recurring": settings["recurring"],
                "strong_model": settings["strong_model"],
                "cheap_model": settings["cheap_model"],
            },
        }

    def _world_row(
        self,
        world: dict[str, Any],
        spend: list[dict[str, Any]],
        revenue: list[dict[str, Any]],
        settings: dict[str, Any],
        rate: float,
        minutes: float,
        month: str,
    ) -> dict[str, Any]:
        world_id = world["id"]
        rows = [row for row in spend if row["world_id"] == world_id]
        llm = sum(row["amount"] for row in rows if row["kind"] == "llm")
        pictures = sum(row["amount"] for row in rows if row["kind"] == "higgsfield")
        extra = sum(
            float(item.get("amount") or 0)
            for item in settings["recurring"]
            if str(item.get("world_id") or "") == world_id
        )
        earned = sum(row["amount"] for row in revenue if row["world_id"] == world_id)
        tasks = self.office.store.completed_task_count(month, world_id)
        view = picture(
            cost=llm + pictures + extra,
            revenue=earned,
            hours=tasks * minutes / 60,
            hourly_rate=rate,
            budget=float(settings["budgets"]["worlds"].get(world_id) or 0),
        )
        view.update(
            {
                "id": world_id,
                "name": world["name"],
                "llm": _money(llm),
                "higgsfield": _money(pictures),
                "recurring": _money(extra),
            }
        )
        return view

    def _agents(
        self, spend: list[dict[str, Any]], names: dict[str, str]
    ) -> list[dict[str, Any]]:
        from openjarvis.personal.knowledge import specialist_name

        buckets: dict[tuple[str, str], dict[str, Any]] = {}
        for row in spend:
            if row["kind"] not in {"llm", "higgsfield"}:
                continue
            key = (row["world_id"], row["specialist_id"])
            bucket = buckets.setdefault(
                key,
                {
                    "world_id": row["world_id"],
                    "world_name": names.get(row["world_id"], row["world_id"]),
                    "specialist_id": row["specialist_id"],
                    "agent_name": specialist_name(row["specialist_id"] or "desk"),
                    "cost": 0.0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                },
            )
            bucket["cost"] += row["amount"]
            bucket["input_tokens"] += int(row["input_tokens"] or 0)
            bucket["output_tokens"] += int(row["output_tokens"] or 0)
        agents = []
        for bucket in buckets.values():
            bucket["cost"] = _money(bucket["cost"])
            agents.append(bucket)
        return agents

    def _spent(self, world_id: str) -> tuple[float, float]:
        month = current_month()
        rows = self.office.store.spend_rows(month)
        settings = self.settings()
        recurring = settings["recurring"]
        world_recurring = sum(
            float(item.get("amount") or 0)
            for item in recurring
            if str(item.get("world_id") or "") == world_id
        )
        overall_recurring = sum(float(item.get("amount") or 0) for item in recurring)
        world_spend = sum(row["amount"] for row in rows if row["world_id"] == world_id)
        overall_spend = sum(row["amount"] for row in rows)
        return world_spend + world_recurring, overall_spend + overall_recurring

    def _note_threshold(self, world_id: str) -> None:
        settings = self.settings()
        spent_world, spent_overall = self._spent(world_id)
        overall_cap = float(settings["budgets"]["overall"] or 0)
        world_cap = float(settings["budgets"]["worlds"].get(world_id) or 0)
        if overall_cap and spent_overall >= overall_cap * 0.8:
            self._alert("", "warn")
        if world_cap and spent_world >= world_cap * 0.8:
            self._alert(world_id, "warn")

    def _alert(self, world_id: str, level: str) -> None:
        name = "The desk"
        if world_id:
            world = self.office.store.get_world(world_id)
            name = world["name"] if world else "This world"
        if level == "block":
            message = f"{name} is at its monthly cap. The paid model was not called."
        elif level == "downgrade":
            message = (
                f"{name} is near its monthly cap. Agents are using the cheaper model."
            )
        else:
            message = f"{name} has used 80% of its monthly budget."
        self.office.store.add_budget_alert(
            world_id=world_id,
            level=level,
            message=message,
            month=current_month(),
        )

    def _gateway(self) -> dict[str, Any] | None:
        client = getattr(self.office, "omniroute", None)
        fetch = getattr(client, "usage_summary", None)
        if fetch is None:
            return None
        try:
            summary = fetch()
        except Exception:
            return None
        if not summary:
            return None
        return summary
