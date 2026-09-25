"""Personal AI OS — chief of staff, specialist team, goals, and memory.

This package composes OpenJarvis primitives (workflow engine, A2A tasks,
skills, the scheduler, and the memory backend) into Jonathan's local
operating picture. It does not replace the chat, voice, or managed-agent
runtime.
"""

from openjarvis.personal.hermes import ModelChoice, resolve_executive_model
from openjarvis.personal.office import PersonalOffice
from openjarvis.personal.specialists import (
    get_specialist,
    list_specialists,
    register_specialist,
    unregister_specialist,
)

__all__ = [
    "ModelChoice",
    "PersonalOffice",
    "get_specialist",
    "list_specialists",
    "register_specialist",
    "resolve_executive_model",
    "unregister_specialist",
]
