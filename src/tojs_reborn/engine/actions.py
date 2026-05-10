from __future__ import annotations

from .events import EventSource, FactEvent
from .resolver import resolve_unit_entered
from .state import GameState, UnitState


def draw_cards(
    state: GameState,
    player_id: str,
    count: int,
    *,
    cause_event_no: int | None = None,
    source: EventSource | None = None,
) -> list[str]:
    player = state.players[player_id]
    drawn: list[str] = []
    for _ in range(count):
        card_instance_id = player.deck.draw_top()
        if card_instance_id is None:
            break
        player.hand.add(card_instance_id)
        drawn.append(card_instance_id)
        instance = state.card_instances[card_instance_id]
        state.event_store.append(
            "card_moved",
            round_no=state.round_no,
            turn_no=state.turn_no,
            actor_player_id=player_id,
            cause_event_no=cause_event_no,
            source=EventSource(
                card_no=instance.card_no,
                card_instance_id=card_instance_id,
            ),
            payload={
                "from_zone": "deck",
                "to_zone": "hand",
                "owner_player_id": player_id,
            },
        )
    state.event_store.append(
        "cards_drawn",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        cause_event_no=cause_event_no,
        source=source or EventSource(),
        payload={
            "count": len(drawn),
            "card_instance_ids": drawn,
        },
    )
    return drawn


def drive_unit(state: GameState, player_id: str, card_instance_id: str) -> UnitState:
    player = state.players[player_id]
    instance = state.card_instances[card_instance_id]
    card = state.card_catalog[instance.card_no]
    if card.category != "unit":
        raise ValueError(f"cannot drive non-unit card: {instance.card_no}")

    action_event = state.event_store.append(
        "action_declared",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        source=EventSource(card_no=instance.card_no, card_instance_id=card_instance_id),
        payload={"action": "drive_unit"},
    )
    player.hand.remove(card_instance_id)
    unit = state.create_unit(card_instance_id)
    player.battlefield.add(unit.unit_id)
    move_event = state.event_store.append(
        "card_moved",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        cause_event_no=action_event.event_no,
        source=EventSource(
            card_no=unit.card_no,
            card_instance_id=card_instance_id,
            unit_id=unit.unit_id,
        ),
        payload={
            "from_zone": "hand",
            "to_zone": "battlefield",
            "owner_player_id": player_id,
        },
    )
    enter_event = state.event_store.append(
        "unit_entered",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        cause_event_no=move_event.event_no,
        source=EventSource(
            card_no=unit.card_no,
            card_instance_id=card_instance_id,
            unit_id=unit.unit_id,
        ),
        payload={"owner_player_id": player_id},
    )
    resolve_unit_entered(state, unit, enter_event, {"draw_cards": _handle_draw_cards})
    return unit


def _handle_draw_cards(
    state: GameState,
    unit: UnitState,
    _ability,
    ability_event: FactEvent,
    step: dict,
) -> None:
    draw_cards(
        state,
        unit.owner_player_id,
        int(step.get("count", 0)),
        cause_event_no=ability_event.event_no,
        source=ability_event.source,
    )
