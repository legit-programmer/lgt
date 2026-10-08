from __future__ import annotations

import asyncio
import os
import subprocess
import sys

import pytest

from lgt.processes import read_lines, spawn_command


@pytest.mark.asyncio
async def test_process_pipes_and_lines(tmp_path):
    tree = await spawn_command(
        [sys.executable, "-c", "import sys; sys.stdout.write('one\\ntwo\\n'); sys.stderr.write('warning\\n')"],
        str(tmp_path), env={**os.environ, "PYTHONIOENCODING": "utf-8"}, line_limit=100,
    )
    try:
        assert [line async for line in read_lines(tree.process.stdout, 100)] == ["one", "two"]
        assert (await tree.process.stderr.read()).splitlines() == [b"warning"]
        assert await tree.process.wait() == 0
    finally:
        await tree.close()


@pytest.mark.asyncio
async def test_launcher_forwards_stdin_and_arguments(tmp_path):
    tree = await spawn_command(
        [sys.executable, "-c", "import sys; print(sys.argv[1] + sys.stdin.read())", "héllo world "],
        str(tmp_path), env={**os.environ, "PYTHONIOENCODING": "utf-8"}, line_limit=100,
    )
    try:
        tree.process.stdin.write("κόσμε".encode("utf-8"))
        await tree.process.stdin.drain()
        tree.process.stdin.close()
        assert [line async for line in read_lines(tree.process.stdout, 100)] == ["héllo world κόσμε"]
        assert await tree.process.wait() == 0
    finally:
        await tree.close()


@pytest.mark.asyncio
async def test_rejects_oversized_line(tmp_path):
    tree = await spawn_command(
        [sys.executable, "-c", "print('x' * 100)"], str(tmp_path), line_limit=32,
    )
    try:
        with pytest.raises(ValueError, match="exceeds 32 bytes"):
            _ = [line async for line in read_lines(tree.process.stdout, 32)]
    finally:
        await tree.close()


@pytest.mark.asyncio
async def test_terminates_child_tree(tmp_path):
    child_code = "import time; time.sleep(60)"
    parent_code = (
        "import subprocess,sys,time; "
        f"p=subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        "print(p.pid, flush=True); time.sleep(60)"
    )
    tree = await spawn_command([sys.executable, "-c", parent_code], str(tmp_path), line_limit=100)
    try:
        child_pid = int(await asyncio.wait_for(tree.process.stdout.readline(), 5))
        await tree.terminate(grace_seconds=0.2)
        assert tree.process.returncode is not None
        if os.name == "nt":
            # tasklist has a different PID reuse risk, but this runs immediately.
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {child_pid}", "/FO", "CSV"],
                capture_output=True, text=True, check=True,
            )
            assert f'"{child_pid}"' not in result.stdout
        else:
            with pytest.raises(ProcessLookupError):
                os.kill(child_pid, 0)
    finally:
        await tree.close()


@pytest.mark.skipif(os.name == "nt", reason="POSIX process group regression")
@pytest.mark.asyncio
async def test_close_kills_child_after_leader_exits(tmp_path):
    parent_code = (
        "import subprocess,sys; "
        "p=subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(60)']); "
        "print(p.pid, flush=True)"
    )
    tree = await spawn_command([sys.executable, "-c", parent_code], str(tmp_path), line_limit=100)
    child_pid = int(await asyncio.wait_for(tree.process.stdout.readline(), 5))
    await asyncio.wait_for(tree.process.wait(), 5)
    await tree.terminate(grace_seconds=0.1)
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)
