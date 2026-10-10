"""Authenticated discovery and logging for a desktop-owned background server."""

from __future__ import annotations

import ctypes
import io
import json
import logging
import os
import secrets
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import uvicorn


def _private_file(path: Path) -> None:
    """Protect the token before writing it, including on Windows NTFS."""
    if os.name != "nt":
        path.chmod(0o600)
        return
    from ctypes import wintypes

    api = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    descriptor = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    present, defaulted = wintypes.BOOL(), wintypes.BOOL()
    convert = api.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    convert.restype = wintypes.BOOL
    get_dacl = api.GetSecurityDescriptorDacl
    get_dacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
    get_dacl.restype = wintypes.BOOL
    set_acl = api.SetNamedSecurityInfoW
    set_acl.argtypes = [wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    set_acl.restype = wintypes.DWORD
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    # OWNER RIGHTS follows this file's owner; SYSTEM retains administrative access.
    if not convert("D:P(A;;FA;;;SY)(A;;FA;;;OW)", 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not get_dacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)):
            raise ctypes.WinError(ctypes.get_last_error())
        status = set_acl(str(path), 1, 0x80000004, None, None, dacl, None)
        if status:
            raise ctypes.WinError(status)
    finally:
        kernel.LocalFree(descriptor)


class DaemonState:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "daemon.json"
        self.token = secrets.token_urlsafe(32)
        self.server: uvicorn.Server | None = None

    def publish(self, port: int) -> None:
        descriptor = {
            "pid": os.getpid(), "port": port, "api_version": 1, "token": self.token,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".daemon-{os.getpid()}-{secrets.token_hex(8)}.tmp")
        try:
            # O_EXCL prevents following an existing temporary-file symlink.
            fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                _private_file(temporary)
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    fd = -1
                    json.dump(descriptor, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                if fd != -1:
                    os.close(fd)
        finally:
            temporary.unlink(missing_ok=True)

    def remove(self) -> None:
        try:
            current = json.loads(self.path.read_text(encoding="utf-8"))
            if current.get("pid") == os.getpid() and current.get("token") == self.token:
                self.path.unlink(missing_ok=True)
        except (OSError, ValueError, AttributeError):
            pass

    def request_shutdown(self) -> None:
        if self.server is not None:
            self.server.should_exit = True


class DaemonServer(uvicorn.Server):
    def __init__(self, config: uvicorn.Config, daemon: DaemonState) -> None:
        super().__init__(config)
        self.daemon = daemon
        daemon.server = self

    async def startup(self, sockets: list[Any] | None = None) -> None:
        await super().startup(sockets=sockets)
        if self.started and not self.should_exit:
            port = self.servers[0].sockets[0].getsockname()[1]
            self.daemon.publish(port)

    async def shutdown(self, sockets: list[Any] | None = None) -> None:
        # Reconnection must stop before the runtime releases its single-writer lock.
        self.daemon.remove()
        await super().shutdown(sockets=sockets)


class _LogStream(io.TextIOBase):
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    @property
    def encoding(self) -> str:
        return "utf-8"

    def write(self, text: str) -> int:
        for line in text.splitlines():
            if line.strip():
                self.logger.info("%s", line)
        return len(text)

    def flush(self) -> None:
        for handler in self.logger.handlers:
            handler.flush()


def configure_daemon_logging(data_dir: Path) -> None:
    """Keep logs bounded and redirect Python output away from detached stdio."""
    logs = data_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(logs / "daemon.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [handler]
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
    stream_logger = logging.getLogger("lgt.daemon.output")
    sys.stdout = _LogStream(stream_logger)
    sys.stderr = _LogStream(stream_logger)
