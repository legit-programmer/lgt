"""Small catalogs shared by the gateway and workspace bootstrap."""

from __future__ import annotations

from typing import Any


COMMANDS = [
    {"name": "/new", "description": "Start a fresh context in this channel", "usage": "/new"},
    {"name": "/cwd", "description": "Change this channel's working directory", "usage": "/cwd <absolute path>"},
    {"name": "/cancel", "description": "Cancel an active run", "usage": "/cancel [run_id]"},
]


_TEMPLATES = (
    ("coder", "Coder", "Writes and changes code", "You are a careful software engineer. Inspect the project, make focused changes, and verify your work."),
    ("planner", "Planner", "Plans and investigates work", "You are a thoughtful planner. Investigate the problem, identify constraints, and propose concrete next steps."),
    ("docs", "Docs", "Writes clear documentation", "You write accurate, concise documentation grounded in the project and its behavior."),
)


def template_catalog(harnesses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Offer starter agents only for a detected harness and one of its models."""
    preferred = next(
        (item for item in harnesses if item.get("harness") in {"claude", "claude_code"}
         and item.get("found") and item.get("models")),
        None,
    )
    if preferred is None:
        preferred = next((item for item in harnesses if item.get("found") and item.get("models")), None)
    if preferred is None:
        return []
    models = preferred["models"]
    model = next((item for item in models if item.get("default")), models[0])
    tools = {item.get("id") for item in preferred.get("tools", [])}
    can_allow_tools = bool(preferred.get("capabilities", {}).get("allowed_tools"))
    desired = {
        "coder": ["Read", "Grep", "Edit", "Bash"],
        "planner": ["Read", "Grep"],
        "docs": ["Read", "Grep", "Edit"],
    }
    return [
        {
            "id": template_id,
            "name": name,
            "description": description,
            "harness": preferred["harness"],
            "model": model["id"],
            "system_prompt": system_prompt,
            "allowed_tools": [tool for tool in desired[template_id] if tool in tools] if can_allow_tools else [],
        }
        for template_id, name, description, system_prompt in _TEMPLATES
    ]
