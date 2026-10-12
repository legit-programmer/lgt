from dataclasses import asdict, replace
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from lgt.gateway import create_app
from lgt.harnesses import HarnessRegistry, _claude_reasoning, _codex_model, _model, _validated_model_modes
from lgt.models import Agent, WorkspaceError
from lgt.orchestrator import Orchestrator
from lgt.streaming_adapter import ClaudeRunner, CustomRunner
from tests.support import ControlledFactory, FakeRouter, settings
from tests.test_gateway import ThreadSafeStore, _with_peer


def registry(tmp_path):
    result = HarnessRegistry(settings(tmp_path))
    entry = next(item for item in result._catalog if item['harness'] == 'codex')
    entry['found'] = True
    entry['models'] = [dict(_model('one', 'One', True), reasoning_modes=[
        {'id': 'low', 'label': 'Low', 'description': 'Fast'},
        {'id': 'high', 'label': 'High', 'description': 'Deep'}], default_reasoning_effort='low'), _model('two', 'Two')]
    return result


def test_inference_routes_validate_preserve_and_broadcast(tmp_path):
    store = ThreadSafeStore(tmp_path / 'inference.db')
    catalog = registry(tmp_path)
    orch = Orchestrator(store, settings(tmp_path), FakeRouter(), ControlledFactory(),
                        lambda *args: True, human_id='local', harness_registry=catalog)
    original = Agent('a', 'builder', 'Builder', 'Help', 'codex', 'one', 'Prompt',
                     extra_args=[], avatar={'style': 'critters', 'seed': 'seed'})
    orch.put_agent(original)
    before = store.get_agent('a')
    frames = []
    orch.bus.publish = frames.append
    with TestClient(_with_peer(create_app(orch, manage_lifespan=False)), base_url='http://127.0.0.1') as client:
        models = client.get('/agents/a/models').json()
        assert models == catalog.models_for(before)
        assert models[1]['reasoning_modes'] == []
        assert client.get('/agents/missing/models').status_code == 404
        for body in ({}, {'model': None}, {'harness': 'claude'}, {'provider': 'claude'},
                     {'reasoning_effort': 1}, {'model': ''}):
            assert client.patch('/agents/a/inference', json=body).status_code == 422
        for body in ({'reasoning_effort': 'max'}, {'model': 'unknown'}, {'model': 'two', 'reasoning_effort': 'high'}):
            assert client.patch('/agents/a/inference', json=body).status_code == 400
        response = client.patch('/agents/a/inference', json={'reasoning_effort': 'high'})
        assert response.status_code == 200
        saved = store.get_agent('a')
        assert saved.reasoning_effort == 'high'
        preserved = set(asdict(before)) - {'reasoning_effort', 'updated_at'}
        assert all(asdict(saved)[key] == asdict(before)[key] for key in preserved)
        assert saved.fingerprint() != before.fingerprint()
        assert next(frame for frame in frames if frame['type'] == 'agent')['reasoning_effort'] == 'high'
        assert client.patch('/agents/a/inference', json={'model': 'two'}).json()['reasoning_effort'] is None
        assert client.patch('/agents/a/inference', json={'model': 'one'}).json()['reasoning_effort'] == 'low'
        assert client.patch('/agents/a/inference', json={'reasoning_effort': None}).json()['reasoning_effort'] is None
        store.retire_agent('a')
        assert client.patch('/agents/a/inference', json={'reasoning_effort': 'low'}).status_code == 400
    store.close()


def test_reasoning_persistence_migrates_old_schema(tmp_path):
    import sqlite3
    from pathlib import Path
    from lgt.store import Store
    path = tmp_path / 'old.db'
    schema = Path('lgt/schema.sql').read_text().replace('    reasoning_effort TEXT,\n', '')
    conn = sqlite3.connect(path)
    conn.executescript(schema)
    conn.close()
    store = Store(path)
    original = Agent('a', 'a', 'A', '', 'codex', 'one', '')
    store.put_agent(original)
    assert store.get_agent('a').reasoning_effort is None
    changed = replace(original, reasoning_effort='high')
    store.put_agent(changed)
    store.close()
    store = Store(path)
    assert store.get_agent('a').reasoning_effort == 'high'
    assert original.reasoning_effort is None
    store.close()


def test_codex_catalog_carries_only_model_reported_modes():
    model = NS(model='one', display_name='One', description='Test', is_default=True,
               supported_reasoning_efforts=[NS(reasoning_effort='xhigh', description='Extra depth')],
               default_reasoning_effort='xhigh')
    item = _codex_model(model)
    assert item['reasoning_modes'] == [{'id': 'xhigh', 'label': 'Xhigh', 'description': 'Extra depth'}]
    assert item['default_reasoning_effort'] == 'xhigh'


def test_claude_modes_depend_on_version_and_resolved_model(monkeypatch):
    for key in ('ANTHROPIC_DEFAULT_SONNET_MODEL', 'ANTHROPIC_BASE_URL', 'CLAUDE_CODE_USE_BEDROCK',
                'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY'):
        monkeypatch.delenv(key, raising=False)
    models = [_model('sonnet', 'Test')]
    _claude_reasoning(models, '2.1.295', '--effort low medium high xhigh max')
    assert [mode['id'] for mode in models[0]['reasoning_modes']] == ['low', 'medium', 'high', 'xhigh', 'max']
    monkeypatch.setenv('ANTHROPIC_DEFAULT_SONNET_MODEL', 'claude-sonnet-4-6')
    models = [_model('sonnet', 'Test')]
    _claude_reasoning(models, '2.1.295', '--effort low medium high xhigh max')
    assert 'xhigh' not in [mode['id'] for mode in models[0]['reasoning_modes']]
    monkeypatch.setenv('ANTHROPIC_DEFAULT_SONNET_MODEL', 'claude-sonnet-4-5')
    models = [_model('sonnet', 'Test')]
    _claude_reasoning(models, '2.1.295', '--effort low medium high xhigh max')
    assert models[0]['reasoning_modes'] == []


def test_custom_modes_are_validated_and_optional():
    assert _validated_model_modes(_model('test', 'Test'))['reasoning_modes'] == []
    with pytest.raises(WorkspaceError):
        _validated_model_modes(dict(_model('test', 'Test'), reasoning_modes=[{'id': 'low'}]))
    with pytest.raises(WorkspaceError):
        _validated_model_modes(dict(_model('test', 'Test'), default_reasoning_effort='high'))


@pytest.mark.asyncio
async def test_busy_agent_update_changes_next_run_not_active_snapshot(tmp_path):
    from lgt.store import Store
    store = Store(tmp_path / 'busy.db')
    factory = ControlledFactory()
    orch = Orchestrator(store, settings(tmp_path), FakeRouter(), factory, lambda *args: True,
                        human_id='local', harness_registry=registry(tmp_path))
    orch.put_agent(Agent('a', 'a', 'A', '', 'codex', 'one', '', reasoning_effort='low'))
    await orch.start()
    try:
        channel = store.get_agent('a').dm_channel_id
        await orch.send_message(channel, 'First', [])
        import asyncio
        for _ in range(100):
            if factory.started:
                break
            await asyncio.sleep(.01)
        active = factory.started[0]
        orch.put_agent(replace(store.get_agent('a'), reasoning_effort='high'))
        assert active.turn.agent.reasoning_effort == 'low'
        await orch.send_message(channel, 'Second', [])
        active.finish()
        for _ in range(100):
            if len(factory.started) > 1:
                break
            await asyncio.sleep(.01)
        next_run = factory.started[1]
        assert next_run.turn.agent.reasoning_effort == 'high'
        assert next_run.turn.run.session_mode == 'cold'
        next_run.finish()
    finally:
        await orch.close()
        store.close()


@pytest.mark.parametrize('resume', [False, True])
@pytest.mark.asyncio
async def test_selected_reasoning_reaches_codex_turn(tmp_path, resume):
    from lgt.codex_adapter import CodexAppServerRunner
    from tests.test_codex_adapter import FakeClient, FakeHandle, note, sample_turn
    client = FakeClient(FakeHandle([note('turn/completed', turn=NS(id='t', status='completed'))]))
    runner = CodexAppServerRunner(tool_output_cap=100, line_limit=1000, cancel_grace_seconds=.1,
                                 log_dir=tmp_path, client_factory=lambda _: client)
    turn = sample_turn(tmp_path, resume=resume)
    turn = replace(turn, agent=replace(turn.agent, reasoning_effort='xhigh'))
    events = [event async for event in runner.start(turn)]
    assert events[-1].data['ok']
    assert client.thread.turn_kwargs[1]['effort'] == 'xhigh'


def test_selected_reasoning_reaches_claude_and_custom(tmp_path):
    import json
    from tests.test_harnesses import turn
    sample = turn(tmp_path, 'claude')
    sample = replace(sample, agent=replace(sample.agent, reasoning_effort='high'))
    runner = ClaudeRunner(('claude',), tool_output_cap=100, line_limit=1000, cancel_grace_seconds=.1,
                          log_dir=tmp_path)
    args = runner.argv(sample)
    assert args[args.index('--effort') + 1] == 'high'
    custom = CustomRunner((), tool_output_cap=100, line_limit=1000, cancel_grace_seconds=.1, log_dir=tmp_path)
    assert json.loads(custom.stdin(sample))['reasoning_effort'] == 'high'
