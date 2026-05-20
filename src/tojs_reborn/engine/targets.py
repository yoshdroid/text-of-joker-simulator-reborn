from __future__ import annotations

from .events import FactEvent
from .rules import opponent_id
from .state import AbilityDefinition, GameState, UnitState


def resolve_player_id(owner_player_id: str, player_ref) -> str:
    if player_ref == "rival":
        return opponent_id(owner_player_id)
    return owner_player_id


def resolve_unit_target_for_effect(
    state: GameState,
    source_unit: UnitState,
    ability: AbilityDefinition,
    ability_event: FactEvent,
    target_ref,
) -> UnitState | None:
    event_target = _resolve_event_unit_target(state, source_unit, ability_event, target_ref)
    if event_target is not None:
        return event_target
    selector = ability.raw.get("selector")
    if not isinstance(selector, dict):
        return _resolve_unit_target(state, source_unit, target_ref)
    if target_ref != selector.get("id") or selector.get("type") != "unit":
        return _resolve_unit_target(state, source_unit, target_ref, selector)
    player_id = resolve_player_id(source_unit.owner_player_id, selector.get("controller"))
    candidates = [unit.unit_id for unit in unit_candidates_for_selector(state, player_id, selector)]
    if not candidates:
        return None
    request_event = state.event_store.append(
        "choice_requested",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=source_unit.owner_player_id,
        cause_event_no=ability_event.event_no,
        source=ability_event.source,
        payload={
            "choice_id": selector.get("id"),
            "type": "unit",
            "candidate_unit_ids": candidates,
            "required": bool(selector.get("required", True)),
        },
    )
    chosen_unit_id = candidates[0]
    state.event_store.append(
        "choice_selected",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=source_unit.owner_player_id,
        cause_event_no=request_event.event_no,
        source=ability_event.source,
        payload={
            "choice_id": selector.get("id"),
            "chosen_unit_id": chosen_unit_id,
            "fallback": "first_legal",
        },
    )
    return state.units[chosen_unit_id]


def resolve_unit_targets_for_effect(
    state: GameState,
    source_unit: UnitState,
    ability: AbilityDefinition,
    _ability_event: FactEvent,
    target_ref,
) -> list[UnitState]:
    selector = ability.raw.get("selector")
    if not isinstance(selector, dict):
        target = _resolve_unit_target(state, source_unit, target_ref)
        return [] if target is None else [target]
    if target_ref != selector.get("id") or selector.get("type") != "unit":
        target = _resolve_unit_target(state, source_unit, target_ref, selector)
        return [] if target is None else [target]
    player_id = resolve_player_id(source_unit.owner_player_id, selector.get("controller"))
    candidates = unit_candidates_for_selector(state, player_id, selector)
    count = selector.get("count", 1)
    if count == "all":
        return candidates
    return candidates[: int(count)]


def unit_candidates_for_selector(state: GameState, player_id: str, selector: dict) -> list[UnitState]:
    candidates = [state.units[unit_id] for unit_id in state.players[player_id].battlefield.units if unit_id in state.units]
    if "exhausted" in selector:
        expected = bool(selector["exhausted"])
        candidates = [unit for unit in candidates if unit.exhausted == expected]
    if "min_level" in selector:
        min_level = int(selector["min_level"])
        candidates = [unit for unit in candidates if unit.level >= min_level]
    if "max_level" in selector:
        max_level = int(selector["max_level"])
        candidates = [unit for unit in candidates if unit.level <= max_level]
    return candidates


def _resolve_unit_target(
    state: GameState,
    source_unit: UnitState,
    target_ref,
    selector: dict | None = None,
) -> UnitState | None:
    if target_ref == "source":
        return source_unit
    if isinstance(target_ref, str) and target_ref in state.units:
        return state.units[target_ref]
    if selector is None:
        return source_unit if target_ref in (None, "source") else None
    player_id = resolve_player_id(source_unit.owner_player_id, selector.get("controller"))
    candidates = unit_candidates_for_selector(state, player_id, selector)
    return candidates[0] if candidates else None


def _resolve_event_unit_target(
    state: GameState,
    source_unit: UnitState,
    ability_event: FactEvent,
    target_ref,
) -> UnitState | None:
    if target_ref not in {"event_attacker", "owner_battle_unit", "rival_battle_unit"}:
        return None
    cause_event = _window_cause_event_for_ability(state, ability_event)
    if cause_event is None or cause_event.type != "battle_started":
        return None
    attacker_unit_id = cause_event.payload.get("attacker_unit_id") or cause_event.source.unit_id
    blocker_unit_id = cause_event.payload.get("blocker_unit_id")
    if target_ref == "event_attacker":
        return state.units.get(attacker_unit_id) if isinstance(attacker_unit_id, str) else None
    battle_units = [
        state.units.get(unit_id)
        for unit_id in (attacker_unit_id, blocker_unit_id)
        if isinstance(unit_id, str)
    ]
    if target_ref == "rival_battle_unit":
        return next(
            (
                unit
                for unit in battle_units
                if unit is not None and unit.owner_player_id != source_unit.owner_player_id
            ),
            None,
        )
    if isinstance(attacker_unit_id, str):
        attacker = state.units.get(attacker_unit_id)
        if attacker is not None and attacker.owner_player_id == source_unit.owner_player_id:
            return attacker
    if isinstance(blocker_unit_id, str):
        blocker = state.units.get(blocker_unit_id)
        if blocker is not None and blocker.owner_player_id == source_unit.owner_player_id:
            return blocker
    return None


def _window_cause_event_for_ability(state: GameState, ability_event: FactEvent) -> FactEvent | None:
    activation_event = _event_by_no_or_none(state, ability_event.cause_event_no)
    if activation_event is None:
        return None
    return _event_by_no_or_none(state, activation_event.cause_event_no)


def _event_by_no_or_none(state: GameState, event_no: int | None) -> FactEvent | None:
    if event_no is None:
        return None
    for event in state.event_store.events:
        if event.event_no == event_no:
            return event
    return None
