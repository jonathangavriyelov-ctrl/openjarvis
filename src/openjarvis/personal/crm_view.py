"""Read-only MCA board for the personal desk.

The deals below are samples. This module never calls the live Quick Funders
CRM. A future read-only address can be named in the environment and is only
shown, not used.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openjarvis.personal.connected_bots import connected_bots

STAGES = (
    "New Lead",
    "Contacted",
    "Docs",
    "Submitted",
    "Offer",
    "Contract",
    "Funded",
    "Renewal",
    "Declined",
    "Missing Docs",
    "Re-marketing",
)
OPEN_STAGES = frozenset(STAGES) - {"Declined"}
ROLES = ("owner", "sales", "underwriting", "watcher")
_BRIEF = Path(__file__).with_name("crm_team_brief.md")
_AS_OF = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
_SPEED_MINUTES = 15

_DEALS: tuple[dict[str, Any], ...] = (
    {
        "id": "sample-harbor",
        "business": "Harbor Deli",
        "stage": "New Lead",
        "phone": "(•••) •••-0142",
        "email": "a•••@example.com",
        "consent": "yes",
        "created_at": "2026-09-30T09:00:00+00:00",
        "first_contact_at": "",
        "next_action": "Call and introduce funding",
        "next_action_on": "2026-09-30",
        "amount": 25000,
        "industry": "restaurant",
        "months_in_business": 14,
        "underwriting_note": "",
    },
    {
        "id": "sample-northside",
        "business": "Northside Market",
        "stage": "Contacted",
        "phone": "(•••) •••-2280",
        "email": "p•••@example.com",
        "consent": "do-not-contact",
        "created_at": "2026-09-28T15:00:00+00:00",
        "first_contact_at": "2026-09-28T15:20:00+00:00",
        "next_action": "Do not call. Leave the file closed.",
        "next_action_on": "2026-09-30",
        "amount": 40000,
        "industry": "grocery",
        "months_in_business": 36,
        "underwriting_note": "",
    },
    {
        "id": "sample-lumen",
        "business": "Lumen Trucking",
        "stage": "Docs",
        "phone": "(•••) •••-7731",
        "email": "m•••@example.com",
        "consent": "yes",
        "created_at": "2026-09-27T11:00:00+00:00",
        "first_contact_at": "2026-09-27T11:12:00+00:00",
        "next_action": "Ask for the missing bank statements",
        "next_action_on": "2026-10-01",
        "amount": 75000,
        "industry": "trucking",
        "months_in_business": 20,
        "underwriting_note": "Statements for two months are still out.",
    },
    {
        "id": "sample-cedar",
        "business": "Cedar Dental",
        "stage": "Submitted",
        "phone": "(•••) •••-4409",
        "email": "r•••@example.com",
        "consent": "yes",
        "created_at": "2026-09-20T14:00:00+00:00",
        "first_contact_at": "2026-09-20T14:25:00+00:00",
        "next_action": "Check funder replies",
        "next_action_on": "2026-10-02",
        "amount": 60000,
        "industry": "healthcare",
        "months_in_business": 48,
        "underwriting_note": "Package sent to two funders.",
    },
    {
        "id": "sample-bright",
        "business": "Bright Bakery",
        "stage": "Offer",
        "phone": "(•••) •••-1188",
        "email": "s•••@example.com",
        "consent": "yes",
        "created_at": "2026-09-18T10:00:00+00:00",
        "first_contact_at": "2026-09-18T10:08:00+00:00",
        "next_action": "Walk through the offer",
        "next_action_on": "2026-10-01",
        "amount": 35000,
        "industry": "restaurant",
        "months_in_business": 18,
        "underwriting_note": "One offer is in.",
    },
    {
        "id": "sample-river",
        "business": "River Books",
        "stage": "Funded",
        "phone": "(•••) •••-9021",
        "email": "t•••@example.com",
        "consent": "yes",
        "created_at": "2026-09-02T09:00:00+00:00",
        "first_contact_at": "2026-09-02T09:30:00+00:00",
        "next_action": "Set a renewal check",
        "next_action_on": "2026-12-02",
        "amount": 50000,
        "industry": "retail",
        "months_in_business": 60,
        "underwriting_note": "Funded this month.",
        "funded_on": "2026-09-12",
    },
    {
        "id": "sample-oak",
        "business": "Oak Auto",
        "stage": "Declined",
        "phone": "(•••) •••-3344",
        "email": "k•••@example.com",
        "consent": "yes",
        "created_at": "2026-09-10T13:00:00+00:00",
        "first_contact_at": "2026-09-10T16:00:00+00:00",
        "next_action": "",
        "next_action_on": "",
        "amount": 20000,
        "industry": "auto",
        "months_in_business": 4,
        "underwriting_note": "Too new for the sample funders.",
    },
    {
        "id": "sample-pine",
        "business": "Pine Fitness",
        "stage": "Re-marketing",
        "phone": "(•••) •••-6670",
        "email": "d•••@example.com",
        "consent": "yes",
        "created_at": "2026-08-01T12:00:00+00:00",
        "first_contact_at": "2026-08-01T12:40:00+00:00",
        "next_action": "Send a short check-in",
        "next_action_on": "2026-10-06",
        "amount": 30000,
        "industry": "fitness",
        "months_in_business": 24,
        "underwriting_note": "",
    },
)

_FUNDERS: tuple[dict[str, Any], ...] = (
    {
        "id": "apex",
        "name": "Apex Advance",
        "industries": ["restaurant", "retail"],
        "min_months": 6,
    },
    {
        "id": "bridge",
        "name": "Bridge Capital",
        "industries": ["trucking"],
        "min_months": 12,
    },
    {
        "id": "harbor-fund",
        "name": "Harbor Fund",
        "industries": ["healthcare", "fitness"],
        "min_months": 12,
    },
)

_AUDIT: tuple[dict[str, str], ...] = (
    {
        "at": "2026-09-30T11:05:00+00:00",
        "actor": "Lead Fixer",
        "deal_id": "sample-harbor",
        "change": "Noted that nobody has called yet.",
    },
    {
        "at": "2026-09-28T15:40:00+00:00",
        "actor": "QF CRM",
        "deal_id": "sample-northside",
        "change": "Marked do-not-contact.",
    },
    {
        "at": "2026-09-27T11:20:00+00:00",
        "actor": "Submissions",
        "deal_id": "sample-lumen",
        "change": "Moved the file to Docs.",
    },
)


def crm_connection() -> dict[str, Any]:
    """Name a future read-only address. Never open it."""
    url = os.environ.get("OPENJARVIS_CRM_READONLY_URL", "").strip()
    return {
        "mode": "sample",
        "read_only_url": url,
        "live_read": False,
        "label": "Sample data. Not the live Quick Funders CRM.",
    }


def _parse(stamp: str) -> datetime | None:
    if not stamp:
        return None
    return datetime.fromisoformat(stamp)


def _minutes_between(start: str, end: str) -> int | None:
    left = _parse(start)
    right = _parse(end)
    if left is None or right is None:
        return None
    return max(0, int((right - left).total_seconds() // 60))


def _visible(deal: dict[str, Any], role: str) -> bool:
    stage = deal["stage"]
    if role == "underwriting":
        return stage in {
            "Docs",
            "Submitted",
            "Offer",
            "Contract",
            "Funded",
            "Missing Docs",
        }
    if role == "sales":
        return stage not in {"Declined"}
    return True


def _public_deal(deal: dict[str, Any], role: str) -> dict[str, Any]:
    row = {
        "id": deal["id"],
        "business": deal["business"],
        "stage": deal["stage"],
        "consent": deal["consent"],
        "next_action": deal["next_action"],
        "next_action_on": deal["next_action_on"],
        "amount": deal["amount"],
        "industry": deal["industry"],
        "created_at": deal["created_at"],
        "untouched": deal["stage"] == "New Lead" and not deal["first_contact_at"],
    }
    if role == "owner":
        row["underwriting_note"] = deal["underwriting_note"]
    if role != "watcher":
        row["phone"] = deal["phone"]
        row["email"] = deal["email"]
    waited = _minutes_between(deal["created_at"], deal["first_contact_at"])
    if waited is not None:
        row["response_minutes"] = waited
    return row


def _alerts(deals: list[dict[str, Any]]) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for deal in _DEALS:
        if deal["stage"] != "New Lead" or deal["first_contact_at"]:
            continue
        if deal["id"] not in {item["id"] for item in deals}:
            continue
        created = _parse(deal["created_at"])
        if created is None:
            continue
        age = int((_AS_OF - created).total_seconds() // 60)
        if age < _SPEED_MINUTES:
            continue
        found.append(
            {
                "kind": "speed_to_lead",
                "deal_id": deal["id"],
                "business": deal["business"],
                "text": f"No call for {age // 60} hours.",
            }
        )
    for deal in deals:
        if deal["consent"] == "do-not-contact":
            found.append(
                {
                    "kind": "do_not_contact",
                    "deal_id": deal["id"],
                    "business": deal["business"],
                    "text": "Do not contact.",
                }
            )
    return found


def _matches(deals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    open_ids = {deal["id"] for deal in deals if deal["consent"] != "do-not-contact"}
    by_id = {deal["id"]: deal for deal in _DEALS}
    for funder in _FUNDERS:
        fits = []
        for deal_id in open_ids:
            deal = by_id[deal_id]
            industry_ok = deal["industry"] in funder["industries"]
            months_ok = deal["months_in_business"] >= funder["min_months"]
            if industry_ok and months_ok and deal["stage"] != "Declined":
                fits.append(deal["business"])
        fits.sort()
        rows.append(
            {
                "id": funder["id"],
                "name": funder["name"],
                "looks_for": (
                    f"{', '.join(funder['industries'])}; "
                    f"{funder['min_months']}+ months in business"
                ),
                "fits": fits,
            }
        )
    return rows


def _metrics(deals: list[dict[str, Any]]) -> dict[str, Any]:
    waits = [
        item["response_minutes"]
        for item in deals
        if "response_minutes" in item
    ]
    funded = [
        deal
        for deal in _DEALS
        if deal["stage"] == "Funded" and deal["id"] in {item["id"] for item in deals}
    ]
    average = round(sum(waits) / len(waits)) if waits else 0
    return {
        "response_minutes": average,
        "funded_count": len(funded),
        "funded_volume": sum(int(deal["amount"]) for deal in funded),
    }


def team_brief() -> str:
    try:
        return _BRIEF.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def crm_snapshot(role: str = "owner") -> dict[str, Any]:
    """One read-only picture of the sample board."""
    chosen = role if role in ROLES else "owner"
    deals = [
        _public_deal(deal, chosen) for deal in _DEALS if _visible(deal, chosen)
    ]
    missing_action = [
        deal["business"]
        for deal in deals
        if deal["stage"] in OPEN_STAGES and not deal["next_action_on"]
    ]
    return {
        "connection": crm_connection(),
        "role": chosen,
        "roles": [
            {"id": "owner", "label": "Owner", "detail": "Whole sample board."},
            {"id": "sales", "label": "Sales", "detail": "Leads and follow-ups."},
            {
                "id": "underwriting",
                "label": "Underwriting",
                "detail": "Files that are in docs or later.",
            },
            {
                "id": "watcher",
                "label": "Watcher",
                "detail": "Stages and next steps. No phone or email.",
            },
        ],
        "stages": list(STAGES),
        "deals": deals,
        "missing_next_action": missing_action,
        "alerts": _alerts(deals),
        "funders": _matches(deals),
        "metrics": _metrics(deals),
        "audit": [
            dict(row)
            for row in _AUDIT
            if row["deal_id"] in {deal["id"] for deal in deals}
        ],
        "bots": connected_bots(),
        "team_brief": team_brief(),
        "checklist": [
            "Stages match an MCA file, including declined and re-marketing.",
            "Every open deal has one dated next step.",
            "An untouched new lead raises a speed-to-lead alert.",
            "Consent and do-not-contact are on the deal.",
            "A funder grid shows who might fit.",
            "Response time and funded volume sit at the top.",
            "Agent writes are listed in an audit log.",
            "The view can be looked at as owner, sales, underwriting, or watcher.",
            "Phone and email are masked. No Social Security or bank numbers.",
        ],
    }
