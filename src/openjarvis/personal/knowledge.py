"""Teach Jarvis from a note, a file, or a link.

The chief of staff reads the item, pulls out lessons and procedures, and
files them with the worlds and agents they belong to. A video link is read
from captions when a site provides them. A web link is read as plain text.
Playbook changes stay proposals until Jonathan approves them.
"""

from __future__ import annotations

import html
import json
import re
import zipfile
from io import BytesIO
from typing import Any, Callable

_YOUTUBE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)"
    r"([A-Za-z0-9_-]{6,})"
)
_TEACH = re.compile(r"^(?:teach|learn|feed)\s*:?\s*", re.IGNORECASE)
_URL = re.compile(r"https?://\S+")

WORLD_TOPICS: dict[str, tuple[str, ...]] = {
    "quick funders": (
        "mca",
        "merchant cash",
        "underwriting",
        "funder",
        "funders",
        "cash advance",
    ),
    "jwj / gavco": ("jewelry", "diamond", "gemstone", "gavco", "jwj"),
    "glatt express": ("kosher", "glatt", "butcher", "meat delivery"),
    "self financial audit": (
        "expense",
        "budget",
        "bookkeeping",
        "personal finance",
        "self audit",
    ),
}

AGENT_TOPICS: dict[str, tuple[str, ...]] = {
    "marketing_content": (
        "marketing",
        "content strategy",
        "campaign",
        "audience",
        "social media",
    ),
    "executive_assistant": ("underwriting", "sop", "checklist", "step by step"),
    "chief_of_staff": ("chief of staff",),
}

AGENT_NAMES = {
    "chief_of_staff": "Chief of Staff",
    "executive_assistant": "Executive Assistant",
    "marketing_content": "Marketing & Content",
    "second_brain": "Second Brain",
}

_AGENT_PREFIXES = (
    ("marketing & content", "marketing_content"),
    ("marketing", "marketing_content"),
    ("executive assistant", "executive_assistant"),
    ("second brain", "second_brain"),
    ("chief of staff", "chief_of_staff"),
)


def specialist_name(specialist_id: str) -> str:
    return AGENT_NAMES.get(specialist_id, specialist_id.replace("_", " ").title())


def is_teaching(text: str) -> bool:
    """A phone message that should be learned rather than run as a mission."""
    stripped = (text or "").strip()
    if _TEACH.match(stripped):
        return True
    return bool(re.fullmatch(r"https?://\S+", stripped))


def parse_teaching(text: str, worlds: list[dict[str, Any]]) -> dict[str, str]:
    """Split a phone teaching message into a note, a link, and a target."""
    body = _TEACH.sub("", (text or "").strip()).strip()
    world_id = ""
    ordered = sorted(worlds, key=lambda item: len(item.get("name") or ""), reverse=True)
    for world in ordered:
        name = (world.get("name") or "").strip()
        if not name:
            continue
        pattern = re.compile(rf"^(?:for\s+)?{re.escape(name)}\s*:\s*", re.IGNORECASE)
        if pattern.match(body):
            world_id = str(world.get("id") or "")
            body = pattern.sub("", body, count=1).strip()
            break
    specialist_id = ""
    for label, sid in _AGENT_PREFIXES:
        pattern = re.compile(rf"^(?:for\s+)?{re.escape(label)}\s*:\s*", re.IGNORECASE)
        if pattern.match(body):
            specialist_id = sid
            body = pattern.sub("", body, count=1).strip()
            break
    url = ""
    found = _URL.search(body)
    if found:
        url = found.group(0).rstrip(").,")
        body = f"{body[: found.start()]} {body[found.end() :]}".strip()
    return {
        "text": body,
        "url": url,
        "world_id": world_id,
        "specialist_id": specialist_id,
    }


def youtube_id(url: str) -> str:
    match = _YOUTUBE.search(url or "")
    return match.group(1) if match else ""


def captions_from_xml(raw: str) -> str:
    parts = re.findall(r"<text[^>]*>(.*?)</text>", raw or "", flags=re.DOTALL)
    text = " ".join(html.unescape(part) for part in parts)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def captions_from_json3(raw: str) -> str:
    try:
        payload = json.loads(raw or "")
    except json.JSONDecodeError:
        return ""
    words: list[str] = []
    for event in payload.get("events") or []:
        for seg in event.get("segs") or []:
            piece = seg.get("utf8")
            if piece:
                words.append(str(piece))
    return re.sub(r"\s+", " ", "".join(words)).strip()


def _caption_url(page: str) -> str:
    key = '"captionTracks":'
    start = page.find(key)
    if start < 0:
        return ""
    start = page.find("[", start)
    if start < 0:
        return ""
    depth = 0
    end = -1
    for index, char in enumerate(page[start:], start):
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                end = index + 1
                break
    if end < 0:
        return ""
    try:
        tracks = json.loads(page[start:end])
    except json.JSONDecodeError:
        return ""
    english = ""
    fallback = ""
    for track in tracks:
        if not isinstance(track, dict):
            continue
        base = str(track.get("baseUrl") or "")
        if not base:
            continue
        fallback = fallback or base
        lang = str(track.get("languageCode") or "")
        if lang.startswith("en"):
            english = base
            break
    return english or fallback


def _page_title(page: str) -> str:
    match = re.search(
        r"<title>(.*?)</title>", page or "", flags=re.IGNORECASE | re.DOTALL
    )
    if not match:
        return ""
    title = re.sub(r"\s+", " ", html.unescape(match.group(1))).strip()
    return title[:180]


def html_to_text(page: str) -> tuple[str, str]:
    title = _page_title(page)
    cleaned = re.sub(
        r"(?is)<(script|style|noscript)\b.*?>.*?</\1>",
        " ",
        page or "",
    )
    cleaned = re.sub(r"(?is)<[^>]+>", " ", cleaned)
    text = re.sub(r"\s+", " ", html.unescape(cleaned)).strip()
    return title, text[:20000]


def _http_get(url: str) -> str:
    import httpx

    response = httpx.get(
        url,
        timeout=12.0,
        follow_redirects=True,
        headers={"User-Agent": "OpenJarvisKnowledge/1.0"},
    )
    response.raise_for_status()
    return response.text


def fetch_link(url: str, get: Callable[[str], str] | None = None) -> dict[str, Any]:
    """Read a web page, or a YouTube transcript when captions are published."""
    target = (url or "").strip()
    if not target.startswith(("http://", "https://")):
        raise ValueError("Links must start with http:// or https://")
    getter = get or _http_get
    video = youtube_id(target)
    try:
        if video:
            page = getter(f"https://www.youtube.com/watch?v={video}&hl=en")
        else:
            page = getter(target)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Could not read that link: {exc}") from exc
    if video:
        title = _page_title(page) or f"YouTube {video}"
        title = re.sub(r"\s+-\s+YouTube$", "", title).strip() or title
        track = _caption_url(page)
        text = ""
        if track:
            try:
                raw = getter(track)
            except Exception:
                raw = ""
            text = captions_from_json3(raw) if raw.strip().startswith("{") else ""
            if not text:
                text = captions_from_xml(raw)
        if not text:
            text = (
                "Transcript unavailable. Paste the words from the video "
                "if you want Jarvis to learn them."
            )
        return {"title": title, "text": text, "kind": "video"}
    title, text = html_to_text(page)
    if len(text) < 40:
        raise ValueError("That page did not include readable text.")
    return {"title": title or target, "text": text, "kind": "link"}


def extract_text(name: str, data: bytes) -> str:
    """Read text, Markdown, a Word document, or the text inside a PDF."""
    if data is None:
        raise ValueError("That file was empty.")
    if len(data) > 5_000_000:
        raise ValueError("That file is larger than 5 MB.")
    lower = (name or "").lower()
    if lower.endswith(".docx"):
        text = _docx_text(data)
    elif lower.endswith(".pdf"):
        text = _pdf_text(data)
    else:
        text = data.decode("utf-8", errors="replace")
    text = text.strip()
    if not text:
        raise ValueError("No text could be read from that file.")
    return text[:50000]


def _docx_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
    except (KeyError, zipfile.BadZipFile) as exc:
        raise ValueError("That Word document could not be read.") from exc
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<[^>]+>", "", xml)
    return html.unescape(xml)


def _pdf_text(data: bytes) -> str:
    parts: list[str] = []
    for match in re.finditer(rb"\((?:\\.|[^\\)]){2,}\)", data):
        raw = match.group(0)[1:-1]
        raw = (
            raw.replace(b"\\n", b"\n")
            .replace(b"\\r", b" ")
            .replace(b"\\(", b"(")
            .replace(b"\\)", b")")
        )
        piece = raw.decode("latin-1", errors="ignore").strip()
        if not piece:
            continue
        printable = sum(ch.isprintable() or ch.isspace() for ch in piece)
        if printable >= max(1, int(len(piece) * 0.8)):
            parts.append(piece)
    return "\n".join(parts)


def _unique(lines: list[str]) -> list[str]:
    seen: list[str] = []
    for line in lines:
        cleaned = line.strip()
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    return seen


def distill(title: str, text: str) -> dict[str, Any]:
    """Summarize a lesson and pull out procedures and ideas without a model."""
    clean = (text or "").replace("\r\n", "\n").strip()
    rows = [line.strip(" -\t") for line in clean.splitlines() if line.strip()]
    flat = " ".join(rows) if rows else clean
    sentences = [
        part.strip() for part in re.split(r"(?<=[.!?])\s+", flat) if part.strip()
    ]
    summary = " ".join(sentences[:2])[:480] or (title or flat)[:480]
    lessons: list[str] = []
    sops: list[str] = []
    ideas: list[str] = []
    for line in rows:
        low = line.lower()
        if low.startswith(("sop:", "step ")) or re.match(r"^\d+[.)\]]\s+", line):
            sops.append(line[:240])
        elif low.startswith("idea") or "idea:" in low:
            ideas.append(line[:240])
        elif any(word in low for word in ("lesson", "always", "never ", "remember")):
            lessons.append(line[:240])
    if not lessons:
        lessons = [sentence[:240] for sentence in sentences[:3]]
    heading = (title or summary or "Lesson").strip()
    return {
        "title": heading[:180],
        "summary": summary or heading[:480],
        "lessons": _unique(lessons)[:6],
        "sops": _unique(sops)[:6],
        "ideas": _unique(ideas)[:6],
    }


def _contains(text: str, phrase: str) -> bool:
    if " " in phrase:
        return phrase in text
    return re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text) is not None


def _agent_ids(text: str, explicit: str) -> list[str]:
    if explicit:
        return [explicit]
    found: list[str] = []
    for sid, topics in AGENT_TOPICS.items():
        if any(_contains(text, topic) for topic in topics):
            found.append(sid)
    if "second_brain" not in found:
        found.append("second_brain")
    return found


def _world_score(world: dict[str, Any], text: str) -> int:
    name = (world.get("name") or "").strip().lower()
    score = 0
    for topic in WORLD_TOPICS.get(name, ()):
        if _contains(text, topic):
            score += 2
    if name and name != "personal" and _contains(text, name):
        score += 3
    return score


def route_targets(
    text: str,
    worlds: list[dict[str, Any]],
    *,
    world_id: str = "",
    specialist_id: str = "",
) -> list[dict[str, str]]:
    """Pick worlds and agents. An explicit target wins over the guess."""
    lowered = (text or "").lower()
    explicit_world = bool(world_id)
    if world_id:
        chosen = [world for world in worlds if world.get("id") == world_id]
    else:
        scored = [(world, _world_score(world, lowered)) for world in worlds]
        chosen = [world for world, score in scored if score > 0]
    agents = _agent_ids(lowered, specialist_id)
    general = False
    if not chosen:
        general = any(agent != "second_brain" for agent in agents)
        if general:
            chosen = list(worlds)
        else:
            personal = [
                world
                for world in worlds
                if world.get("kind") == "personal"
                or (world.get("name") or "").strip().lower() == "personal"
            ]
            chosen = personal or worlds[:1]
    routes: list[dict[str, str]] = []
    for world in chosen:
        name = world.get("name") or "this world"
        for agent in agents:
            routes.append(
                {
                    "world_id": str(world.get("id") or ""),
                    "specialist_id": agent,
                    "reason": _reason(
                        name,
                        agent,
                        explicit_world=explicit_world,
                        explicit_agent=bool(specialist_id),
                        general=general,
                    ),
                }
            )
    return routes


def _reason(
    world_name: str,
    specialist_id: str,
    *,
    explicit_world: bool,
    explicit_agent: bool,
    general: bool,
) -> str:
    if explicit_world or explicit_agent:
        return "You chose this destination."
    if general and specialist_id == "marketing_content":
        return "No single business was named, so every marketing agent received it."
    if specialist_id == "marketing_content":
        return f"Content and marketing lessons belong with {world_name}."
    if specialist_id == "executive_assistant":
        return f"Procedures and underwriting belong with {world_name}."
    if specialist_id == "chief_of_staff":
        return f"This changes how the chief works in {world_name}."
    if general:
        return f"No single business was named, so {world_name} kept a copy."
    return f"The second brain keeps this for {world_name}."


def playbook_addition(lessons: list[str], sops: list[str]) -> str:
    """Lines worth proposing as a change to an agent's instructions."""
    lines: list[str] = []
    for sop in sops[:2]:
        cleaned = sop.strip()
        if not cleaned.lower().startswith("sop"):
            cleaned = f"SOP: {cleaned}"
        lines.append(cleaned[:300])
    for lesson in lessons:
        if re.search(r"\balways\b", lesson, flags=re.IGNORECASE):
            lines.append(lesson.strip()[:300])
    return "\n".join(_unique(lines)[:4])


def playbook_owner(specialist_ids: list[str]) -> str:
    for sid in (
        "marketing_content",
        "executive_assistant",
        "chief_of_staff",
        "second_brain",
    ):
        if sid in specialist_ids:
            return sid
    return specialist_ids[0] if specialist_ids else "second_brain"


class KnowledgeFeed:
    """File lessons into scoped memory and hold playbook edits for approval."""

    def __init__(self, office: Any) -> None:
        self.office = office

    def teach(
        self,
        *,
        text: str = "",
        url: str = "",
        title: str = "",
        filename: str = "",
        data: bytes | None = None,
        world_id: str = "",
        specialist_id: str = "",
    ) -> dict[str, Any]:
        kind = "note"
        source = ""
        body = (text or "").strip()
        heading = (title or "").strip()
        if data:
            extracted = extract_text(filename or "upload.txt", data)
            body = f"{body}\n{extracted}".strip() if body else extracted
            kind = "file"
            source = filename or "upload"
        if url:
            fetched = self._read_url(url)
            body = f"{body}\n{fetched['text']}".strip() if body else fetched["text"]
            heading = heading or str(fetched.get("title") or "")
            if kind == "note":
                kind = str(fetched.get("kind") or "link")
            source = source or url.strip()
        if not body:
            raise ValueError("Add a note, a file, or a link.")
        if specialist_id:
            self._known_agent(specialist_id)
        if world_id and self.office.store.get_world(world_id) is None:
            raise ValueError("That world does not exist.")
        distilled = distill(heading, body)
        worlds = self.office.store.list_worlds()
        routes = route_targets(
            f"{distilled['title']}\n{body}",
            worlds,
            world_id=world_id,
            specialist_id=specialist_id,
        )
        if not routes:
            raise ValueError("The chief could not place this anywhere.")
        item = self.office.store.add_knowledge_item(
            title=distilled["title"],
            kind=kind,
            source=source,
            body=body,
            summary=distilled["summary"],
            lessons=distilled["lessons"],
            sops=distilled["sops"],
            ideas=distilled["ideas"],
        )
        self._file_routes(item, routes)
        self._propose(item, routes)
        return self._public(self.office.store.get_knowledge_item(item["id"]))

    def teach_from_phone(self, text: str) -> dict[str, Any] | None:
        if not is_teaching(text):
            return None
        parsed = parse_teaching(text, self.office.store.list_worlds())
        if not parsed["text"] and not parsed["url"]:
            raise ValueError("Add a note or a link after teach.")
        return self.teach(
            text=parsed["text"],
            url=parsed["url"],
            world_id=parsed["world_id"],
            specialist_id=parsed["specialist_id"],
        )

    def teaching_reply(self, item: dict[str, Any]) -> str:
        lines = [item.get("summary") or item.get("title") or "Learned."]
        routes = item.get("routes") or []
        if routes:
            lines.append("")
            lines.append("Routed to:")
            for route in routes:
                lines.append(f"- {route.get('world_name')} · {route.get('agent_name')}")
        return "\n".join(lines)

    def list_items(self, world_id: str = "") -> list[dict[str, Any]]:
        items = []
        for row in self.office.store.list_knowledge_items():
            public = self._public(row)
            if world_id and not any(
                route["world_id"] == world_id for route in public["routes"]
            ):
                continue
            items.append(public)
        return items

    def learned(self, world_id: str = "") -> dict[str, Any]:
        grouped: dict[str, dict[str, Any]] = {}
        for item in self.list_items(world_id):
            for route in item["routes"]:
                if world_id and route["world_id"] != world_id:
                    continue
                bucket = grouped.setdefault(
                    route["world_id"],
                    {
                        "id": route["world_id"],
                        "name": route["world_name"],
                        "agents": {},
                    },
                )
                agent = bucket["agents"].setdefault(
                    route["specialist_id"],
                    {
                        "id": route["specialist_id"],
                        "name": route["agent_name"],
                        "items": [],
                    },
                )
                agent["items"].append(
                    {
                        "id": item["id"],
                        "title": item["title"],
                        "summary": item["summary"],
                        "lessons": item["lessons"],
                        "sops": item["sops"],
                        "ideas": item["ideas"],
                    }
                )
        worlds = []
        for bucket in grouped.values():
            agents = []
            for agent in bucket["agents"].values():
                agent["count"] = len(agent["items"])
                agents.append(agent)
            worlds.append(
                {"id": bucket["id"], "name": bucket["name"], "agents": agents}
            )
        return {"worlds": worlds}

    def lessons_for(
        self, specialist_id: str, world_id: str | None = None
    ) -> list[dict[str, Any]]:
        found = []
        for item in self.list_items(world_id or ""):
            for route in item["routes"]:
                if route["specialist_id"] != specialist_id:
                    continue
                if world_id and route["world_id"] != world_id:
                    continue
                found.append(
                    {
                        "title": item["title"],
                        "summary": item["summary"],
                        "lessons": item["lessons"],
                        "world_id": route["world_id"],
                        "world_name": route["world_name"],
                    }
                )
        return found

    def reroute(
        self, item_id: str, *, world_id: str, specialist_id: str
    ) -> dict[str, Any]:
        item = self.office.store.get_knowledge_item(item_id)
        if item is None or item.get("status") != "active":
            raise KeyError(item_id)
        self._known_agent(specialist_id)
        if self.office.store.get_world(world_id) is None:
            raise ValueError("That world does not exist.")
        self._clear_routes(item_id)
        self._file_routes(
            item,
            [
                {
                    "world_id": world_id,
                    "specialist_id": specialist_id,
                    "reason": "You moved this lesson.",
                }
            ],
        )
        return self._public(self.office.store.get_knowledge_item(item_id))

    def remove(self, item_id: str) -> dict[str, Any]:
        item = self.office.store.get_knowledge_item(item_id)
        if item is None:
            raise KeyError(item_id)
        self._clear_routes(item_id)
        self.office.store.set_knowledge_status(item_id, "removed")
        return {"id": item_id, "removed": True}

    def playbooks(self, status: str = "") -> list[dict[str, Any]]:
        rows = []
        for row in self.office.store.list_playbook_proposals(status):
            rows.append(self._public_playbook(row))
        return rows

    def decide_playbook(self, proposal_id: str, *, approve: bool) -> dict[str, Any]:
        row = self.office.store.get_playbook_proposal(proposal_id)
        if row is None:
            raise KeyError(proposal_id)
        if approve:
            updated = self.office.store.update_team(
                row["world_id"],
                row["specialist_id"],
                brief=row["proposed_brief"],
            )
            if updated is None:
                raise ValueError("That agent is not on this world.")
            status = "approved"
            detail = "The playbook now includes this lesson."
        else:
            status = "rejected"
            detail = "The current playbook was left as it was."
        saved = self.office.store.update_playbook_proposal(
            proposal_id, status=status, detail=detail
        )
        return self._public_playbook(saved)

    def _read_url(self, url: str) -> dict[str, Any]:
        reader = getattr(self.office, "source_reader", None)
        if reader is not None:
            return reader(url)
        return fetch_link(url)

    def _known_agent(self, specialist_id: str) -> None:
        from openjarvis.personal.specialists import get_specialist

        try:
            get_specialist(specialist_id)
        except KeyError as exc:
            raise ValueError("That agent does not exist.") from exc

    def _file_routes(self, item: dict[str, Any], routes: list[dict[str, str]]) -> None:
        note_body = self._memory_body(item)
        for route in routes:
            note = self.office.capture_note(
                item["title"],
                note_body,
                tags="knowledge",
                world_id=route["world_id"],
                specialist_id=route["specialist_id"],
            )
            self.office.store.add_knowledge_route(
                item_id=item["id"],
                world_id=route["world_id"],
                specialist_id=route["specialist_id"],
                note_id=note.get("id") or "",
                memory_id=note.get("memory_id") or "",
                reason=route.get("reason") or "",
            )

    def _memory_body(self, item: dict[str, Any]) -> str:
        lessons = item.get("lessons") or []
        sops = item.get("sops") or []
        parts = [item.get("summary") or ""]
        if lessons:
            parts.append("Lessons:\n" + "\n".join(lessons))
        if sops:
            parts.append("Procedures:\n" + "\n".join(sops))
        return "\n\n".join(part for part in parts if part).strip()

    def _clear_routes(self, item_id: str) -> None:
        for route in self.office.store.list_knowledge_routes(item_id):
            self.office.store.delete_note(route.get("note_id") or "")
            self.office.memory.delete(route.get("memory_id") or "")
        self.office.store.delete_knowledge_routes(item_id)

    def _propose(self, item: dict[str, Any], routes: list[dict[str, str]]) -> None:
        addition = playbook_addition(item.get("lessons") or [], item.get("sops") or [])
        if not addition:
            return
        by_world: dict[str, list[str]] = {}
        for route in routes:
            by_world.setdefault(route["world_id"], []).append(route["specialist_id"])
        for world_id, agents in by_world.items():
            owner = playbook_owner(agents)
            member = next(
                (
                    row
                    for row in self.office.store.team(world_id)
                    if row["specialist_id"] == owner
                ),
                None,
            )
            current = (member or {}).get("brief") or ""
            if addition in current:
                continue
            proposed = f"{current.rstrip()}\n{addition}".strip()
            self.office.store.add_playbook_proposal(
                world_id=world_id,
                specialist_id=owner,
                item_id=item["id"],
                proposed_brief=proposed,
                reason=addition.splitlines()[0][:240],
            )

    def _public(self, item: dict[str, Any] | None) -> dict[str, Any]:
        if item is None:
            raise KeyError("knowledge item")
        names = {
            world["id"]: world["name"] for world in self.office.store.list_worlds()
        }
        routes = []
        for route in self.office.store.list_knowledge_routes(item["id"]):
            routes.append(
                {
                    "id": route["id"],
                    "world_id": route["world_id"],
                    "world_name": names.get(route["world_id"], route["world_id"]),
                    "specialist_id": route["specialist_id"],
                    "agent_name": specialist_name(route["specialist_id"]),
                    "reason": route.get("reason") or "",
                }
            )
        return {
            "id": item["id"],
            "title": item["title"],
            "kind": item["kind"],
            "source": item.get("source") or "",
            "summary": item.get("summary") or "",
            "lessons": item.get("lessons") or [],
            "sops": item.get("sops") or [],
            "ideas": item.get("ideas") or [],
            "status": item.get("status") or "active",
            "created_at": item.get("created_at") or "",
            "routes": routes,
        }

    def _public_playbook(self, row: dict[str, Any] | None) -> dict[str, Any]:
        if row is None:
            raise KeyError("playbook")
        names = {
            world["id"]: world["name"] for world in self.office.store.list_worlds()
        }
        return {
            "id": row["id"],
            "world_id": row["world_id"],
            "world_name": names.get(row["world_id"], row["world_id"]),
            "specialist_id": row["specialist_id"],
            "agent_name": specialist_name(row["specialist_id"]),
            "item_id": row.get("item_id") or "",
            "proposed_brief": row.get("proposed_brief") or "",
            "reason": row.get("reason") or "",
            "status": row.get("status") or "pending",
            "detail": row.get("detail") or "",
            "created_at": row.get("created_at") or "",
        }
