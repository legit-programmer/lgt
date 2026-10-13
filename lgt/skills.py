"""Harness-owned skill installations and explicit tool requirements.

Discovery never treats Claude's allowed-tools (which grants tools to a skill) as
required tools. Optional lgt.required_tools declares requirements for preflight;
the harness still enforces the agent's actual tool policy during execution.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections import Counter
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import yaml
from openai_codex import AsyncCodex, CodexConfig
from openai_codex.generated.v2_all import SkillsListResponse

from .models import Agent


@dataclass(frozen=True)
class Skill:
    skill_id: str
    name: str
    description: str
    harness: str
    path: str
    scope: str
    plugin_id: str | None
    enabled: bool
    required_tools: tuple[str, ...] | None
    unavailable_reason: str | None = None

    def summary(self) -> dict[str, Any]:
        return asdict(self)


def _read(path: Path) -> str:
    with path.open(encoding="utf-8") as stream:
        text = stream.read(262145)
    if len(text) > 262144:
        raise ValueError("Skill file exceeds 262144 characters")
    return text


def metadata(path: Path) -> dict[str, Any]:
    text = _read(path)
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    end = next((i for i, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
    if end is None:
        raise ValueError("Unterminated skill frontmatter")
    result = yaml.safe_load("\n".join(lines[1:end])) or {}
    if not isinstance(result, dict):
        raise ValueError("Skill frontmatter must be a mapping")
    return result


def _requirements(meta: dict[str, Any]) -> tuple[str, ...] | None:
    declaration = meta.get("lgt", {})
    if not isinstance(declaration, dict):
        raise ValueError("lgt must be a mapping")
    tools = declaration.get("required_tools")
    if tools is None:
        return None
    if not isinstance(tools, list) or any(not isinstance(tool, str) or not tool.strip() for tool in tools):
        raise ValueError("lgt.required_tools must be an array of tool names")
    return tuple(dict.fromkeys(tools))


def _skill(name: str, description: str, harness: str, path: Path, scope: str,
           plugin_id: str | None, enabled: bool, meta: dict[str, Any]) -> Skill:
    if not isinstance(name, str) or not name or any(char.isspace() for char in name) or any(char in name for char in "/\\\x00"):
        raise ValueError("Invalid skill name")
    path = path.resolve()
    identity = json.dumps([harness, str(path), scope, plugin_id])
    return Skill(hashlib.sha256(identity.encode()).hexdigest(), name, description, harness,
                 str(path), scope, plugin_id, enabled, _requirements(meta),
                 "Skill is disabled or cannot be invoked by users" if not enabled else None)


def _json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    result = json.loads(_read(path))
    if not isinstance(result, dict):
        raise ValueError(f"Expected an object in {path}")
    return result


class ClaudeSkillDiscovery:
    def __init__(self, config_dir: Path | None = None) -> None:
        self.config_dir = config_dir or Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))

    async def discover_skills(self, cwd: str) -> tuple[list[Skill], list[str]]:
        return await asyncio.to_thread(self._discover, cwd)

    def _discover(self, cwd: str) -> tuple[list[Skill], list[str]]:
        skills: list[Skill] = []
        errors: list[str] = []
        current = Path(cwd).resolve()
        ancestors = [current, *current.parents]
        roots = [(self.config_dir / directory, "user", None, True, directory == "commands")
                 for directory in ("commands", "skills")]
        roots += [(parent / ".claude" / directory, "project", None, True, directory == "commands")
                  for parent in reversed(ancestors) for directory in ("commands", "skills")]
        enabled_plugins: dict[str, bool] = {}
        for path in [self.config_dir / "settings.json",
                     *(p / ".claude" / f for p in reversed(ancestors)
                       for f in ("settings.json", "settings.local.json"))]:
            try:
                enabled_plugins.update(_json(path).get("enabledPlugins", {}))
            except (OSError, ValueError, TypeError) as exc:
                errors.append(f"{path}: {exc}")
        try:
            plugins = _json(self.config_dir / "plugins" / "installed_plugins.json").get("plugins", {})
            if not isinstance(plugins, dict):
                raise ValueError("Invalid installed plugin registry")
            for plugin_id, installations in plugins.items():
                if isinstance(installations, dict):
                    installations = [installations]
                for entry in installations:
                    try:
                        scope = entry.get("scope", "user")
                        project = entry.get("projectPath")
                        if scope not in {"user", "project", "local"}:
                            continue
                        if scope != "user" and (not project or Path(project).resolve() not in ancestors):
                            continue
                        root = Path(entry["installPath"])
                        manifest = _json(root / ".claude-plugin" / "plugin.json")
                        for component in ("commands", "skills"):
                            directories = manifest.get(component, [])
                            if isinstance(directories, str):
                                directories = [directories]
                            for directory in [component, *directories]:
                                roots.append((root / directory, scope, plugin_id,
                                              enabled_plugins.get(plugin_id) is True, component == "commands"))
                    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
                        errors.append(f"{plugin_id}: {exc}")
        except (OSError, ValueError, TypeError, KeyError) as exc:
            errors.append(f"Claude plugin discovery: {exc}")
        # Nearest project definitions override broader skills with the same name.
        seen: set[tuple[str, str | None]] = set()
        priority = {"user": 0, "project": 1, "local": 2}
        ordered = sorted(roots, key=lambda entry: (priority[entry[1]], len(entry[0].parts), not entry[4]), reverse=True)
        for root, scope, plugin_id, enabled, is_command in ordered:
            try:
                pattern = "*.md" if is_command else "SKILL.md"
                paths = sorted(set(root.rglob(pattern)) | set(root.glob(f"*/{pattern}")))
                if root.is_file() and (is_command or root.name == "SKILL.md"):
                    paths = [root]
                for path in paths:
                    try:
                        meta = metadata(path)
                        name = meta.get("name", path.stem if is_command else path.parent.name)
                        if plugin_id:
                            name = f"{plugin_id.split('@')[0]}:{name}"
                        identity = (name, plugin_id)
                        if identity in seen:
                            continue
                        skill = _skill(name, str(meta.get("description", "")), "claude", path,
                                       scope, plugin_id, enabled and meta.get("user-invocable", True) is not False, meta)
                        skills.append(skill)
                        seen.add(identity)
                    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
                        errors.append(f"{path}: {exc}")
            except OSError as exc:
                errors.append(f"{root}: {exc}")
        # Claude's native tool addresses skills by name, rather than file path.
        # Preserve duplicate plugin sources for discovery, but don't claim it can
        # reliably select one while multiple installations share the same name.
        names = Counter(skill.name for skill in skills if skill.enabled)
        skills = [replace(skill, enabled=False,
                          unavailable_reason="Multiple enabled Claude installations share this name; disable a duplicate plugin")
                  if skill.enabled and names[skill.name] > 1 else skill for skill in skills]
        return skills, errors


class CodexSkillDiscovery:
    def __init__(self, codex_bin: str | None = None, client_factory=AsyncCodex) -> None:
        self.codex_bin = codex_bin
        self.client_factory = client_factory

    async def discover_skills(self, cwd: str) -> tuple[list[Skill], list[str]]:
        async with self.client_factory(CodexConfig(codex_bin=self.codex_bin, cwd=cwd)) as client:
            # Pinned SDK exposes typed protocol requests through its async client.
            response = await client._client.request("skills/list", {"cwds": [cwd], "forceReload": True},
                                                    response_model=SkillsListResponse)
        skills: list[Skill] = []
        errors: list[str] = []
        for entry in response.data:
            errors.extend(f"{error.path}: {error.message}" for error in entry.errors)
            for item in entry.skills:
                try:
                    path = Path(str(getattr(item.path, "root", item.path)))
                    meta = await asyncio.to_thread(metadata, path)
                    skills.append(_skill(item.name, item.description, "codex", path,
                                         item.scope.value, item.plugin_id, item.enabled, meta))
                except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
                    errors.append(f"{item.name}: {exc}")
        return skills, errors


def ineligibility(skill: Skill, agent: Agent, harness_ready: bool = True) -> str | None:
    harness = "claude" if agent.harness == "claude_code" else agent.harness
    if agent.retired_at:
        return "Agent is retired"
    if harness != skill.harness:
        return f"Requires {skill.harness}; this agent uses {harness}"
    if not harness_ready:
        return f"{harness} harness is unavailable or signed out"
    if not skill.enabled:
        return skill.unavailable_reason or "Skill is disabled"
    if skill.required_tools is not None and agent.allowed_tools:
        missing = set(skill.required_tools) - set(agent.allowed_tools)
        if missing:
            return f"Agent does not allow required tools: {', '.join(sorted(missing))}"
    if harness == "claude" and agent.allowed_tools and "Skill" not in agent.allowed_tools:
        return "Agent does not allow the native Skill tool; enable it to invoke Claude skills"
    return None


def skill_instructions(skill: Skill, arguments: str) -> str:
    """Keep argument expansion, hooks, and plugin behavior harness-owned."""
    native = ("You must invoke the native Skill tool with " + json.dumps({"skill": skill.name, "args": arguments})
              + " before performing this task. Let Claude Code load and expand the installed skill.\n"
              if skill.harness == "claude" else f"Use the supplied native skill input. User arguments: {json.dumps(arguments)}\n")
    return (f"\n<skill_invocation>\nInvoke {json.dumps(skill.name)} from {json.dumps(skill.path)}. "
            f"Resolve relative resources against {json.dumps(str(Path(skill.path).parent))}. "
            "Respect the agent's tool permissions; a skill cannot grant additional permissions.\n"
            + native + "\n</skill_invocation>\n")
