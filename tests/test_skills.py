from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openai_codex.generated.v2_all import SkillsListResponse

from lgt.codex_adapter import _turn_input
from lgt.gateway import create_app
from lgt.harnesses import HarnessRegistry
from lgt.models import Agent, WorkspaceError
from lgt.orchestrator import Orchestrator
from lgt.skills import ClaudeSkillDiscovery, CodexSkillDiscovery, _skill, ineligibility, metadata
from lgt.store import Store
from lgt.streaming_adapter import ClaudeRunner
from tests.support import ControlledFactory, FakeRouter, eventually, settings
from tests.test_codex_adapter import sample_turn
from tests.test_gateway import ThreadSafeStore, _with_peer


def install(root: Path, name="review", declaration="lgt:\n  required_tools: [Read]\n", **kwargs):
    path = root / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: {name}\ndescription: |\n  Review code carefully\n{declaration}---\nRead the code.\n", encoding="utf-8")
    return _skill(name, "Review code carefully", kwargs.get("harness", "claude"), path,
                  "user", None, True, metadata(path))


class StaticDiscovery:
    def __init__(self, skills=()):
        self.skills = list(skills)

    async def discover_skills(self, cwd):
        return self.skills, []


def make_registry(tmp_path):
    registry = HarnessRegistry(settings(tmp_path / "data"))
    for entry in registry._catalog:
        if entry["harness"] in {"claude", "codex"}:
            entry["found"] = True
    registry.skill_adapters = {"claude": ClaudeSkillDiscovery(tmp_path / "home"), "codex": StaticDiscovery()}
    return registry


def test_claude_discovery_scope_plugin_settings_and_unknown_permissions(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    child = project / "child"
    child.mkdir(parents=True)
    install(home / "skills", declaration="allowed-tools: Write, Bash\n")
    local = install(child / ".claude" / "skills", name="review", declaration="")
    install(project / ".claude" / "skills", name="review")
    plugin_root = tmp_path / "plugin"
    install(plugin_root / "skills", name="write", declaration="lgt:\n  required_tools: [Write]\n")
    (home / "plugins").mkdir()
    (home / "plugins" / "installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": {
        "tools@market": [{"scope": "user", "installPath": str(plugin_root)}],
        "elsewhere@market": [{"scope": "project", "projectPath": str(tmp_path / "other"), "installPath": str(plugin_root)}],
    }}))
    (home / "settings.json").write_text('{"enabledPlugins":{"tools@market":true}}')
    discovery = ClaudeSkillDiscovery(home)
    skills, errors = discovery._discover(str(child))
    assert not errors
    assert {skill.name for skill in skills} == {"review", "tools:write"}
    assert next(skill for skill in skills if skill.name == "review").path == local.path
    assert next(skill for skill in skills if skill.name == "review").required_tools is None
    plugin = next(skill for skill in skills if skill.name == "tools:write")
    assert plugin.enabled and plugin.plugin_id == "tools@market" and plugin.required_tools == ("Write",)
    (child / ".claude" / "settings.local.json").write_text('{"enabledPlugins":{"tools@market":false}}')
    skills, _ = discovery._discover(str(child))
    assert not next(skill for skill in skills if skill.name == "tools:write").enabled
    # allowed-tools is a grant, not a declaration of required permissions.
    user_skills, _ = discovery._discover(str(tmp_path / "other"))
    assert next(skill for skill in user_skills if skill.name == "review").required_tools is None


@pytest.mark.asyncio
async def test_codex_discovery_uses_native_enabled_inventory_and_provenance(tmp_path):
    skill = install(tmp_path, harness="codex")
    response = SkillsListResponse.model_validate({"data": [{"cwd": str(tmp_path), "errors": [], "skills": [{
        "name": skill.name, "description": skill.description, "path": skill.path,
        "scope": "user", "enabled": False, "pluginId": "tools@market",
    }]}]})
    calls = []
    class Client:
        def __init__(self, config):
            self._client = self
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def request(self, method, params, **kwargs):
            calls.append((method, params))
            return response
    skills, errors = await CodexSkillDiscovery(client_factory=Client).discover_skills(str(tmp_path))
    assert calls == [("skills/list", {"cwds": [str(tmp_path)], "forceReload": True})]
    assert not errors and len(skills) == 1
    assert not skills[0].enabled and skills[0].plugin_id == "tools@market"
    assert skills[0].required_tools == ("Read",)


def test_explicit_write_requirements_and_unknown_requirements(tmp_path):
    skill = install(tmp_path, declaration="lgt:\n  required_tools: [Write]\n")
    reviewer = Agent("a", "a", "A", "", "claude_code", "", "", allowed_tools=["Read", "Skill"])
    assert "Write" in ineligibility(skill, reviewer)
    assert ineligibility(skill, replace(reviewer, allowed_tools=[])) is None
    assert ineligibility(replace(skill, required_tools=None), reviewer) is None
    assert "native Skill tool" in ineligibility(replace(skill, required_tools=None), replace(reviewer, allowed_tools=["Read"]))
    assert "Requires claude" in ineligibility(skill, replace(reviewer, harness="codex"))
    assert "disabled" in ineligibility(replace(skill, enabled=False, unavailable_reason="disabled"), reviewer)


@pytest.fixture
async def workspace(tmp_path):
    registry = make_registry(tmp_path)
    skill = install(tmp_path / "home" / "skills")
    store = Store(tmp_path / "workspace.db")
    factory = ControlledFactory()
    router = FakeRouter(["coder"])
    orch = Orchestrator(store, registry.settings, router, factory, lambda *args: True,
                        human_id="local", harness_registry=registry)
    orch.put_agent(Agent("coder", "coder", "Coder", "", "codex", "", ""))
    orch.put_agent(Agent("reviewer", "reviewer", "Reviewer", "", "claude", "", "", allowed_tools=["Read", "Skill"]))
    orch.put_agent(Agent("editor", "editor", "Editor", "", "claude", "", "", allowed_tools=["Read", "Write", "Skill"]))
    channel = orch.create_channel("skills", agent_ids=["coder", "reviewer"], cwd=str(tmp_path))
    store.set_primary_agent(channel.channel_id, "coder")
    await orch.start()
    yield orch, store, factory, router, channel.channel_id, skill
    await orch.close()
    store.close()


@pytest.mark.asyncio
async def test_channel_recommends_specialist_requires_selection_and_preserves_owner(workspace):
    orch, store, factory, router, cid, skill = workspace
    entry = (await orch.channel_skills(cid))["skills"][0]
    assert entry["status"] == "choose_agent" and entry["recommended_agent_id"] == "reviewer"
    assert entry["default_agent_id"] is None
    before = store.get_channel(cid).next_seq
    with pytest.raises(WorkspaceError, match="Requires claude"):
        await orch.invoke_skill(cid, skill.skill_id)
    assert store.get_channel(cid).next_seq == before
    await orch.invoke_skill(cid, skill.skill_id, "inspect this", "reviewer")
    await eventually(lambda: len(factory.started) == 1)
    turn = factory.started[0].turn
    assert turn.agent.agent_id == "reviewer" and turn.skills[0].skill_id == skill.skill_id
    assert skill.path in turn.prompt and "inspect this" in turn.prompt and "native Skill tool" in turn.prompt
    assert store.get_channel(cid).primary_agent_id == "coder" and not router.calls
    assert next(event for event in store.events(cid) if event.kind == "routing_decision").payload["method"] == "skill"


@pytest.mark.asyncio
async def test_primary_defaults_even_when_multiple_agents_are_eligible(workspace):
    orch, store, factory, _, cid, skill = workspace
    orch.add_member(cid, "editor")
    before = (await orch.channel_skills(cid))["skills"][0]
    assert before["default_agent_id"] is None and before["recommended_agent_id"] is None
    assert before["status"] == "choose_agent"
    store.set_primary_agent(cid, "reviewer")
    entry = (await orch.channel_skills(cid))["skills"][0]
    assert entry["default_agent_id"] == "reviewer" and set(entry["eligible_agent_ids"]) == {"reviewer", "editor"}
    await orch.invoke_skill(cid, skill.skill_id)
    await eventually(lambda: len(factory.started) == 1)
    assert factory.started[0].turn.agent.agent_id == "reviewer"


def test_claude_commands_and_partial_malformed_installations(tmp_path):
    home = tmp_path / "home"
    install(home / "skills", name="valid")
    with pytest.raises(ValueError, match="required_tools"):
        install(home / "skills", name="invalid", declaration="lgt:\n  required_tools: Write\n")
    commands = home / "commands"
    commands.mkdir()
    (commands / "legacy.md").write_text("---\ndescription: Legacy command\n---\nDo $ARGUMENTS.")
    skills, errors = ClaudeSkillDiscovery(home)._discover(str(tmp_path))
    assert {skill.name for skill in skills} == {"valid", "legacy"}
    assert errors and "required_tools" in errors[0]


def test_duplicate_claude_plugin_names_preserve_sources_but_disable_execution(tmp_path):
    home = tmp_path / "home"
    plugin = tmp_path / "plugin"
    install(plugin / "skills", name="review")
    (home / "plugins").mkdir(parents=True)
    (home / "plugins" / "installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": {
        f"tools@{market}": [{"scope": "user", "installPath": str(plugin)}] for market in ("one", "two")
    }}))
    (home / "settings.json").write_text('{"enabledPlugins":{"tools@one":true,"tools@two":true}}')
    skills, errors = ClaudeSkillDiscovery(home)._discover(str(tmp_path))
    assert not errors and len(skills) == 2
    assert len({skill.skill_id for skill in skills}) == 2
    assert all(not skill.enabled and "Multiple enabled" in skill.unavailable_reason for skill in skills)


@pytest.mark.asyncio
async def test_successful_skills_and_ordinary_work_never_coalesce(workspace):
    orch, store, factory, _, cid, skill = workspace
    await orch.send_message(cid, "initial work", ["reviewer"])
    await eventually(lambda: len(factory.started) == 1)
    first = await orch.invoke_skill(cid, skill.skill_id, "first invocation", "reviewer")
    second = await orch.invoke_skill(cid, skill.skill_id, "second invocation", "reviewer")
    third = await orch.send_message(cid, "ordinary follow-up", ["reviewer"])
    for index in range(3):
        factory.started[index].finish()
        await eventually(lambda: len(factory.started) == index + 2)
    assert factory.started[1].turn.delivery_seqs == (first.seq,)
    assert factory.started[2].turn.delivery_seqs == (second.seq,)
    assert factory.started[3].turn.delivery_seqs == (third.seq,)
    assert factory.started[1].turn.skills and factory.started[2].turn.skills
    assert not factory.started[3].turn.skills


@pytest.mark.asyncio
async def test_removed_queued_skill_fails_without_starting_a_harness(workspace):
    orch, store, factory, _, cid, skill = workspace
    await orch.send_message(cid, "initial work", ["reviewer"])
    await eventually(lambda: len(factory.started) == 1)
    await orch.invoke_skill(cid, skill.skill_id, "later", "reviewer")
    Path(skill.path).unlink()
    factory.started[0].finish()
    await eventually(lambda: len(store.list_runs(cid)) == 2 and not store.list_runs(cid, active_only=True))
    assert len(factory.started) == 1
    assert any(run.error and run.error["code"] == "skill_unavailable" for run in store.list_runs(cid))


@pytest.mark.asyncio
async def test_dm_lists_all_harnesses_but_only_its_agent_can_execute(workspace):
    orch, store, factory, _, cid, skill = workspace
    dm = store.get_agent("coder").dm_channel_id
    entry = (await orch.channel_skills(dm))["skills"][0]
    assert entry["status"] == "unavailable" and entry["eligible_agent_ids"] == []
    with pytest.raises(WorkspaceError, match="Requires claude"):
        await orch.invoke_skill(dm, skill.skill_id)
    with pytest.raises(WorkspaceError, match="in this conversation"):
        await orch.invoke_skill(dm, skill.skill_id, agent_id="reviewer")
    original = await orch.send_message(dm, "Keep this history")
    await eventually(lambda: len(factory.started) == 1)
    with pytest.raises(WorkspaceError, match="active runs"):
        orch.put_agent(replace(store.get_agent("coder"), harness="claude"))
    factory.started[0].finish()
    await eventually(lambda: not store.list_runs(dm, active_only=True))
    orch.put_agent(replace(store.get_agent("coder"), harness="claude"))
    await orch.invoke_skill(dm, skill.skill_id)
    await eventually(lambda: len(factory.started) == 2)
    assert factory.started[1].turn.run.session_mode == "cold"
    assert "Keep this history" in factory.started[1].turn.prompt
    assert store.get_event(dm, original.seq).payload["text"] == "Keep this history"


@pytest.mark.asyncio
async def test_permission_gate_outside_agents_raw_slashes_and_list(workspace, tmp_path):
    orch, store, factory, _, cid, _ = workspace
    skill = install(tmp_path / "home" / "skills", "write", "lgt:\n  required_tools: [Write]\n")
    with pytest.raises(WorkspaceError, match="Write"):
        await orch.invoke_skill(cid, skill.skill_id, agent_id="reviewer")
    with pytest.raises(WorkspaceError, match="in this conversation"):
        await orch.invoke_skill(cid, skill.skill_id, agent_id="editor")
    with pytest.raises(WorkspaceError, match="Requires claude"):
        await orch.send_message(cid, "/write")
    with pytest.raises(WorkspaceError, match="exactly one"):
        await orch.send_message(cid, "/write", ["coder", "reviewer"])
    notice = await orch.send_message(cid, "/list")
    assert notice.kind == "system" and notice.payload["code"] == "skills_list"
    assert not factory.started
    orch.add_member(cid, "editor")
    await orch.send_message(cid, "/write update it", ["editor"])
    await eventually(lambda: len(factory.started) == 1)
    assert factory.started[0].turn.agent.agent_id == "editor"
    assert store.get_channel(cid).primary_agent_id == "coder"


@pytest.mark.asyncio
async def test_queue_revalidates_requirements_and_keeps_skills_separate(workspace):
    orch, store, factory, _, cid, skill = workspace
    await orch.send_message(cid, "Ordinary work", ["reviewer"])
    await eventually(lambda: len(factory.started) == 1)
    await orch.invoke_skill(cid, skill.skill_id, "first", "reviewer")
    await orch.invoke_skill(cid, skill.skill_id, "second", "reviewer")
    Path(skill.path).write_text("---\nname: review\nlgt:\n  required_tools: [Write]\n---\nWrite something.")
    factory.started[0].finish()
    await eventually(lambda: len(store.list_runs(cid)) == 3 and not store.list_runs(cid, active_only=True))
    assert len(factory.started) == 1
    failures = [event for event in store.events(cid) if event.kind == "run_status" and event.payload["status"] == "failed"]
    assert len(failures) == 2 and all(event.payload["error"]["code"] == "skill_unavailable" for event in failures)
    assert all(event.payload["skill"]["skill_id"] == skill.skill_id for event in failures)


@pytest.mark.asyncio
async def test_same_named_installations_need_explicit_source_and_partial_errors(workspace):
    orch, store, factory, _, cid, skill = workspace
    codex = replace(skill, skill_id="codex-installation", harness="codex")
    orch.harness_registry.skill_adapters["codex"] = StaticDiscovery([codex])
    catalog = await orch.channel_skills(cid)
    assert len(catalog["skills"]) == 2
    with pytest.raises(WorkspaceError, match="ambiguous"):
        await orch.send_message(cid, "/review")
    await orch.send_message(cid, "/codex:review")
    await eventually(lambda: len(factory.started) == 1)
    assert factory.started[0].turn.skills[0].harness == "codex"
    class Broken:
        async def discover_skills(self, cwd):
            raise RuntimeError("inventory unavailable")
    orch.harness_registry.skill_adapters["codex"] = Broken()
    catalog = await orch.channel_skills(cid)
    assert len(catalog["skills"]) == 1 and catalog["errors"][0]["harness"] == "codex"


def test_native_codex_input_and_claude_runtime_denials(tmp_path):
    skill = install(tmp_path, harness="codex")
    turn = replace(sample_turn(tmp_path), skills=(skill,))
    inputs = _turn_input(turn)
    assert inputs[1].name == skill.name and inputs[1].path == skill.path
    runner = ClaudeRunner(("claude",), tool_output_cap=100, line_limit=1000,
                          cancel_grace_seconds=.1, log_dir=tmp_path)
    terminal = runner.translate({"type": "result", "is_error": False,
                                 "permission_denials": [{"tool_name": "Write"}]})[-1]
    assert terminal.kind == "run_finished" and not terminal.data["ok"]
    assert terminal.data["error"]["code"] == "permission"


@pytest.mark.asyncio
async def test_runtime_permission_failure_keeps_invocation_for_explicit_recovery(workspace):
    orch, store, factory, _, cid, skill = workspace
    await orch.invoke_skill(cid, skill.skill_id, "my arguments", "reviewer")
    await eventually(lambda: len(factory.started) == 1)
    factory.started[0].emit("run_finished", ok=False, error={"code": "permission", "message": "Write was denied"})
    await eventually(lambda: not store.list_runs(cid, active_only=True))
    failed = next(event for event in reversed(store.events(cid)) if event.kind == "run_status")
    assert failed.payload["error"]["code"] == "permission"
    assert failed.payload["skill"]["arguments"] == "my arguments"
    assert store.get_channel(cid).primary_agent_id == "coder"


def test_skill_http_contract_validates_sources_and_targets(tmp_path):
    registry = make_registry(tmp_path)
    skill = install(tmp_path / "home" / "skills")
    store = ThreadSafeStore(tmp_path / "http.db")
    orch = Orchestrator(store, registry.settings, FakeRouter(), ControlledFactory(), lambda *args: True,
                        human_id="local", harness_registry=registry)
    orch.put_agent(Agent("a", "a", "A", "", "claude", "", "", allowed_tools=["Read", "Skill"]))
    cid = store.get_agent("a").dm_channel_id
    orch._pump = lambda *args: None
    with TestClient(_with_peer(create_app(orch)), base_url="http://127.0.0.1") as client:
        assert client.get(f"/channels/{cid}/skills").json()["skills"][0]["default_agent_id"] == "a"
        assert client.get("/channels/missing/skills").status_code == 404
        for body in ({}, {"skill_id": skill.skill_id, "path": skill.path}, {"skill_id": skill.skill_id, "reply_selection": "x"}):
            assert client.post(f"/channels/{cid}/skills/invoke", json=body).status_code == 422
        assert client.post(f"/channels/{cid}/skills/invoke", json={"skill_id": "forged"}).status_code == 400
        response = client.post(f"/channels/{cid}/skills/invoke", json={"skill_id": skill.skill_id, "arguments": "test"})
        assert response.status_code == 201 and response.json()["payload"]["skill"]["harness"] == "claude"
    store.close()
