"""Event bus used for Server-Sent Events. In-memory by default, Redis pub/sub optionally."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from autoskill.config import get_settings
from autoskill.db.base import utcnow

log = logging.getLogger(__name__)


@dataclass
class Event:
    channel: str
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    at: str = field(default_factory=lambda: utcnow().isoformat())

    def to_json(self) -> str:
        return json.dumps({"type": self.type, "data": self.data, "at": self.at})


class Subscription:
    """Async iterator over events of one channel. `open()` registers eagerly so events
    published between subscribing and the first read are not lost."""

    async def open(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def __aiter__(self) -> Subscription:
        return self

    async def __anext__(self) -> Event:  # pragma: no cover - interface
        raise NotImplementedError

    async def aclose(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class EventBus:
    async def publish(self, event: Event) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def subscribe(self, channel: str) -> Subscription:  # pragma: no cover - interface
        raise NotImplementedError


class _MemorySubscription(Subscription):
    def __init__(self, bus: MemoryEventBus, channel: str) -> None:
        self._bus, self._channel = bus, channel
        self._queue: asyncio.Queue[Event] = asyncio.Queue()

    async def open(self) -> None:
        self._bus._subscribers[self._channel].add(self._queue)

    async def __anext__(self) -> Event:
        return await self._queue.get()

    async def aclose(self) -> None:
        self._bus._subscribers[self._channel].discard(self._queue)


class MemoryEventBus(EventBus):
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[Event]]] = defaultdict(set)

    async def publish(self, event: Event) -> None:
        for queue in list(self._subscribers.get(event.channel, ())):
            queue.put_nowait(event)

    def subscribe(self, channel: str) -> Subscription:
        return _MemorySubscription(self, channel)


class _RedisSubscription(Subscription):
    def __init__(self, redis_client, channel: str) -> None:
        self._channel = channel
        self._pubsub = redis_client.pubsub()

    async def open(self) -> None:
        await self._pubsub.subscribe(f"autoskill:{self._channel}")

    async def __anext__(self) -> Event:
        while True:
            message = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is None:
                continue
            payload = json.loads(message["data"])
            return Event(channel=self._channel, type=payload["type"], data=payload["data"], at=payload["at"])

    async def aclose(self) -> None:
        await self._pubsub.unsubscribe(f"autoskill:{self._channel}")
        await self._pubsub.close()


class RedisEventBus(EventBus):
    def __init__(self, url: str) -> None:
        import redis.asyncio as redis

        self._redis = redis.from_url(url)

    async def publish(self, event: Event) -> None:
        await self._redis.publish(f"autoskill:{event.channel}", event.to_json())

    def subscribe(self, channel: str) -> Subscription:
        return _RedisSubscription(self._redis, channel)


_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        settings = get_settings()
        _bus = RedisEventBus(settings.redis_url) if settings.events == "redis" else MemoryEventBus()
    return _bus


def reset_event_bus() -> None:
    global _bus
    _bus = None


def user_channel(user_id: str) -> str:
    return f"user:{user_id}"


def project_channel(project_id: str) -> str:
    return f"project:{project_id}"


async def emit(channel: str, type_: str, data: dict[str, Any] | None = None) -> None:
    await get_event_bus().publish(Event(channel=channel, type=type_, data=data or {}))
