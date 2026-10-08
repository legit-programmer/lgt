"""Run a one-shot CLI prompt without a shell and with bounded output."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from lgt.processes import ProcessTree, spawn_command

_READ_CHUNK_BYTES = 64 * 1024
_ERROR_TEXT_LIMIT = 800


class CLIOutputLimitError(ValueError):
    """A CLI wrote more stdout than the configured capture limit."""


@dataclass(frozen=True)
class CLIProcessError(RuntimeError):
    """A CLI exited unsuccessfully, with a bounded stderr diagnostic."""

    returncode: int
    stderr: str

    def __str__(self) -> str:
        detail = self.stderr.strip()
        return f"CLI exited with status {self.returncode}" + (f": {detail}" if detail else "")


async def _capture(stream: asyncio.StreamReader, limit_bytes: int) -> tuple[bytes, bool]:
    """Drain a pipe fully while retaining at most ``limit_bytes`` bytes."""
    captured = bytearray()
    exceeded = False
    while chunk := await stream.read(_READ_CHUNK_BYTES):
        remaining = limit_bytes - len(captured)
        if remaining > 0:
            captured.extend(chunk[:remaining])
        if len(chunk) > remaining:
            exceeded = True
    return bytes(captured), exceeded


async def _send_prompt(tree: ProcessTree, prompt: str) -> None:
    stream = tree.process.stdin
    if stream is None:
        raise RuntimeError("CLI stdin pipe is unavailable")
    stream.write(prompt.encode("utf-8"))
    try:
        await stream.drain()
    except (BrokenPipeError, ConnectionResetError):
        # A CLI may exit before consuming input; its exit status and stderr
        # below provide the useful failure signal.
        pass
    stream.close()
    try:
        await stream.wait_closed()
    except (BrokenPipeError, ConnectionResetError):
        pass


async def _stop_and_drain(
    tree: ProcessTree,
    tasks: tuple[asyncio.Task[object], ...],
) -> None:
    try:
        await tree.terminate()
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def invoke_cli(
    argv: list[str],
    cwd: str,
    prompt: str,
    timeout_seconds: float,
    *,
    output_limit_bytes: int,
) -> str:
    """Run ``argv`` with ``prompt`` on stdin and return bounded UTF-8 stdout.

    Both output pipes are drained concurrently from process start. The limit is
    applied to captured bytes per stream; extra bytes are drained and discarded
    so children cannot block on a full pipe. The same bound is supplied to the
    process reader as its NDJSON line limit.
    """
    if not argv or not argv[0] or any(not isinstance(part, str) for part in argv):
        raise ValueError("argv must contain strings and a nonempty executable")
    if not cwd:
        raise ValueError("cwd must be nonempty")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if output_limit_bytes <= 0:
        raise ValueError("output_limit_bytes must be positive")

    tree = await spawn_command(argv, cwd, line_limit=output_limit_bytes)
    stdout = tree.process.stdout
    stderr = tree.process.stderr
    if stdout is None or stderr is None:
        await tree.close()
        raise RuntimeError("CLI output pipes are unavailable")

    stdout_task = asyncio.create_task(_capture(stdout, output_limit_bytes))
    stderr_task = asyncio.create_task(_capture(stderr, output_limit_bytes))
    wait_task = asyncio.create_task(tree.process.wait())
    tasks: tuple[asyncio.Task[object], ...] = (
        stdout_task,
        stderr_task,
        wait_task,
    )
    try:
        try:
            async with asyncio.timeout(timeout_seconds):
                await _send_prompt(tree, prompt)
                await asyncio.gather(*tasks)
        except TimeoutError:
            await _stop_and_drain(tree, tasks)
            raise TimeoutError(f"CLI timed out after {timeout_seconds:g} seconds") from None
        except BaseException:
            await _stop_and_drain(tree, tasks)
            raise

        stdout_result, stdout_exceeded = stdout_task.result()
        stderr_result, stderr_exceeded = stderr_task.result()
        returncode = wait_task.result()
        stderr_text = stderr_result.decode("utf-8", errors="replace")
        if stderr_exceeded:
            stderr_text += " …[stderr truncated]"
        if returncode != 0:
            raise CLIProcessError(returncode=returncode, stderr=stderr_text[:_ERROR_TEXT_LIMIT])
        if stdout_exceeded:
            raise CLIOutputLimitError(
                f"CLI stdout exceeded the {output_limit_bytes}-byte output limit",
            )
        return stdout_result.decode("utf-8")
    finally:
        await tree.close()


def make_cli_invoker(*, output_limit_bytes: int):
    """Bind an explicit capture bound into the router/summarizer invoke contract."""

    async def invoke(argv: list[str], cwd: str, prompt: str, timeout: float) -> str:
        return await invoke_cli(
            argv,
            cwd,
            prompt,
            timeout,
            output_limit_bytes=output_limit_bytes,
        )

    return invoke
