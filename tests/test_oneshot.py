from __future__ import annotations

import sys

import pytest

from lgt.oneshot import CLIOutputLimitError, CLIProcessError, invoke_cli, make_cli_invoker


@pytest.mark.asyncio
async def test_invoke_cli_sends_prompt_and_captures_stdout(tmp_path):
    code = "import sys; sys.stdout.write(sys.stdin.read().upper())"

    output = await invoke_cli(
        [sys.executable, "-c", code],
        str(tmp_path),
        "route this",
        3.0,
        output_limit_bytes=1024,
    )

    assert output == "ROUTE THIS"


@pytest.mark.asyncio
async def test_empty_tool_list_argument_is_preserved(tmp_path):
    output = await invoke_cli(
        [sys.executable, "-c", "import sys; print(repr(sys.argv[1]))", ""],
        str(tmp_path), "", 3.0, output_limit_bytes=1024,
    )
    assert output.strip() == "''"


@pytest.mark.asyncio
async def test_stdout_and_stderr_are_drained_concurrently(tmp_path):
    code = "import sys; sys.stderr.write('e' * 300000); sys.stdout.write('done')"

    output = await invoke_cli(
        [sys.executable, "-c", code],
        str(tmp_path),
        "",
        3.0,
        output_limit_bytes=1024,
    )

    assert output == "done"


@pytest.mark.asyncio
async def test_stdout_limit_is_enforced(tmp_path):
    code = "print('x' * 100)"

    with pytest.raises(CLIOutputLimitError, match="16-byte output limit"):
        await invoke_cli(
            [sys.executable, "-c", code],
            str(tmp_path),
            "",
            3.0,
            output_limit_bytes=16,
        )


@pytest.mark.asyncio
async def test_nonzero_exit_includes_bounded_stderr(tmp_path):
    code = "import sys; sys.stderr.write('bad input'); sys.exit(7)"

    with pytest.raises(CLIProcessError, match="status 7: bad input"):
        await invoke_cli(
            [sys.executable, "-c", code],
            str(tmp_path),
            "",
            3.0,
            output_limit_bytes=1024,
        )


@pytest.mark.asyncio
async def test_timeout_terminates_cli_tree(tmp_path):
    with pytest.raises(TimeoutError, match="timed out"):
        await invoke_cli(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            str(tmp_path),
            "",
            0.1,
            output_limit_bytes=1024,
        )


@pytest.mark.asyncio
async def test_factory_binds_explicit_output_limit(tmp_path):
    invoke = make_cli_invoker(output_limit_bytes=1024)
    code = "import sys; sys.stdout.write(sys.stdin.read())"

    output = await invoke([sys.executable, "-c", code], str(tmp_path), "hello", 3.0)

    assert output == "hello"
