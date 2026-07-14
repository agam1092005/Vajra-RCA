"""Unified event schema + Apache Kafka event bus.

This is the normalized envelope every heterogeneous signal is mapped into.
In production, it publishes to and consumes from Apache Kafka topics.
If Kafka is offline, it degrades gracefully to in-memory pub/sub.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Callable

from ..core.config import settings

class EventType(str, Enum):
    NETWORK_FLOW = "network_flow"      # a flow record (UNSW / NSL-KDD)
    LOG = "log"                        # a parsed log line (HDFS)
    SECURITY_ALERT = "security_alert"  # labelled attack / signature hit
    METRIC = "metric"                  # a numeric telemetry sample
    CONFIG_CHANGE = "config_change"    # a real config/git change
    ANOMALY = "anomaly"                # output of a detector
    INCIDENT = "incident"             # a correlated incident with RCA


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Event:
    """One normalized signal. `attributes` carries source-specific real fields."""
    event_type: EventType
    source: str                       # e.g. "unsw_nb15", "hdfs", "config_monitor", "isolation_forest"
    node: str                         # entity this event concerns (ip / service / component)
    timestamp: float                  # unix epoch seconds (from the real record where available)
    severity: Severity = Severity.INFO
    confidence: float = 1.0
    signature: str = ""               # short human label ("Exploits attack", "PacketResponder Exception")
    description: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    ingested_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["event_type"] = self.event_type.value
        d["severity"] = self.severity.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Event:
        return cls(
            event_type=EventType(d["event_type"]),
            source=d["source"],
            node=d["node"],
            timestamp=d["timestamp"],
            severity=Severity(d["severity"]),
            confidence=d.get("confidence", 1.0),
            signature=d.get("signature", ""),
            description=d.get("description", ""),
            attributes=d.get("attributes", {}),
            event_id=d.get("event_id", uuid.uuid4().hex),
            ingested_at=d.get("ingested_at", time.time())
        )


Subscriber = Callable[[Event], Any]


class EventBus:
    """Kafka-backed Event Bus with an in-memory queue fallback."""

    def __init__(self, history: int = 5000) -> None:
        self._subscribers: list[Subscriber] = []
        self._queues: list[asyncio.Queue] = []
        self._history: deque[Event] = deque(maxlen=history)
        self._counts: dict[str, int] = defaultdict(int)
        
        self.producer = None
        self.consumer = None
        self._consumer_task: asyncio.Task | None = None
        self._use_kafka = False

    async def start(self) -> None:
        """Start the Kafka producer and consumer loop."""
        try:
            from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
            from ..core.serialize import to_jsonable
            self.producer = AIOKafkaProducer(
                bootstrap_servers=settings.kafka_bootstrap_servers,
                value_serializer=lambda v: json.dumps(to_jsonable(v)).encode('utf-8')
            )
            await self.producer.start()
            
            # Subscribing to all events
            self.consumer = AIOKafkaConsumer(
                "vajra_metrics", "vajra_logs", "vajra_alerts", "vajra_anomalies", "vajra_config_changes",
                bootstrap_servers=settings.kafka_bootstrap_servers,
                group_id="vajra-rca-group",
                auto_offset_reset="latest",
                value_deserializer=lambda v: json.loads(v.decode('utf-8'))
            )
            await self.consumer.start()
            self._use_kafka = True
            self._consumer_task = asyncio.create_task(self._kafka_consumer_loop())
            print("[Kafka] EventBus successfully connected and streaming.")
        except Exception as e:
            print(f"[Kafka] Connection failed: {e}. Falling back to in-memory bus.")
            self._use_kafka = False

    async def stop(self) -> None:
        if self._consumer_task:
            self._consumer_task.cancel()
        if self.consumer:
            await self.consumer.stop()
        if self.producer:
            await self.producer.stop()

    def subscribe(self, callback: Subscriber) -> None:
        """Register a callback invoked for every event (runs in memory)."""
        self._subscribers.append(callback)

    async def publish(self, event: Event) -> None:
        """Publish an event to Kafka or local subscribers."""
        self._history.append(event)
        self._counts[event.event_type.value] += 1

        if self._use_kafka and self.producer:
            topic = f"vajra_{event.event_type.value}s"
            # Map event types to specific topics
            if event.event_type == EventType.NETWORK_FLOW:
                topic = "vajra_metrics"
            elif event.event_type == EventType.LOG:
                topic = "vajra_logs"
            elif event.event_type == EventType.SECURITY_ALERT:
                topic = "vajra_alerts"
            elif event.event_type == EventType.ANOMALY:
                topic = "vajra_anomalies"
            elif event.event_type == EventType.CONFIG_CHANGE:
                topic = "vajra_config_changes"

            try:
                await self.producer.send_and_wait(topic, event.to_dict())
                return  # Consumer loop will dispatch it to subscribers
            except Exception as e:
                print(f"[Kafka] Publish failed: {e}. Dispatching locally.")

        # Local dispatch fallback
        await self._dispatch_local(event)

    async def _dispatch_local(self, event: Event) -> None:
        for cb in self._subscribers:
            res = cb(event)
            if asyncio.iscoroutine(res):
                await res
        for q in self._queues:
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(event)

    async def _kafka_consumer_loop(self) -> None:
        try:
            async for msg in self.consumer:
                try:
                    evt = Event.from_dict(msg.value)
                    await self._dispatch_local(evt)
                except Exception as e:
                    print(f"[Kafka] Error parsing consumed event: {e}")
        except asyncio.CancelledError:
            pass

    async def stream(self, maxsize: int = 1000) -> AsyncIterator[Event]:
        """Yield events as they arrive."""
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._queues.append(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._queues.remove(q)

    def recent(self, event_type: EventType | None = None, limit: int = 500) -> list[Event]:
        items = list(self._history)
        if event_type:
            items = [e for e in items if e.event_type == event_type]
        return items[-limit:]

    @property
    def counts(self) -> dict[str, int]:
        return dict(self._counts)


# Global bus
bus = EventBus()
