"""Byte-level stdio host for the official Codex SDK's app-server process.

This module forwards JSON-RPC unchanged. It bounds each stdout line before
the SDK's unbounded readline sees it, records stderr, and owns the process
tree. It deliberately does not parse or implement the app-server protocol.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

try:
    from . import processes
except ImportError:  # Executed as an absolute script by the SDK.
    import processes


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise BrokenPipeError("stdio pipe closed")
        view = view[written:]


def _stdin_pump(destination, stop) -> None:
    try:
        while data := os.read(sys.stdin.fileno(), 65536):
            destination.write(data)
    except (BrokenPipeError, OSError):
        pass
    finally:
        # The SDK/backend owns this pipe. EOF means it can no longer receive
        # notifications, so no harness descendant may keep running.
        stop()
        try:
            destination.close()
        except OSError:
            pass


def _stderr_pump(source, path: Path) -> None:
    with path.open("ab", buffering=0) as log:
        while data := os.read(source.fileno(), 65536):
            log.write(data)


def _stdout_pump(source, line_limit: int) -> None:
    line_bytes = 0
    while data := os.read(source.fileno(), 65536):
        for section in data.split(b"\n")[:-1]:
            line_bytes += len(section)
            if line_bytes > line_limit:
                raise ValueError(f"app-server output line exceeds {line_limit} bytes")
            line_bytes = 0
        line_bytes += len(data.rsplit(b"\n", 1)[-1])
        if line_bytes > line_limit:
            raise ValueError(f"app-server output line exceeds {line_limit} bytes")
        _write_all(sys.stdout.fileno(), data)


def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True)
    parser.add_argument("--line-limit", required=True, type=int)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if args.line_limit <= 0 or not command:
        parser.error("positive line limit and command required")
    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    job = None
    if os.name != "nt":
        # Make the host PID the persistent process-group ID recorded on runs.
        # The app-server inherits this group, so restart recovery can killpg
        # the stored host PID even after the app-server leader has exited.
        os.setsid()
    if os.name == "nt":
        proc = subprocess.Popen(
            [sys.executable, processes.__file__, "--lgt-launcher"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=0, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        try:
            job = processes._create_job()
            processes._assign_job(job, proc.pid)
            payload = json.dumps(command, ensure_ascii=False).encode("utf-8")
            proc.stdin.write(len(payload).to_bytes(4, "big") + payload)
        except BaseException:
            if job is not None:
                processes._kernel32.CloseHandle(job)
            proc.kill()
            proc.wait()
            raise
    else:
        proc = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=0,
        )

    stopping = False
    kill_timer = None

    def force_kill():
        try:
            os.killpg(os.getpgrp(), signal.SIGKILL)
        except ProcessLookupError:
            pass

    def stop(_signum=None, _frame=None):
        nonlocal job, stopping, kill_timer
        if stopping:
            return
        stopping = True
        if job is not None:
            processes._kernel32.CloseHandle(job)
            job = None
        elif os.name != "nt":
            try:
                os.killpg(os.getpgrp(), signal.SIGTERM)
            except ProcessLookupError:
                pass
            kill_timer = threading.Timer(1.0, force_kill)
            kill_timer.daemon = True
            kill_timer.start()

    signal.signal(signal.SIGTERM, stop)
    if os.name != "nt":
        signal.signal(signal.SIGINT, stop)
    stdin_thread = threading.Thread(target=_stdin_pump, args=(proc.stdin, stop), daemon=True)
    stderr_thread = threading.Thread(target=_stderr_pump, args=(proc.stderr, log_path), daemon=True)
    stdin_thread.start()
    stderr_thread.start()
    failed = False
    try:
        _stdout_pump(proc.stdout, args.line_limit)
    except (ValueError, BrokenPipeError) as error:
        failed = True
        with log_path.open("ab") as log:
            log.write(f"\nSDK host: {error}\n".encode())
        stop()
    finally:
        if proc.poll() is None:
            stop()
        code = proc.wait()
        stderr_thread.join(timeout=2)
        if kill_timer is not None:
            kill_timer.cancel()
        if job is not None:
            processes._kernel32.CloseHandle(job)
    return 2 if failed else code


if __name__ == "__main__":
    try:
        sys.exit(_main())
    except BaseException as error:
        print(f"SDK host failed: {error}", file=sys.stderr)
        sys.exit(2)
