"""Spawn CLI harnesses and manage the entire child process tree."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
from collections.abc import AsyncIterator


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _SIZE_T = ctypes.c_size_t
    _ULONG_PTR = ctypes.c_size_t

    class _BasicLimits(ctypes.Structure):
        _fields_ = [
            ("per_process_time", ctypes.c_int64),
            ("per_job_time", ctypes.c_int64),
            ("flags", wintypes.DWORD),
            ("minimum_working_set", _SIZE_T),
            ("maximum_working_set", _SIZE_T),
            ("active_process_limit", wintypes.DWORD),
            ("affinity", _ULONG_PTR),
            ("priority_class", wintypes.DWORD),
            ("scheduling_class", wintypes.DWORD),
        ]

    class _IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in (
            "read_operation_count", "write_operation_count", "other_operation_count",
            "read_transfer_count", "write_transfer_count", "other_transfer_count",
        )]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("basic", _BasicLimits),
            ("io", _IoCounters),
            ("process_memory_limit", _SIZE_T),
            ("job_memory_limit", _SIZE_T),
            ("peak_process_memory_used", _SIZE_T),
            ("peak_job_memory_used", _SIZE_T),
        ]

    class _Accounting(ctypes.Structure):
        _fields_ = [
            ("user_time", ctypes.c_int64), ("kernel_time", ctypes.c_int64),
            ("period_user_time", ctypes.c_int64), ("period_kernel_time", ctypes.c_int64),
            ("page_faults", wintypes.DWORD), ("total_processes", wintypes.DWORD),
            ("active_processes", wintypes.DWORD), ("terminated_processes", wintypes.DWORD),
        ]

    _kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.SetInformationJobObject.argtypes = (
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
    )
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.QueryInformationJobObject.argtypes = (
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
    )
    _kernel32.QueryInformationJobObject.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _kernel32.CloseHandle.restype = wintypes.BOOL

    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    _PROCESS_TERMINATE = 0x0001
    _PROCESS_SET_QUOTA = 0x0100


def _win_error() -> OSError:
    return ctypes.WinError(ctypes.get_last_error())


def _create_job() -> int:
    job = _kernel32.CreateJobObjectW(None, None)
    if not job:
        raise _win_error()
    limits = _ExtendedLimits()
    limits.basic.flags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not _kernel32.SetInformationJobObject(
        job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(limits), ctypes.sizeof(limits),
    ):
        error = _win_error()
        _kernel32.CloseHandle(job)
        raise error
    return job


def _assign_job(job: int, pid: int) -> None:
    process = _kernel32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
    if not process:
        raise _win_error()
    try:
        if not _kernel32.AssignProcessToJobObject(job, process):
            raise _win_error()
    finally:
        _kernel32.CloseHandle(process)


def _job_active_processes(job: int) -> int:
    accounting = _Accounting()
    if not _kernel32.QueryInformationJobObject(
        job, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None,
    ):
        raise _win_error()
    return accounting.active_processes


class ProcessTree:
    """An asyncio subprocess whose descendants are terminated with it."""

    def __init__(self, process: asyncio.subprocess.Process, job: int | None = None) -> None:
        self.process = process
        self.pid = process.pid
        self._job = job

    async def terminate(self, grace_seconds: float = 5.0) -> None:
        if os.name == "nt":
            # Windows has no SIGTERM for a process group. TerminateJobObject
            # reliably stops descendants; a grace period cannot be guaranteed.
            if self._job is not None:
                _kernel32.TerminateJobObject(self._job, 1)
            elif self.process.returncode is None:
                self.process.kill()
        else:
            # Descendants can outlive the leader and keep its stdio pipes open.
            # Signal the group even when asyncio already reaped the leader.
            try:
                os.killpg(self.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            loop = asyncio.get_running_loop()
            deadline = loop.time() + grace_seconds
            while loop.time() < deadline:
                try:
                    os.killpg(self.pid, 0)
                except ProcessLookupError:
                    break
                await asyncio.sleep(min(0.05, max(0, deadline - loop.time())))
            else:
                # A process group containing only zombies may still report as
                # present; SIGKILL is harmless in that case.
                try:
                    os.killpg(self.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        await self.process.wait()
        if os.name == "nt" and self._job is not None:
            # The launcher can be reaped before its children release files.
            # Wait for the whole Job Object to empty before reporting success.
            async with asyncio.timeout(max(1.0, grace_seconds)):
                while _job_active_processes(self._job):
                    await asyncio.sleep(0.01)

    async def close(self) -> None:
        if self.process.returncode is None or os.name != "nt" or self._job is not None:
            await self.terminate()
        if self._job is not None:
            _kernel32.CloseHandle(self._job)
            self._job = None


async def spawn_command(
    argv: list[str], cwd: str, env: dict[str, str] | None = None, *, line_limit: int,
) -> ProcessTree:
    """Start a CLI, with stdin/stdout/stderr pipes and tree cancellation.

    ``line_limit`` is applied by :func:`read_lines`; the StreamReader's own
    limit is raised to avoid a smaller implicit cap.
    """
    if not argv or line_limit <= 0:
        raise ValueError("argv must be nonempty and line_limit must be positive")
    kwargs: dict[str, object] = {
        "cwd": cwd,
        "env": env,
        "stdin": asyncio.subprocess.PIPE,
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
        "limit": max(line_limit + 1, 65536),
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    if os.name == "nt":
        # The launcher blocks on stdin until it has joined our Job Object.
        # Its eventual child inherits the job, closing the usual spawn/assign
        # race without needing CREATE_SUSPENDED or private asyncio handles.
        command = [sys.executable, os.path.abspath(__file__), "--lgt-launcher"]
    else:
        command = argv
    process = await asyncio.create_subprocess_exec(*command, **kwargs)
    if os.name != "nt":
        return ProcessTree(process)
    job = None
    try:
        job = _create_job()
        _assign_job(job, process.pid)
        launch_bytes = json.dumps(argv, ensure_ascii=False).encode("utf-8")
        process.stdin.write(len(launch_bytes).to_bytes(4, "big") + launch_bytes)
        await process.stdin.drain()
        return ProcessTree(process, job)
    except BaseException:
        if job is not None:
            _kernel32.CloseHandle(job)
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise


async def read_lines(stream: asyncio.StreamReader, line_limit: int) -> AsyncIterator[str]:
    """Read UTF-8 NDJSON lines while rejecting a line over ``line_limit`` bytes."""
    if line_limit <= 0:
        raise ValueError("line_limit must be positive")
    pending = bytearray()
    while chunk := await stream.read(65536):
        for segment in chunk.split(b"\n")[:-1]:
            if len(pending) + len(segment) > line_limit:
                raise ValueError(f"NDJSON line exceeds {line_limit} bytes")
            pending.extend(segment)
            yield pending.removesuffix(b"\r").decode("utf-8")
            pending.clear()
        tail = chunk.rsplit(b"\n", 1)[-1]
        if len(pending) + len(tail) > line_limit:
            raise ValueError(f"NDJSON line exceeds {line_limit} bytes")
        pending.extend(tail)
    if pending:
        yield pending.removesuffix(b"\r").decode("utf-8")


def _windows_launcher() -> int:
    """Wait for Job assignment, then run the real CLI with inherited pipes."""
    size_bytes = bytearray()
    while len(size_bytes) < 4:
        chunk = os.read(sys.stdin.fileno(), 4 - len(size_bytes))
        if not chunk:
            return 2
        size_bytes.extend(chunk)
    remaining = int.from_bytes(size_bytes, "big")
    if remaining <= 0 or remaining > 1024 * 1024:
        return 2
    payload = bytearray()
    while remaining:
        chunk = os.read(sys.stdin.fileno(), remaining)
        if not chunk:
            return 2
        payload.extend(chunk)
        remaining -= len(chunk)
    argv = json.loads(payload)
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
        return 2
    with subprocess.Popen(
        argv,
        stdin=sys.stdin.buffer,
        stdout=sys.stdout.buffer,
        stderr=sys.stderr.buffer,
    ) as child:
        return child.wait()


if __name__ == "__main__" and os.name == "nt" and sys.argv[1:] == ["--lgt-launcher"]:
    try:
        sys.exit(_windows_launcher())
    except Exception as error:
        print(f"Process launcher failed: {error}", file=sys.stderr)
        sys.exit(2)
