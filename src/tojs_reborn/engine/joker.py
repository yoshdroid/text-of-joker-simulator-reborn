from __future__ import annotations

from .events import EventSource
from .rules import MAX_HAND_SIZE
from .state import GameState


JOKER_TURN_END_GAIN_MULTIPLIER = 4
JOKER_LIFE_DAMAGE_GAIN = 10


def gain_joker_gauge(
    state: GameState,
    player_id: str,
    amount: int,
    *,
    cause_event_no: int | None = None,
    reason: str,
) -> None:
    if amount <= 0:
        return
    player = state.players[player_id]
    if player.joker_granted:
        return
    before_gauge = player.joker_gauge
    after_gauge = min(100, before_gauge + amount)
    if after_gauge == before_gauge:
        return
    player.joker_gauge = after_gauge
    state.event_store.append(
        "joker_gauge_changed",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        cause_event_no=cause_event_no,
        source=EventSource(),
        payload={
            "player_id": player_id,
            "before_gauge": before_gauge,
            "after_gauge": after_gauge,
            "amount": after_gauge - before_gauge,
            "reason": reason,
        },
    )


def gain_joker_gauge_for_turn_end(state: GameState, player_id: str, *, cause_event_no: int) -> None:
    joker = state.joker_catalog[state.players[player_id].joker_no]
    gain_joker_gauge(
        state,
        player_id,
        JOKER_TURN_END_GAIN_MULTIPLIER * joker.speed,
        cause_event_no=cause_event_no,
        reason="turn_end",
    )


def gain_joker_gauge_for_life_loss(state: GameState, player_id: str, life_loss: int, *, cause_event_no: int) -> None:
    gain_joker_gauge(
        state,
        player_id,
        JOKER_LIFE_DAMAGE_GAIN * life_loss,
        cause_event_no=cause_event_no,
        reason="life_loss",
    )


def try_grant_joker(state: GameState, player_id: str, *, cause_event_no: int | None = None) -> bool:
    player = state.players[player_id]
    if player.joker_granted or player.joker_gauge < 100 or state.turn_player_id != player_id:
        return False
    if len(player.hand.cards) >= MAX_HAND_SIZE:
        return False
    joker_no = player.joker_no
    if joker_no not in state.joker_catalog:
        raise ValueError(f"unknown joker_no: {joker_no}")
    instance = state.create_card_instance(joker_no, player_id)
    player.hand.add(instance.instance_id)
    before_gauge = player.joker_gauge
    player.joker_gauge = 0
    player.joker_granted = True
    state.event_store.append(
        "joker_card_granted",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        cause_event_no=cause_event_no,
        source=EventSource(card_no=joker_no, card_instance_id=instance.instance_id),
        payload={
            "player_id": player_id,
            "joker_no": joker_no,
            "card_instance_id": instance.instance_id,
            "before_gauge": before_gauge,
            "after_gauge": 0,
        },
    )
    return True
