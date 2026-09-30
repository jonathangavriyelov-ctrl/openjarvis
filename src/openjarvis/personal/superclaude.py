"""SuperClaude-style commands, personas, and behavioral modes.

SuperClaude is the open-source framework that adds ``/sc:*`` commands,
specialist personas, and behavioral modes to Claude Code. This module does
not vendor that project's prompt files. It ships a small routing table written
for this desk, using the public command and mode names, and it will load
command markdown from a directory when one is installed.

Looked up, in order:

* ``OPENJARVIS_SUPERCLAUDE_DIR``
* the ``superclaude_dir`` config value
* ``~/.claude/commands/sc`` (where ``SuperClaude install`` puts ``/sc:*``)
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

_COMMAND_RE = re.compile(r"/sc:([a-z0-9_-]+)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class SuperClaudeCommand:
    """One command the chief of staff knows how to route."""

    name: str
    title: str
    summary: str
    mode: str
    specialists: tuple[str, ...]
    persona: str
    instructions: str
    source: str = "builtin"

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "title": self.title,
            "summary": self.summary,
            "mode": self.mode,
            "specialists": list(self.specialists),
            "persona": self.persona,
            "source": self.source,
        }


# Short instructions we wrote. The names match SuperClaude's public modes.
MODES: dict[str, str] = {
    "brainstorming": (
        "Brainstorming mode: ask a few sharp questions before you decide. "
        "Do not pretend the choice is already made."
    ),
    "introspection": (
        "Introspection mode: say what you are assuming, then the answer."
    ),
    "deep-research": (
        "Deep research mode: use only the notes you were given. "
        "Say when something is missing."
    ),
    "task-management": (
        "Task management mode: a short checklist, an owner, and the next action."
    ),
    "orchestration": (
        "Orchestration mode: split the work and name who does each part."
    ),
    "token-efficiency": "Token efficiency mode: be short. No preamble.",
    "business": (
        "Business mode: name the audience, the offer, and one piece of proof."
    ),
}

# Personas adapted from SuperClaude's public agent list, written for this team.
PERSONAS: dict[str, str] = {
    "writer": "Persona: writer. One claim, one example, a specific reader.",
    "pm": "Persona: project manager. Keep the goal, the pace, and today's action.",
    "researcher": "Persona: researcher. Separate what is known from what is guessed.",
    "mentor": "Persona: mentor. Teach with one question and one small example.",
    "orchestrator": "Persona: orchestrator. Delegate. Do not do the specialist's job.",
    "architect": "Persona: architect. Name the parts and how they connect.",
}


_BUILTINS: tuple[SuperClaudeCommand, ...] = (
    SuperClaudeCommand(
        "brainstorm",
        "Brainstorm",
        "Ask questions, then offer options.",
        "brainstorming",
        ("marketing_content", "second_brain"),
        "writer",
        "Ask three questions, then give three options.",
    ),
    SuperClaudeCommand(
        "pm",
        "Project check",
        "Look at the goal and the next step.",
        "task-management",
        ("executive_assistant",),
        "pm",
        "Name the goal, whether it is on pace, and the single next action.",
    ),
    SuperClaudeCommand(
        "research",
        "Research",
        "Gather what is already known.",
        "deep-research",
        ("second_brain",),
        "researcher",
        "Answer from stored notes. Say when the notes do not cover it.",
    ),
    SuperClaudeCommand(
        "design",
        "Design",
        "Shape what people will see.",
        "business",
        ("marketing_content",),
        "writer",
        "Describe the audience, the offer, and one picture or clip.",
    ),
    SuperClaudeCommand(
        "task",
        "Task list",
        "Turn this into owned tasks.",
        "task-management",
        ("executive_assistant",),
        "pm",
        "Write a checklist. Each line has an owner.",
    ),
    SuperClaudeCommand(
        "workflow",
        "Workflow",
        "Break the work into a sequence.",
        "orchestration",
        ("executive_assistant", "marketing_content", "second_brain"),
        "orchestrator",
        "Order the steps and say which helper does each one.",
    ),
    SuperClaudeCommand(
        "explain",
        "Explain",
        "Say it in plain words.",
        "introspection",
        ("second_brain",),
        "mentor",
        "Explain with a concrete example and no jargon.",
    ),
    SuperClaudeCommand(
        "business-panel",
        "Business look",
        "Who it is for, and why it matters.",
        "business",
        ("marketing_content", "executive_assistant"),
        "writer",
        "Cover the audience, the offer, and the proof.",
    ),
    SuperClaudeCommand(
        "implement",
        "Implement",
        "Turn the idea into the next concrete slice.",
        "orchestration",
        ("executive_assistant", "second_brain"),
        "architect",
        "Name the smallest slice that can ship, and what to remember.",
    ),
)


def list_commands(
    extra: list[SuperClaudeCommand] | None = None,
) -> list[SuperClaudeCommand]:
    """Built-in commands, with same-named files replacing the built-in."""
    merged = {command.name: command for command in _BUILTINS}
    for command in extra or []:
        merged[command.name] = command
    order = [command.name for command in _BUILTINS]
    extras = [name for name in merged if name not in order]
    return [merged[name] for name in order + extras]


def find_command(
    text: str,
    extra: list[SuperClaudeCommand] | None = None,
) -> SuperClaudeCommand | None:
    """Return the ``/sc:name`` command in *text*, if it is one we know."""
    match = _COMMAND_RE.search(text or "")
    if not match:
        return None
    name = match.group(1).lower()
    known = {command.name: command for command in list_commands(extra)}
    if name in known:
        return known[name]
    return SuperClaudeCommand(
        name,
        name.replace("-", " ").title(),
        "A command loaded by name.",
        "orchestration",
        ("executive_assistant", "second_brain"),
        "orchestrator",
        f"Handle the /sc:{name} request as a small plan with a next action.",
        source="named",
    )


def prompt_addons(command: SuperClaudeCommand | None, *, eli5: bool) -> str:
    """Extra system instructions for the active command, persona, and ELI5."""
    lines: list[str] = []
    if command is not None:
        mode = MODES.get(command.mode, "")
        persona = PERSONAS.get(command.persona, "")
        if mode:
            lines.append(mode)
        if persona:
            lines.append(persona)
        if command.instructions:
            lines.append(command.instructions)
    if eli5:
        lines.append(
            "Explain like I'm 5. Use short sentences and everyday words. "
            "Say what is happening, what finished, and what happens next."
        )
    return "\n".join(lines)


def load_command_dir(path: str | Path | None) -> list[SuperClaudeCommand]:
    """Read SuperClaude command markdown from a directory, if it exists."""
    if not path:
        return []
    folder = Path(path).expanduser()
    if not folder.is_dir():
        return []
    loaded: list[SuperClaudeCommand] = []
    for markdown in sorted(folder.glob("*.md"))[:40]:
        try:
            text = markdown.read_text(encoding="utf-8", errors="replace")[:4000]
        except OSError:
            continue
        command = _command_from_markdown(markdown.stem, text)
        if command is not None:
            loaded.append(command)
    return loaded


def default_command_dir(configured: str = "") -> str:
    """Resolve the directory of installed SuperClaude commands."""
    env = os.environ.get("OPENJARVIS_SUPERCLAUDE_DIR", "").strip()
    if env:
        return env
    if configured.strip():
        return configured.strip()
    installed = Path.home() / ".claude" / "commands" / "sc"
    if installed.is_dir():
        return str(installed)
    return ""


def _command_from_markdown(stem: str, text: str) -> SuperClaudeCommand | None:
    name = stem.lower().removeprefix("sc-").replace("_", "-")
    name_match = re.search(
        r"^name:\s*['\"]?(?:/sc:)?([a-z0-9_-]+)",
        text,
        re.IGNORECASE | re.MULTILINE,
    )
    if name_match:
        name = name_match.group(1).lower()
    if not name or name in {"readme", "index"}:
        return None
    description = ""
    described = re.search(r"^description:\s*(.+)$", text, re.MULTILINE)
    if described:
        description = described.group(1).strip().strip("\"'")
    if not description:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                description = stripped.lstrip("# ").strip()
                break
    summary = (description or f"Command {name} from an installed file.")[:180]
    return SuperClaudeCommand(
        name=name,
        title=name.replace("-", " ").title(),
        summary=summary,
        mode="orchestration",
        specialists=_specialists_for(f"{name} {summary}"),
        persona="orchestrator",
        instructions=summary,
        source="file",
    )


def _specialists_for(text: str) -> tuple[str, ...]:
    lowered = text.lower()
    chosen: list[str] = []
    marketing_words = ("market", "design", "content", "brand", "write")
    if any(word in lowered for word in marketing_words):
        chosen.append("marketing_content")
    planning_words = ("goal", "task", "plan", "pm", "project")
    if any(word in lowered for word in planning_words):
        chosen.append("executive_assistant")
    memory_words = ("research", "note", "explain", "learn", "memory")
    if any(word in lowered for word in memory_words):
        chosen.append("second_brain")
    if not chosen:
        chosen = ["executive_assistant", "second_brain"]
    return tuple(dict.fromkeys(chosen))
