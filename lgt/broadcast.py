from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any


@dataclass(eq=False)
class Subscription:
    channel_ids: set[str]
    queue: asyncio.Queue[dict[str, Any]]
    overflowed: bool = False


class EventBus:
    """Fan out live output without making a slow client block an agent."""

    def __init__(self) -> None:
        self._subscriptions: set[Subscription] = set()

    def subscribe(self, channel_ids: set[str], capacity: int) -> Subscription:
        subscription = Subscription(channel_ids, asyncio.Queue(maxsize=capacity))
        self._subscriptions.add(subscription)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        self._subscriptions.discard(subscription)

    def update_channels(self, channel_ids: set[str]) -> None:
        """Refresh subscriptions for the single local human."""
        for subscription in self._subscriptions:
            subscription.channel_ids = set(channel_ids)

    def publish(self, message: dict[str, Any]) -> None:
        channel_id = message.get("channel_id")
        if message["type"] == "event":
            channel_id = message["event"]["channel_id"]
        for subscription in tuple(self._subscriptions):
            if subscription.overflowed or channel_id not in subscription.channel_ids:
                continue
            try:
                subscription.queue.put_nowait(message)
            except asyncio.QueueFull:
                subscription.overflowed = True
                while not subscription.queue.empty():
                    subscription.queue.get_nowait()
                subscription.queue.put_nowait({
                    "type": "resync", "channels": sorted(subscription.channel_ids),
                })
