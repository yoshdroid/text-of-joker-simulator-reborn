from __future__ import annotations

from .events import EventSource
from .rules import MAX_HAND_SIZE, get_unit_bp, opponent_id
from .state import GameState, UnitState


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


def play_joker(state: GameState, player_id: str, card_instance_id: str) -> None:
    if state.turn_player_id != player_id:
        raise ValueError(f"not turn player: {player_id}")
    player = state.players[player_id]
    if card_instance_id not in player.hand.cards:
        raise ValueError(f"joker card is not in hand: {card_instance_id}")
    instance = state.card_instances[card_instance_id]
    if instance.card_no not in state.joker_catalog:
        raise ValueError(f"card is not a joker: {instance.card_no}")
    joker = state.joker_catalog[instance.card_no]
    if player.current_cp < joker.cp:
        raise ValueError(f"not enough CP to play joker: required={joker.cp} current={player.current_cp}")

    action_event = state.event_store.append(
        "action_declared",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        source=EventSource(card_no=instance.card_no, card_instance_id=card_instance_id),
        payload={"action": "play_joker", "card_instance_id": card_instance_id, "joker_no": instance.card_no},
    )
    before_cp = player.current_cp
    player.current_cp -= joker.cp
    state.event_store.append(
        "cp_changed",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        cause_event_no=action_event.event_no,
        source=EventSource(card_no=instance.card_no, card_instance_id=card_instance_id),
        payload={"before_cp": before_cp, "after_cp": player.current_cp, "amount": -joker.cp, "reason": "joker"},
    )
    player.hand.remove(card_instance_id)
    used_event = state.event_store.append(
        "joker_card_used",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        cause_event_no=action_event.event_no,
        source=EventSource(card_no=instance.card_no, card_instance_id=card_instance_id),
        payload={"joker_no": instance.card_no, "card_instance_id": card_instance_id},
    )
    _resolve_joker_effect(state, player_id, instance.card_no, used_event.event_no, card_instance_id)


def _resolve_joker_effect(
    state: GameState,
    player_id: str,
    joker_no: str,
    cause_event_no: int,
    card_instance_id: str,
) -> None:
    if joker_no == "JK-01":
        targets = [state.units[unit_id] for unit_id in state.players[opponent_id(player_id)].battlefield.units if unit_id in state.units]
        for target in targets:
            _deal_joker_damage(state, player_id, target, 5000, cause_event_no=cause_event_no, joker_no=joker_no, card_instance_id=card_instance_id)
        return
    if joker_no == "JK-02":
        _recover_all_own_units(state, player_id, cause_event_no=cause_event_no, joker_no=joker_no, card_instance_id=card_instance_id)
        return
    if joker_no == "JK-03":
        _return_rival_units_to_hand(
            state,
            player_id,
            max_count=2,
            cause_event_no=cause_event_no,
            joker_no=joker_no,
            card_instance_id=card_instance_id,
        )
        return
    _append_joker_effect_fizzled(state, player_id, joker_no, card_instance_id, cause_event_no, "unsupported_joker")


def _append_joker_effect_fizzled(
    state: GameState,
    player_id: str,
    joker_no: str,
    card_instance_id: str,
    cause_event_no: int,
    reason: str,
) -> None:
    state.event_store.append(
        "joker_effect_fizzled",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        cause_event_no=cause_event_no,
        source=EventSource(card_no=joker_no, card_instance_id=card_instance_id),
        payload={"joker_no": joker_no, "reason": reason},
    )


def _recover_all_own_units(
    state: GameState,
    player_id: str,
    *,
    cause_event_no: int,
    joker_no: str,
    card_instance_id: str,
) -> None:
    for unit_id in list(state.players[player_id].battlefield.units):
        unit = state.units.get(unit_id)
        if unit is None or not unit.exhausted:
            continue
        unit.exhausted = False
        state.event_store.append(
            "unit_action_recovered",
            round_no=state.round_no,
            turn_no=state.turn_no,
            actor_player_id=player_id,
            cause_event_no=cause_event_no,
            source=EventSource(card_no=joker_no, card_instance_id=card_instance_id),
            payload={"unit_id": unit.unit_id, "reason": "joker"},
        )


def _return_rival_units_to_hand(
    state: GameState,
    player_id: str,
    *,
    max_count: int,
    cause_event_no: int,
    joker_no: str,
    card_instance_id: str,
) -> None:
    rival_player_id = opponent_id(player_id)
    candidates = [unit_id for unit_id in state.players[rival_player_id].battlefield.units if unit_id in state.units]
    selected_unit_ids = candidates[:max_count]
    if not selected_unit_ids:
        _append_joker_effect_fizzled(state, player_id, joker_no, card_instance_id, cause_event_no, "no_valid_target")
        return
    request_event = state.event_store.append(
        "choice_requested",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        cause_event_no=cause_event_no,
        source=EventSource(card_no=joker_no, card_instance_id=card_instance_id),
        payload={
            "choice_id": "target_units",
            "type": "unit",
            "candidate_unit_ids": candidates,
            "count": min(max_count, len(candidates)),
            "required": True,
        },
    )
    state.event_store.append(
        "choice_selected",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        cause_event_no=request_event.event_no,
        source=EventSource(card_no=joker_no, card_instance_id=card_instance_id),
        payload={
            "choice_id": "target_units",
            "chosen_unit_ids": selected_unit_ids,
            "fallback": "first_legal",
        },
    )
    for unit_id in selected_unit_ids:
        unit = state.units.get(unit_id)
        if unit is not None:
            _return_unit_to_hand(state, player_id, unit, cause_event_no=cause_event_no, joker_no=joker_no, card_instance_id=card_instance_id)


def _return_unit_to_hand(
    state: GameState,
    actor_player_id: str,
    unit: UnitState,
    *,
    cause_event_no: int,
    joker_no: str,
    card_instance_id: str,
) -> None:
    owner = state.players[unit.owner_player_id]
    if unit.unit_id not in owner.battlefield.units:
        return
    owner.battlefield.remove(unit.unit_id)
    instance = state.card_instances[unit.card_instance_id]
    before_level = instance.level
    instance.level = 1
    to_zone = "hand" if len(owner.hand.cards) < MAX_HAND_SIZE else "discard_pile"
    if to_zone == "hand":
        owner.hand.add(unit.card_instance_id)
    else:
        owner.discard_pile.add(unit.card_instance_id)
    state.event_store.append(
        "card_moved",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=unit.owner_player_id,
        cause_event_no=cause_event_no,
        source=EventSource(card_no=unit.card_no, card_instance_id=unit.card_instance_id, unit_id=unit.unit_id),
        payload={
            "from_zone": "battlefield",
            "to_zone": to_zone,
            "owner_player_id": unit.owner_player_id,
            "reason": "joker_return_unit",
            "hand_limit": MAX_HAND_SIZE,
            "hand_limit_exceeded": to_zone == "discard_pile",
            "before_level": before_level,
            "after_level": instance.level,
        },
    )
    state.event_store.append(
        "unit_returned_to_hand",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=actor_player_id,
        cause_event_no=cause_event_no,
        source=EventSource(card_no=joker_no, card_instance_id=card_instance_id),
        payload={
            "target_unit_id": unit.unit_id,
            "target_card_instance_id": unit.card_instance_id,
            "owner_player_id": unit.owner_player_id,
            "to_zone": to_zone,
        },
    )
    del state.units[unit.unit_id]


def _deal_joker_damage(
    state: GameState,
    player_id: str,
    target: UnitState,
    amount: int,
    *,
    cause_event_no: int,
    joker_no: str,
    card_instance_id: str,
) -> None:
    before_damage = target.current_damage
    target.current_damage += amount
    damage_event = state.event_store.append(
        "damage_dealt",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        cause_event_no=cause_event_no,
        source=EventSource(card_no=joker_no, card_instance_id=card_instance_id),
        payload={
            "target_unit_id": target.unit_id,
            "before_damage": before_damage,
            "after_damage": target.current_damage,
            "amount": amount,
            "reason": "joker",
        },
    )
    if target.current_damage >= get_unit_bp(state, target):
        from .combat import destroy_lethal_units

        destroy_lethal_units(state, [target], damage_event.event_no)
