"""Persistent paired-device credentials and per-connection revocation signals."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from collections import defaultdict
from typing import Any

from .store import Store


class DeviceAuth:
    def __init__(self) -> None:
        self._connections: dict[str, set[asyncio.Event]] = defaultdict(set)

    def create(self, store: Store, name: str) -> tuple[dict[str, Any], str]:
        name = name.strip()
        if not name or len(name) > 100 or not name.isprintable():
            raise ValueError("Device name must contain 1–100 printable characters.")
        token = "lgt_device_" + secrets.token_urlsafe(32)
        device = store.create_device(name, hashlib.sha256(token.encode()).hexdigest())
        return device, token

    def authenticate(self, store: Store, token: Any) -> dict[str, Any] | None:
        if not isinstance(token, str) or not token.startswith("lgt_device_") or len(token) > 128:
            return None
        device = store.device_for_credential(hashlib.sha256(token.encode()).hexdigest())
        if device is not None:
            store.touch_device(device["device_id"])
        return device

    def subscribe(self, device_id: str) -> asyncio.Event:
        revoked = asyncio.Event()
        self._connections[device_id].add(revoked)
        return revoked

    def unsubscribe(self, device_id: str, revoked: asyncio.Event) -> None:
        connections = self._connections.get(device_id)
        if connections is not None:
            connections.discard(revoked)
            if not connections:
                self._connections.pop(device_id, None)

    def revoke(self, store: Store, device_id: str) -> dict[str, Any]:
        device = store.revoke_device(device_id)
        for revoked in self._connections.get(device_id, ()):
            revoked.set()
        return device
