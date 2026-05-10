from __future__ import annotations

from .actions import get_effect_handlers
from .events import EventSource
from .rules import get_unit_bp, opponent_id
from .resolver import resolve_unit_attacked, resolve_unit_blocked, resolve_unit_destroyed
from .state import GameState, UnitState


def attack_player(state: GameState, player_id: str, attacker_unit_id: str) -> None:
    attacker = _get_owned_unit(state, player_id, attacker_unit_id)
    action_event = _declare_attack(state, player_id, attacker)
    resolve_unit_attacked(state, attacker, action_event, get_effect_handlers())
    opponent = state.players[opponent_id(player_id)]
    before_life = opponent.life
    opponent.life -= 1
    state.event_store.append(
        "life_changed",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        cause_event_no=action_event.event_no,
        source=_unit_source(attacker),
        payload={
            "player_id": opponent.player_id,
            "before_life": before_life,
            "after_life": opponent.life,
            "amount": -1,
            "reason": "player_attack",
        },
    )


def attack_unit(state: GameState, player_id: str, attacker_unit_id: str, blocker_unit_id: str) -> None:
    attacker = _get_owned_unit(state, player_id, attacker_unit_id)
    blocker = _get_owned_unit(state, opponent_id(player_id), blocker_unit_id)
    action_event = _declare_attack(state, player_id, attacker)
    resolve_unit_attacked(state, attacker, action_event, get_effect_handlers())
    block_event = declare_block(state, opponent_id(player_id), blocker.unit_id, attacker.unit_id, action_event.event_no)
    resolve_unit_blocked(state, blocker, block_event, get_effect_handlers())
    battle_event = state.event_store.append(
        "battle_started",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        cause_event_no=action_event.event_no,
        source=_unit_source(attacker),
        payload={"attacker_unit_id": attacker.unit_id, "blocker_unit_id": blocker.unit_id},
    )
    _deal_battle_damage(state, attacker, blocker, battle_event.event_no)
    _deal_battle_damage(state, blocker, attacker, battle_event.event_no)
    _emit_battle_result(state, attacker, blocker, battle_event.event_no)
    destroy_lethal_units(state, [attacker, blocker], battle_event.event_no)


def declare_block(
    state: GameState,
    player_id: str,
    blocker_unit_id: str,
    attacker_unit_id: str,
    cause_event_no: int,
):
    blocker = _get_owned_unit(state, player_id, blocker_unit_id)
    return state.event_store.append(
        "block_declared",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        cause_event_no=cause_event_no,
        source=_unit_source(blocker),
        payload={"blocker_unit_id": blocker_unit_id, "attacker_unit_id": attacker_unit_id},
    )


def _declare_attack(state: GameState, player_id: str, attacker: UnitState):
    if state.turn_player_id != player_id:
        raise ValueError(f"not turn player: {player_id}")
    if attacker.exhausted:
        raise ValueError(f"unit already exhausted: {attacker.unit_id}")
    action_event = state.event_store.append(
        "action_declared",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        source=_unit_source(attacker),
        payload={"action": "attack", "attacker_unit_id": attacker.unit_id},
    )
    attacker.exhausted = True
    state.event_store.append(
        "unit_attacked",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        cause_event_no=action_event.event_no,
        source=_unit_source(attacker),
        payload={"attacker_unit_id": attacker.unit_id},
    )
    return action_event


def _deal_battle_damage(state: GameState, source: UnitState, target: UnitState, cause_event_no: int) -> None:
    amount = get_unit_bp(state, source)
    before_damage = target.current_damage
    target.current_damage += amount
    state.event_store.append(
        "damage_dealt",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=source.owner_player_id,
        cause_event_no=cause_event_no,
        source=_unit_source(source),
        payload={
            "target_unit_id": target.unit_id,
            "before_damage": before_damage,
            "after_damage": target.current_damage,
            "amount": amount,
        },
    )


def destroy_lethal_units(state: GameState, units: list[UnitState], cause_event_no: int) -> None:
    destroyed_units = [
        unit
        for unit in units
        if unit.unit_id in state.units and unit.current_damage >= get_unit_bp(state, unit)
    ]
    battlefield_order = _battlefield_order(state)
    destroyed_units.sort(
        key=lambda unit: (
            0 if unit.owner_player_id == state.turn_player_id else 1,
            battlefield_order.get(unit.unit_id, 9999),
        )
    )
    for unit in destroyed_units:
        _destroy_unit(state, unit, cause_event_no)


def _destroy_unit(state: GameState, unit: UnitState, cause_event_no: int) -> None:
    player = state.players[unit.owner_player_id]
    player.battlefield.remove(unit.unit_id)
    player.discard_pile.add(unit.card_instance_id)
    state.event_store.append(
        "card_moved",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=unit.owner_player_id,
        cause_event_no=cause_event_no,
        source=_unit_source(unit),
        payload={
            "from_zone": "battlefield",
            "to_zone": "discard_pile",
            "owner_player_id": unit.owner_player_id,
        },
    )
    destroyed_event = state.event_store.append(
        "unit_destroyed",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=unit.owner_player_id,
        cause_event_no=cause_event_no,
        source=_unit_source(unit),
        payload={"reason": "battle"},
    )
    resolve_unit_destroyed(state, unit, destroyed_event, get_effect_handlers())
    del state.units[unit.unit_id]


def _emit_battle_result(state: GameState, attacker: UnitState, blocker: UnitState, cause_event_no: int) -> None:
    attacker_lethal = attacker.current_damage >= get_unit_bp(state, attacker)
    blocker_lethal = blocker.current_damage >= get_unit_bp(state, blocker)
    if attacker_lethal and blocker_lethal:
        result_type = "battle_draw"
    elif blocker_lethal:
        result_type = "battle_won"
    elif attacker_lethal:
        result_type = "battle_lost"
    else:
        result_type = "battle_unresolved"
    state.event_store.append(
        result_type,
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=attacker.owner_player_id,
        cause_event_no=cause_event_no,
        source=_unit_source(attacker),
        payload={
            "attacker_unit_id": attacker.unit_id,
            "blocker_unit_id": blocker.unit_id,
            "attacker_lethal": attacker_lethal,
            "blocker_lethal": blocker_lethal,
        },
    )


def _battlefield_order(state: GameState) -> dict[str, int]:
    order: dict[str, int] = {}
    for player in state.players.values():
        for index, unit_id in enumerate(player.battlefield.units):
            order[unit_id] = index
    return order


def _get_owned_unit(state: GameState, player_id: str, unit_id: str) -> UnitState:
    unit = state.units[unit_id]
    if unit.owner_player_id != player_id:
        raise ValueError(f"unit {unit_id} is not controlled by {player_id}")
    return unit


def _unit_source(unit: UnitState) -> EventSource:
    return EventSource(
        card_no=unit.card_no,
        card_instance_id=unit.card_instance_id,
        unit_id=unit.unit_id,
    )
