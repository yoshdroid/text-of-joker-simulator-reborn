from __future__ import annotations

from .events import EventSource
from .rules import get_unit_bp, opponent_id
from .state import GameState, UnitState


def attack_player(state: GameState, player_id: str, attacker_unit_id: str) -> None:
    attacker = _get_owned_unit(state, player_id, attacker_unit_id)
    action_event = _declare_attack(state, player_id, attacker)
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
    _destroy_if_lethal(state, attacker, battle_event.event_no)
    _destroy_if_lethal(state, blocker, battle_event.event_no)


def _declare_attack(state: GameState, player_id: str, attacker: UnitState):
    if attacker.exhausted:
        raise ValueError(f"unit already exhausted: {attacker.unit_id}")
    action_event = state.event_store.append(
        "action_declared",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        source=_unit_source(attacker),
        payload={"action": "attack"},
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


def _destroy_if_lethal(state: GameState, unit: UnitState, cause_event_no: int) -> None:
    if unit.unit_id not in state.units:
        return
    if unit.current_damage < get_unit_bp(state, unit):
        return
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
    state.event_store.append(
        "unit_destroyed",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=unit.owner_player_id,
        cause_event_no=cause_event_no,
        source=_unit_source(unit),
        payload={"reason": "battle"},
    )
    del state.units[unit.unit_id]


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
