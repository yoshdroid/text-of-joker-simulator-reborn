from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EventSource:
    card_no: str | None = None
    card_instance_id: str | None = None
    unit_id: str | None = None
    ability_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_no": self.card_no,
            "card_instance_id": self.card_instance_id,
            "unit_id": self.unit_id,
            "ability_id": self.ability_id,
        }


@dataclass(frozen=True)
class FactEvent:
    event_no: int
    type: str
    round_no: int
    turn_no: int
    actor_player_id: str | None
    cause_event_no: int | None = None
    source: EventSource = field(default_factory=EventSource)
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_no": self.event_no,
            "type": self.type,
            "round_no": self.round_no,
            "turn_no": self.turn_no,
            "actor_player_id": self.actor_player_id,
            "cause_event_no": self.cause_event_no,
            "source": self.source.to_dict(),
            "payload": self.payload,
        }


class EventStore:
    def __init__(self) -> None:
        self._events: list[FactEvent] = []
        self._next_event_no = 1

    @property
    def events(self) -> tuple[FactEvent, ...]:
        return tuple(self._events)

    def append(
        self,
        event_type: str,
        *,
        round_no: int,
        turn_no: int,
        actor_player_id: str | None,
        source: EventSource | None = None,
        payload: dict[str, Any] | None = None,
        cause_event_no: int | None = None,
    ) -> FactEvent:
        event = FactEvent(
            event_no=self._next_event_no,
            type=event_type,
            round_no=round_no,
            turn_no=turn_no,
            actor_player_id=actor_player_id,
            cause_event_no=cause_event_no,
            source=source or EventSource(),
            payload=payload or {},
        )
        self._events.append(event)
        self._next_event_no += 1
        return event

    def to_list(self) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self._events]

