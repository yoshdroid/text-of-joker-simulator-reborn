from __future__ import annotations

from collections.abc import Callable

from .events import EventSource, FactEvent
from .state import AbilityDefinition, GameState, UnitState


EffectHandler = Callable[
    [GameState, UnitState, AbilityDefinition, FactEvent, dict],
    None,
]


def resolve_unit_entered(
    state: GameState,
    entering_unit: UnitState,
    cause_event: FactEvent,
    effect_handlers: dict[str, EffectHandler],
) -> None:
    _resolve_supported_abilities(
        state,
        entering_unit,
        "SELF_CIP",
        cause_event,
        effect_handlers,
    )

    owner = state.players[entering_unit.owner_player_id]
    for unit_id in owner.battlefield.units:
        if unit_id == entering_unit.unit_id:
            continue
        _resolve_supported_abilities(
            state,
            state.units[unit_id],
            "YOUR_CIP",
            cause_event,
            effect_handlers,
        )

    opponent_id = _opponent_id(entering_unit.owner_player_id)
    opponent = state.players[opponent_id]
    for unit_id in opponent.battlefield.units:
        _resolve_supported_abilities(
            state,
            state.units[unit_id],
            "RIVAL_CIP",
            cause_event,
            effect_handlers,
        )


def resolve_unit_destroyed(
    state: GameState,
    destroyed_unit: UnitState,
    cause_event: FactEvent,
    effect_handlers: dict[str, EffectHandler],
) -> None:
    _resolve_supported_abilities(
        state,
        destroyed_unit,
        "SELF_PIG",
        cause_event,
        effect_handlers,
    )


def _resolve_supported_abilities(
    state: GameState,
    ability_source_unit: UnitState,
    timing: str,
    cause_event: FactEvent,
    effect_handlers: dict[str, EffectHandler],
) -> None:
    card = state.card_catalog[ability_source_unit.card_no]
    for ability in card.abilities:
        if ability.status != "supported" or ability.timing != timing:
            continue
        ability_event = state.event_store.append(
            "ability_resolved",
            round_no=state.round_no,
            turn_no=state.turn_no,
            actor_player_id=ability_source_unit.owner_player_id,
            cause_event_no=cause_event.event_no,
            source=EventSource(
                card_no=ability_source_unit.card_no,
                card_instance_id=ability_source_unit.card_instance_id,
                unit_id=ability_source_unit.unit_id,
                ability_id=ability.ability_id,
            ),
            payload={
                "ability_name": ability.name,
                "timing": ability.timing,
            },
        )
        for step in ability.effect_steps:
            handler = effect_handlers.get(str(step.get("effect")))
            if handler is not None:
                handler(state, ability_source_unit, ability, ability_event, step)


def _opponent_id(player_id: str) -> str:
    return "P2" if player_id == "P1" else "P1"
