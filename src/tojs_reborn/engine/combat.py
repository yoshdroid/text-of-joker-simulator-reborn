from __future__ import annotations

from collections.abc import Callable

from .effects import get_effect_handlers
from .events import EventSource
from .rules import get_unit_bp, opponent_id
from .resolver import (
    AbilityCostChoice,
    OptionalAbilityChoice,
    resolve_player_attack_succeeded,
    resolve_unit_battled,
    resolve_unit_attacked,
    resolve_unit_blocked,
    resolve_unit_destroyed,
    resolve_unit_overclocked,
)
from .state import GameState, UnitState

BattleStartedCallback = Callable[[GameState, int], None]


def attack_player(state: GameState, player_id: str, attacker_unit_id: str) -> None:
    attack_event = declare_attack(state, player_id, attacker_unit_id)
    resolve_unblocked_attack(state, attack_event.event_no)


def declare_attack(
    state: GameState,
    player_id: str,
    attacker_unit_id: str,
    optional_ability_choice: OptionalAbilityChoice | None = None,
    ability_cost_choice: AbilityCostChoice | None = None,
):
    attacker = _get_owned_unit(state, player_id, attacker_unit_id)
    action_event = _declare_attack(state, player_id, attacker)
    resolve_unit_attacked(state, attacker, action_event, get_effect_handlers(), optional_ability_choice, ability_cost_choice)
    return action_event


def attack_bypasses_block(state: GameState, attacker_unit_id: str) -> bool:
    attacker = state.units[attacker_unit_id]
    return "unblockable" in attacker.keywords


def resolve_unblocked_attack(state: GameState, attack_event_no: int) -> None:
    attack_event = state.event_store.events[attack_event_no - 1]
    if attack_event.type != "action_declared" or attack_event.payload.get("action") != "attack":
        raise ValueError(f"event is not an attack declaration: {attack_event_no}")
    attacker_unit_id = attack_event.payload["attacker_unit_id"]
    attacker = state.units[attacker_unit_id]
    block_choice_event = state.event_store.append(
        "block_choice_resolved",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=attacker.owner_player_id,
        cause_event_no=attack_event.event_no,
        source=_unit_source(attacker),
        payload={"attacker_unit_id": attacker.unit_id, "choice": "no_block"},
    )
    _process_post_block_choice_trigger_window(state, block_choice_event.event_no)
    opponent = state.players[opponent_id(attacker.owner_player_id)]
    before_life = opponent.life
    opponent.life -= 1
    life_event = state.event_store.append(
        "life_changed",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=attacker.owner_player_id,
        cause_event_no=attack_event.event_no,
        source=_unit_source(attacker),
        payload={
            "player_id": opponent.player_id,
            "before_life": before_life,
            "after_life": opponent.life,
            "amount": -1,
            "reason": "player_attack",
        },
    )
    resolve_player_attack_succeeded(state, attacker, life_event, get_effect_handlers())


def attack_player_legacy(state: GameState, player_id: str, attacker_unit_id: str) -> None:
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
    action_event = declare_attack(state, player_id, attacker_unit_id)
    declare_block(state, opponent_id(player_id), blocker_unit_id, attacker_unit_id, action_event.event_no)


def resolve_blocked_battle(
    state: GameState,
    block_event_no: int,
    optional_ability_choice: OptionalAbilityChoice | None = None,
    ability_cost_choice: AbilityCostChoice | None = None,
    battle_started_callback: BattleStartedCallback | None = None,
) -> None:
    block_event = state.event_store.events[block_event_no - 1]
    if block_event.type != "block_declared":
        raise ValueError(f"event is not a block declaration: {block_event_no}")
    attacker = state.units[block_event.payload["attacker_unit_id"]]
    blocker = state.units[block_event.payload["blocker_unit_id"]]
    battle_event = state.event_store.append(
        "battle_started",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=attacker.owner_player_id,
        cause_event_no=block_event.event_no,
        source=_unit_source(attacker),
        payload={"attacker_unit_id": attacker.unit_id, "blocker_unit_id": blocker.unit_id},
    )
    if battle_started_callback is not None:
        battle_started_callback(state, battle_event.event_no)
    resolve_unit_battled(state, attacker, battle_event, get_effect_handlers(), optional_ability_choice, ability_cost_choice)
    resolve_unit_battled(state, blocker, battle_event, get_effect_handlers(), optional_ability_choice, ability_cost_choice)
    _deal_battle_damage(state, attacker, blocker, battle_event.event_no)
    _deal_battle_damage(state, blocker, attacker, battle_event.event_no)
    winner = _emit_battle_result(state, attacker, blocker, battle_event.event_no)
    if winner is not None:
        _reward_battle_winner(state, winner, battle_event.event_no, optional_ability_choice, ability_cost_choice)
    destroy_lethal_units(state, [attacker, blocker], battle_event.event_no)


def declare_block(
    state: GameState,
    player_id: str,
    blocker_unit_id: str,
    attacker_unit_id: str,
    cause_event_no: int,
    optional_ability_choice: OptionalAbilityChoice | None = None,
    ability_cost_choice: AbilityCostChoice | None = None,
    battle_started_callback: BattleStartedCallback | None = None,
):
    blocker = _get_owned_unit(state, player_id, blocker_unit_id)
    block_event = state.event_store.append(
        "block_declared",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=player_id,
        cause_event_no=cause_event_no,
        source=_unit_source(blocker),
        payload={"blocker_unit_id": blocker_unit_id, "attacker_unit_id": attacker_unit_id},
    )
    resolve_unit_blocked(state, blocker, block_event, get_effect_handlers(), optional_ability_choice, ability_cost_choice)
    block_choice_event = state.event_store.append(
        "block_choice_resolved",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=state.units[attacker_unit_id].owner_player_id,
        cause_event_no=block_event.event_no,
        source=_unit_source(blocker),
        payload={"blocker_unit_id": blocker_unit_id, "attacker_unit_id": attacker_unit_id, "choice": "block"},
    )
    _process_post_block_choice_trigger_window(state, block_choice_event.event_no)
    resolve_blocked_battle(state, block_event.event_no, optional_ability_choice, ability_cost_choice, battle_started_callback)
    return block_event


def _process_post_block_choice_trigger_window(state: GameState, cause_event_no: int) -> None:
    from .windows import process_trigger_window

    process_trigger_window(state, cause_event_no, get_effect_handlers(), window_name="post_block_choice")


def _declare_attack(state: GameState, player_id: str, attacker: UnitState):
    if state.turn_player_id != player_id:
        raise ValueError(f"not turn player: {player_id}")
    if attacker.exhausted:
        raise ValueError(f"unit already exhausted: {attacker.unit_id}")
    if attacker.attack_restricted_turn_no == state.turn_no:
        raise ValueError(f"unit cannot attack on the turn it entered: {attacker.unit_id}")
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
        if unit.unit_id in state.units:
            _destroy_unit(state, unit, cause_event_no)


def destroy_unit(state: GameState, unit: UnitState, cause_event_no: int, *, reason: str = "effect") -> None:
    if unit.unit_id not in state.units:
        return
    _destroy_unit(state, unit, cause_event_no, reason=reason)


def destroy_units(state: GameState, units: list[UnitState], cause_event_no: int, *, reason: str = "effect") -> None:
    battlefield_order = _battlefield_order(state)
    destroyed_units = [unit for unit in units if unit.unit_id in state.units]
    destroyed_units.sort(
        key=lambda unit: (
            0 if unit.owner_player_id == state.turn_player_id else 1,
            battlefield_order.get(unit.unit_id, 9999),
        )
    )
    for unit in destroyed_units:
        if unit.unit_id in state.units:
            _destroy_unit(state, unit, cause_event_no, reason=reason)


def _destroy_unit(state: GameState, unit: UnitState, cause_event_no: int, *, reason: str = "battle") -> None:
    if unit.unit_id in state.pending_destroyed_units:
        return
    player = state.players[unit.owner_player_id]
    destroyed_event = state.event_store.append(
        "unit_destroyed",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=unit.owner_player_id,
        cause_event_no=cause_event_no,
        source=_unit_source(unit),
        payload={"reason": reason},
    )
    resolve_unit_destroyed(state, unit, destroyed_event, get_effect_handlers())

    from .windows import has_matching_intercept_window

    if has_matching_intercept_window(state, "unit_destroyed", destroyed_event.event_no):
        state.pending_destroyed_units[unit.unit_id] = {
            "cause_event_no": cause_event_no,
            "destroyed_event_no": destroyed_event.event_no,
        }
        return
    _move_destroyed_unit_to_discard(state, unit, cause_event_no)


def finalize_pending_destroyed_unit(state: GameState, destroyed_event_no: int) -> None:
    for unit_id, pending in list(state.pending_destroyed_units.items()):
        if pending.get("destroyed_event_no") != destroyed_event_no:
            continue
        unit = state.units.get(unit_id)
        if unit is not None:
            _move_destroyed_unit_to_discard(state, unit, int(pending["cause_event_no"]))
        del state.pending_destroyed_units[unit_id]


def _move_destroyed_unit_to_discard(state: GameState, unit: UnitState, cause_event_no: int) -> None:
    player = state.players[unit.owner_player_id]
    if unit.unit_id not in player.battlefield.units:
        return
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
    del state.units[unit.unit_id]


def _emit_battle_result(
    state: GameState,
    attacker: UnitState,
    blocker: UnitState,
    cause_event_no: int,
) -> UnitState | None:
    attacker_lethal = attacker.current_damage >= get_unit_bp(state, attacker)
    blocker_lethal = blocker.current_damage >= get_unit_bp(state, blocker)
    winner: UnitState | None = None
    if attacker_lethal and blocker_lethal:
        result_type = "battle_draw"
    elif blocker_lethal:
        result_type = "battle_won"
        winner = attacker
    elif attacker_lethal:
        result_type = "battle_lost"
        winner = blocker
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
            "winner_unit_id": winner.unit_id if winner is not None else None,
            "winner_player_id": winner.owner_player_id if winner is not None else None,
        },
    )
    return winner


def _reward_battle_winner(
    state: GameState,
    winner: UnitState,
    cause_event_no: int,
    optional_ability_choice: OptionalAbilityChoice | None,
    ability_cost_choice: AbilityCostChoice | None,
) -> None:
    if winner.unit_id not in state.units:
        return
    before_level = winner.level
    leveled_up = False
    if winner.level < 3:
        winner.level += 1
        leveled_up = True
        state.card_instances[winner.card_instance_id].level = winner.level
        level_event = state.event_store.append(
            "unit_level_changed",
            round_no=state.round_no,
            turn_no=state.turn_no,
            actor_player_id=winner.owner_player_id,
            cause_event_no=cause_event_no,
            source=_unit_source(winner),
            payload={
                "unit_id": winner.unit_id,
                "before_level": before_level,
                "after_level": winner.level,
                "reason": "battle_win",
                "after_bp": get_unit_bp(state, winner),
            },
        )
        _clear_battle_winner_damage(state, winner, cause_event_no)
        if winner.level >= 3:
            overclock_event = state.event_store.append(
                "unit_overclocked",
                round_no=state.round_no,
                turn_no=state.turn_no,
                actor_player_id=winner.owner_player_id,
                cause_event_no=level_event.event_no,
                source=_unit_source(winner),
                payload={"level": winner.level, "reason": "battle_win"},
            )
            if winner.exhausted:
                winner.exhausted = False
                state.event_store.append(
                    "unit_action_recovered",
                    round_no=state.round_no,
                    turn_no=state.turn_no,
                    actor_player_id=winner.owner_player_id,
                    cause_event_no=overclock_event.event_no,
                    source=_unit_source(winner),
                    payload={"unit_id": winner.unit_id, "reason": "overclock"},
                )
            resolve_unit_overclocked(
                state,
                winner,
                overclock_event,
                get_effect_handlers(),
                optional_ability_choice,
                ability_cost_choice,
            )
    if not leveled_up:
        return


def _clear_battle_winner_damage(state: GameState, winner: UnitState, cause_event_no: int) -> None:
    if winner.current_damage == 0:
        return
    before_damage = winner.current_damage
    winner.current_damage = 0
    state.event_store.append(
        "unit_damage_cleared",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=winner.owner_player_id,
        cause_event_no=cause_event_no,
        source=_unit_source(winner),
        payload={
            "unit_id": winner.unit_id,
            "before_damage": before_damage,
            "after_damage": 0,
            "reason": "battle_win",
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
