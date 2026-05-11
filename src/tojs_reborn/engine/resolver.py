from __future__ import annotations

from collections.abc import Callable

from .events import EventSource, FactEvent
from .state import AbilityDefinition, GameState, UnitState


EffectHandler = Callable[
    [GameState, UnitState, AbilityDefinition, FactEvent, dict],
    None,
]
OptionalAbilityChoice = Callable[
    [GameState, UnitState, AbilityDefinition, FactEvent],
    bool,
]


def resolve_unit_entered(
    state: GameState,
    entering_unit: UnitState,
    cause_event: FactEvent,
    effect_handlers: dict[str, EffectHandler],
    optional_ability_choice: OptionalAbilityChoice | None = None,
) -> None:
    _resolve_supported_abilities(
        state,
        entering_unit,
        "SELF_CIP",
        cause_event,
        effect_handlers,
        optional_ability_choice,
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
            optional_ability_choice,
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
            optional_ability_choice,
        )


def resolve_unit_destroyed(
    state: GameState,
    destroyed_unit: UnitState,
    cause_event: FactEvent,
    effect_handlers: dict[str, EffectHandler],
    optional_ability_choice: OptionalAbilityChoice | None = None,
) -> None:
    _resolve_supported_abilities(
        state,
        destroyed_unit,
        "SELF_PIG",
        cause_event,
        effect_handlers,
        optional_ability_choice,
    )


def resolve_unit_attacked(
    state: GameState,
    attacking_unit: UnitState,
    cause_event: FactEvent,
    effect_handlers: dict[str, EffectHandler],
    optional_ability_choice: OptionalAbilityChoice | None = None,
) -> None:
    _resolve_supported_abilities(
        state,
        attacking_unit,
        "SELF_ATK",
        cause_event,
        effect_handlers,
        optional_ability_choice,
    )


def resolve_unit_blocked(
    state: GameState,
    blocking_unit: UnitState,
    cause_event: FactEvent,
    effect_handlers: dict[str, EffectHandler],
    optional_ability_choice: OptionalAbilityChoice | None = None,
) -> None:
    _resolve_supported_abilities(
        state,
        blocking_unit,
        "SELF_BLOCK",
        cause_event,
        effect_handlers,
        optional_ability_choice,
    )


def resolve_turn_ended(
    state: GameState,
    player_id: str,
    cause_event: FactEvent,
    effect_handlers: dict[str, EffectHandler],
    optional_ability_choice: OptionalAbilityChoice | None = None,
) -> None:
    for unit_id in list(state.players[player_id].battlefield.units):
        if unit_id in state.units:
            _resolve_supported_abilities(
                state,
                state.units[unit_id],
                "SELF_TURN_END",
                cause_event,
                effect_handlers,
                optional_ability_choice,
            )


def resolve_unit_overclocked(
    state: GameState,
    unit: UnitState,
    cause_event: FactEvent,
    effect_handlers: dict[str, EffectHandler],
    optional_ability_choice: OptionalAbilityChoice | None = None,
) -> None:
    _resolve_supported_abilities(
        state,
        unit,
        "SELF_OC",
        cause_event,
        effect_handlers,
        optional_ability_choice,
    )


def _resolve_supported_abilities(
    state: GameState,
    ability_source_unit: UnitState,
    timing: str,
    cause_event: FactEvent,
    effect_handlers: dict[str, EffectHandler],
    optional_ability_choice: OptionalAbilityChoice | None = None,
) -> None:
    card = state.card_catalog[ability_source_unit.card_no]
    for ability in card.abilities:
        if ability.status != "supported" or ability.timing != timing:
            continue
        if not _condition_matches(state, ability_source_unit, ability):
            continue
        selector = ability.raw.get("selector")
        if isinstance(selector, dict) and selector.get("type") == "unit":
            if not _has_unit_target(state, ability_source_unit, selector):
                continue
        if ability.optional and not _choose_optional_ability(
            state,
            ability_source_unit,
            ability,
            cause_event,
            optional_ability_choice,
        ):
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
                "optional": ability.optional,
            },
        )
        for step in ability.effect_steps:
            handler = effect_handlers.get(str(step.get("effect")))
            if handler is not None:
                handler(state, ability_source_unit, ability, ability_event, step)


def _choose_optional_ability(
    state: GameState,
    ability_source_unit: UnitState,
    ability: AbilityDefinition,
    cause_event: FactEvent,
    optional_ability_choice: OptionalAbilityChoice | None,
) -> bool:
    request_event = state.event_store.append(
        "choice_requested",
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
            "type": "optional_ability",
            "ability_id": ability.ability_id,
            "ability_name": ability.name,
            "legal_choices": [
                {"type": "pass_ability", "ability_id": ability.ability_id},
                {"type": "use_ability", "ability_id": ability.ability_id},
            ],
        },
    )
    use_ability = bool(optional_ability_choice(state, ability_source_unit, ability, request_event)) if optional_ability_choice else False
    state.event_store.append(
        "choice_selected",
        round_no=state.round_no,
        turn_no=state.turn_no,
        actor_player_id=ability_source_unit.owner_player_id,
        cause_event_no=request_event.event_no,
        source=EventSource(
            card_no=ability_source_unit.card_no,
            card_instance_id=ability_source_unit.card_instance_id,
            unit_id=ability_source_unit.unit_id,
            ability_id=ability.ability_id,
        ),
        payload={
            "type": "optional_ability",
            "ability_id": ability.ability_id,
            "choice": "use_ability" if use_ability else "pass_ability",
            "fallback": "pass_ability" if optional_ability_choice is None else None,
        },
    )
    return use_ability


def _condition_matches(state: GameState, ability_source_unit: UnitState, ability: AbilityDefinition) -> bool:
    condition = ability.raw.get("condition")
    if condition is None:
        return True
    if not isinstance(condition, dict):
        return False
    if condition.get("type") != "used_other_card_this_turn":
        return False
    min_cp = int(condition.get("min_cp", 0))
    color = condition.get("color")
    for event in state.event_store.events:
        if event.turn_no != state.turn_no or event.type != "action_declared":
            continue
        if event.payload.get("action") != "drive_unit":
            continue
        if event.actor_player_id != ability_source_unit.owner_player_id:
            continue
        if condition.get("exclude_source") and event.source.card_instance_id == ability_source_unit.card_instance_id:
            continue
        if event.source.card_no is None:
            continue
        card = state.card_catalog[event.source.card_no]
        if (card.cp or 0) >= min_cp and (color is None or card.color == color):
            return True
    return False


def _has_unit_target(state: GameState, source_unit: UnitState, selector: dict) -> bool:
    controller = selector.get("controller")
    if controller == "rival":
        player_id = _opponent_id(source_unit.owner_player_id)
    elif controller == "owner":
        player_id = source_unit.owner_player_id
    else:
        player_id = source_unit.owner_player_id
    return any(unit_id in state.units for unit_id in state.players[player_id].battlefield.units)


def _opponent_id(player_id: str) -> str:
    return "P2" if player_id == "P1" else "P1"
