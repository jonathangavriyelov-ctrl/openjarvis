"""Names and jobs for bots that live in Grok Bot.

Jarvis only displays this list. It does not call Grok Bot. Edit the JSON
to change a name, world, or job.
"""

from __future__ import annotations

import json
from pathlib import Path

_CATALOG = Path(__file__).with_name("connected_bots.json")


def connected_bots() -> list[dict[str, str]]:
    raw = json.loads(_CATALOG.read_text(encoding="utf-8"))
    bots: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        bot_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        world = str(item.get("world") or "").strip()
        role = str(item.get("role") or "").strip()
        if not bot_id or not name:
            continue
        bots.append(
            {"id": bot_id, "name": name, "world": world, "role": role}
        )
    return bots
